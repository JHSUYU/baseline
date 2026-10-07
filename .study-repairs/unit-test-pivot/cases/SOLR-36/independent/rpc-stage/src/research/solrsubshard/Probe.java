package research.solrsubshard;

import java.io.BufferedWriter;
import java.io.IOException;
import java.io.InputStream;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.Properties;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import org.apache.solr.common.SolrException;
import org.apache.solr.common.cloud.DocRouter;
import org.apache.solr.common.cloud.Replica;
import org.apache.solr.common.cloud.Slice;
import org.apache.solr.update.AddUpdateCommand;
import org.apache.solr.update.DeleteUpdateCommand;
import org.apache.solr.update.SolrCmdDistributor;
import org.apache.zookeeper.KeeperException;
import org.slf4j.MDC;

/** Logical subshard/replica identity and physical Jetty node recorded separately. */
public final class Probe {
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final ConcurrentHashMap<String, AtomicInteger> ORDINALS =
      new ConcurrentHashMap<>();
  private static final AtomicInteger NEXT_STEP = new AtomicInteger(1);
  private static final ThreadLocal<String> TARGET_SOURCE = new ThreadLocal<>();
  private static final ThreadLocal<String> TARGET_PHYSICAL = new ThreadLocal<>();
  private static final ThreadLocal<String> TARGET_PHASE = new ThreadLocal<>();
  private static final ThreadLocal<String> CHILD_RANGE = new ThreadLocal<>();
  private static final ThreadLocal<String> PARENT_RANGE = new ThreadLocal<>();
  private static final Properties FAULT = new Properties();
  private static BufferedWriter output;
  private static int plannedSteps;

  private Probe() {}

  public static synchronized void initialize() {
    if (output != null) return;
    String trace = System.getProperty("solrsubshard.trace.file");
    if (trace == null || trace.isEmpty())
      throw new IllegalArgumentException("solrsubshard.trace.file required");
    try {
      Path path = Paths.get(trace);
      Files.createDirectories(path.toAbsolutePath().getParent());
      output = Files.newBufferedWriter(path, StandardCharsets.UTF_8,
          StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
      String plan = System.getProperty("solrsubshard.fault.plan", "");
      if (!plan.isEmpty()) {
        try (InputStream input = Files.newInputStream(Paths.get(plan))) {
          FAULT.load(input);
        }
        plannedSteps = Integer.parseInt(FAULT.getProperty("count", "1"));
        if (plannedSteps < 1 || plannedSteps > 10)
          throw new IllegalArgumentException("fault plan count must be 1..10");
        for (int step = 1; step <= plannedSteps; step++) {
          String prefix = "step." + step + ".";
          for (String field : new String[]{"marker", "siteId", "sourceKey", "resource", "hitOrdinal"}) {
            if (FAULT.getProperty(prefix + field) == null)
              throw new IllegalArgumentException("missing fault field " + prefix + field);
          }
        }
      }
      Runtime.getRuntime().addShutdownHook(new Thread(Probe::close, "solrsubshard-probe-close"));
    } catch (IOException failure) {
      throw new IllegalStateException("SOLR subshard trace init failed", failure);
    }
  }

  public static synchronized void close() {
    if (output == null) return;
    emit("SUMMARY", "", "", "", "", "", 0, false,
        "applied=" + (NEXT_STEP.get() - 1) + "/" + plannedSteps);
    try { output.flush(); output.close(); }
    catch (IOException failure) { failure.printStackTrace(System.err); }
    output = null;
  }

  private static String quote(String value) {
    if (value == null) return "null";
    StringBuilder result = new StringBuilder(value.length() + 2).append('"');
    for (char character : value.toCharArray()) {
      if (character == '"' || character == '\\') result.append('\\').append(character);
      else if (character == '\n') result.append("\\n");
      else if (character == '\r') result.append("\\r");
      else if (character == '\t') result.append("\\t");
      else if (character < 0x20) result.append(String.format("\\u%04x", (int) character));
      else result.append(character);
    }
    return result.append('"').toString();
  }

  private static synchronized void emit(String event, String marker, String site,
                                        String source, String physicalNode,
                                        String resource, int ordinal, boolean applied,
                                        String detail) {
    if (output == null) return;
    String row = "{\"event\":" + quote(event)
        + ",\"seq\":" + SEQUENCE.incrementAndGet()
        + ",\"timeNs\":" + System.nanoTime()
        + ",\"threadId\":" + Thread.currentThread().getId()
        + ",\"marker\":" + quote(marker)
        + ",\"siteId\":" + quote(site)
        + ",\"sourceKey\":" + quote(source)
        + ",\"physicalNode\":" + quote(physicalNode)
        + ",\"resource\":" + quote(resource)
        + ",\"hitOrdinal\":" + ordinal
        + ",\"applied\":" + applied
        + ",\"detail\":" + quote(detail) + "}";
    try { output.write(row); output.newLine(); }
    catch (IOException failure) { throw new IllegalStateException("trace write failed", failure); }
  }

  public static void targetEnter(String collection, String shard, String replica,
                                 String physicalNode, Object phase) {
    String source = collection == null || shard == null || replica == null ?
        "UNRESOLVED:SUBSHARD_REPLICA" :
        "SOLR/SUBSHARD/" + collection + "/" + shard + "/" + replica;
    TARGET_SOURCE.set(source);
    TARGET_PHYSICAL.set(physicalNode);
    TARGET_PHASE.set(String.valueOf(phase));
    CHILD_RANGE.remove();
    PARENT_RANGE.remove();
    emit("TARGET_ENTER", "SOLR36_37:DEFENSIVE_CHECKS",
        "DistributedZkUpdateProcessor.doDefensiveChecks", source, physicalNode,
        collection, 0, false, "phase=" + phase);
  }

  public static void guard36(Slice.State state) {
    emit("TARGET_CHECK", "SOLR36:ACTIVE_SUBSHARD_GUARD",
        "DistributedZkUpdateProcessor.java:986", TARGET_SOURCE.get(),
        TARGET_PHYSICAL.get(), "", 0, false,
        "state=" + state + ";phase=" + TARGET_PHASE.get());
  }

  public static void rangeOperands(DocRouter.Range child, DocRouter.Range parent) {
    CHILD_RANGE.set(String.valueOf(child));
    PARENT_RANGE.set(String.valueOf(parent));
  }

  public static void guard37(boolean isSubset) {
    emit("TARGET_CHECK", "SOLR37:CHILD_RANGE_SUBSET_GUARD",
        "DistributedZkUpdateProcessor.java:994", TARGET_SOURCE.get(),
        TARGET_PHYSICAL.get(), "", 0, false,
        "child=" + CHILD_RANGE.get() + ";parent=" + PARENT_RANGE.get()
            + ";subset=" + isSubset + ";phase=" + TARGET_PHASE.get());
  }

  public static void targetThrow(Throwable failure, int line) {
    if (!(failure instanceof SolrException)) return;
    String message = failure.getMessage();
    String marker;
    if (line == 987 && message != null && message.equals(
        "Request says it is coming from parent shard leader but we are in active state"))
      marker = "SOLR36:ACTIVE_SUBSHARD_THROW";
    else if (line == 995 && message != null && message.equals(
        "Request says it is coming from parent shard leader but parent hash range is not superset of my range"))
      marker = "SOLR37:CHILD_RANGE_THROW";
    else return;
    emit("TARGET_THROW", marker, "DistributedZkUpdateProcessor.java:" + line,
        TARGET_SOURCE.get(), TARGET_PHYSICAL.get(), "", 0, false,
        failure.getClass().getName() + ": " + message);
  }

  /** The original synchronous parent-to-child HTTP request, immediately before send. */
  public static void rpcSend(SolrCmdDistributor.Req request) throws SocketTimeoutException {
    if (request == null || request.node == null || request.uReq == null
        || request.uReq.getParams() == null) return;
    final String commandKind;
    if (request.cmd instanceof AddUpdateCommand) {
      commandKind = "Add";
    } else if (request.cmd instanceof DeleteUpdateCommand
               && ((DeleteUpdateCommand) request.cmd).isDeleteById()) {
      commandKind = "DeleteById";
    } else {
      return;
    }
    String fromParent = request.uReq.getParams().get("distrib.from.parent");
    String collection = request.node.getCollection();
    String shard = request.node.getShardId();
    if (!"shard1".equals(fromParent) || !"collection1".equals(collection)
        || shard == null || !shard.startsWith("shard1_")) return;
    if (request.node.getNodeProps() == null
        || !(request.node.getNodeProps().getNodeProps() instanceof Replica)) return;
    Replica child = (Replica) request.node.getNodeProps().getNodeProps();
    String replica = child.getName();
    if (replica == null) return;
    String marker = "FAULT:HTTP:parentForward" + commandKind;
    String site = "org.apache.solr.update.SolrCmdDistributor.submit#L309->Http2SolrClient.request";
    String logicalTarget = "SOLR/SUBSHARD/" + collection + "/" + shard + "/" + replica;
    String physicalTarget = request.node.getUrl();
    String resource = "/update/" + commandKind + "/" + collection + "/" + shard
        + "/" + replica;
    String key = marker + '\u0000' + site + '\u0000' + logicalTarget + '\u0000' + resource;
    int ordinal = ORDINALS.computeIfAbsent(key, unused -> new AtomicInteger())
        .incrementAndGet();
    int step = NEXT_STEP.get();
    boolean matched = apply(marker, site, logicalTarget, resource, ordinal);
    emit("IO_OBSERVED", marker, site, logicalTarget, physicalTarget,
        resource, ordinal, matched,
        "command=" + commandKind + ";fromParent=" + fromParent
            + ";senderShard=" + MDC.get("shard")
            + ";senderReplica=" + MDC.get("replica")
            + ";destNode=" + child.getNodeName());
    if (!matched) return;
    String mode = FAULT.getProperty("step." + step + ".faultMode", "TIMEOUT");
    if ("TIMEOUT".equals(mode)) {
      throw new SocketTimeoutException("injected parent-to-child HTTP timeout");
    }
    if (!"DELAY".equals(mode))
      throw new IllegalArgumentException("unknown parent-forward fault mode " + mode);
    int delayMs = Integer.parseInt(FAULT.getProperty("step." + step + ".delayMs", "10000"));
    if (delayMs < 1 || delayMs > 30000)
      throw new IllegalArgumentException("delayMs must be 1..30000");
    try {
      Thread.sleep(delayMs);
    } catch (InterruptedException interrupted) {
      Thread.currentThread().interrupt();
      throw new SocketTimeoutException("injected parent-to-child HTTP delay interrupted");
    }
    emit("FAULT_EFFECT", marker, site, logicalTarget, physicalTarget,
        resource, ordinal, true, "delayMs=" + delayMs + ";sent=next");
  }

  private static String mdcValue(String name, String prefix) {
    String value = MDC.get(name);
    return value != null && value.startsWith(prefix) ? value.substring(prefix.length()) : null;
  }

  private static String collectionSource(String path) {
    if (path.startsWith("/collections/")) {
      String suffix = path.substring("/collections/".length());
      return "SOLR/COLLECTION/" + suffix.split("/", 2)[0];
    }
    return "UNRESOLVED:ZK:" + path;
  }

  private static boolean apply(String marker, String site, String source,
                               String resource, int ordinal) {
    int step = NEXT_STEP.get();
    if (step > plannedSteps) return false;
    String prefix = "step." + step + ".";
    boolean exact = marker.equals(FAULT.getProperty(prefix + "marker"))
        && site.equals(FAULT.getProperty(prefix + "siteId"))
        && source.equals(FAULT.getProperty(prefix + "sourceKey"))
        && resource.equals(FAULT.getProperty(prefix + "resource"))
        && ordinal == Integer.parseInt(FAULT.getProperty(prefix + "hitOrdinal"));
    if (exact && (source.startsWith("UNRESOLVED:") || site.startsWith("UNRESOLVED:")))
      throw new IllegalStateException("refuse fault on unresolved I/O identity");
    return exact && NEXT_STEP.compareAndSet(step, step + 1);
  }

  /** Observe a real ZooKeeper operation inside Solr's retry callable. */
  public static void nativeEntry(String path, String api) throws KeeperException {
    if (path == null) return;
    StackTraceElement[] stack = Thread.currentThread().getStackTrace();
    StackTraceElement caller = null;
    boolean inDefensiveCheck = false;
    for (StackTraceElement frame : stack) {
      if (frame.getClassName().equals("org.apache.solr.update.processor.DistributedZkUpdateProcessor")
          && frame.getMethodName().equals("doDefensiveChecks")) inDefensiveCheck = true;
      if (caller == null && frame.getClassName().startsWith("org.apache.solr.")
          && !frame.getClassName().equals("org.apache.solr.common.cloud.SolrZkClient")
          && !frame.getClassName().equals("org.apache.solr.common.cloud.ZkCmdExecutor"))
        caller = frame;
    }
    String collection = mdcValue("collection", "c:");
    String shard = mdcValue("shard", "s:");
    String replica = mdcValue("replica", "r:");
    String source = inDefensiveCheck && TARGET_SOURCE.get() != null ?
        TARGET_SOURCE.get() :
        collection != null && shard != null && replica != null ?
            "SOLR/REPLICA/" + collection + "/" + shard + "/" + replica :
            collectionSource(path);
    String site = caller == null ? "UNRESOLVED:CALLER" : caller.getClassName()
        + "." + caller.getMethodName() + "#L" + caller.getLineNumber()
        + "->SolrZkClient." + api;
    int end = api.indexOf('$', "lambda$".length());
    if (!api.startsWith("lambda$") || end < 0)
      throw new IllegalArgumentException("unexpected retry method " + api);
    String marker = "FAULT:ZK_NATIVE:" + api.substring("lambda$".length(), end);
    String key = marker + '\u0000' + site + '\u0000' + source + '\u0000' + path;
    int ordinal = ORDINALS.computeIfAbsent(key, unused -> new AtomicInteger())
        .incrementAndGet();
    boolean matched = apply(marker, site, source, path, ordinal);
    String node = inDefensiveCheck ? TARGET_PHYSICAL.get() : MDC.get("node_name");
    emit("IO_OBSERVED", marker, site, source, node == null ? "" : node,
        path, ordinal, matched, "path=" + path + ";mdcCore=" + MDC.get("core"));
    if (matched) throw KeeperException.create(KeeperException.Code.CONNECTIONLOSS, path);
  }
}
