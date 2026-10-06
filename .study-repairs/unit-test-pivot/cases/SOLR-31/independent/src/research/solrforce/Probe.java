package research.solrforce;

import java.io.BufferedWriter;
import java.io.IOException;
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
import org.apache.solr.common.cloud.Replica;
import org.apache.solr.request.SolrQueryRequest;
import org.apache.zookeeper.KeeperException;
import org.slf4j.MDC;

/** Exact target events, physical node evidence, and retry-internal ZK fault points. */
public final class Probe {
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final ConcurrentHashMap<String, AtomicInteger> ORDINALS =
      new ConcurrentHashMap<>();
  private static final ThreadLocal<String> TARGET_SOURCE = new ThreadLocal<>();
  private static final AtomicInteger NEXT_STEP = new AtomicInteger(1);
  private static final Properties FAULT = new Properties();
  private static BufferedWriter output;
  private static int plannedSteps;

  private Probe() {}

  public static synchronized void initialize() {
    if (output != null) return;
    String trace = System.getProperty("solrforce.trace.file");
    if (trace == null || trace.isEmpty())
      throw new IllegalArgumentException("solrforce.trace.file required");
    try {
      Path path = Paths.get(trace);
      Files.createDirectories(path.toAbsolutePath().getParent());
      output = Files.newBufferedWriter(path, StandardCharsets.UTF_8,
          StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
      String plan = System.getProperty("solrforce.fault.plan", "");
      if (!plan.isEmpty()) {
        try (java.io.InputStream input = Files.newInputStream(Paths.get(plan))) {
          FAULT.load(input);
        }
        plannedSteps = Integer.parseInt(FAULT.getProperty("count", "1"));
        if (plannedSteps < 1 || plannedSteps > 10)
          throw new IllegalArgumentException("fault plan count must be 1..10");
        for (int step = 1; step <= plannedSteps; step++) {
          String prefix = "step." + step + ".";
          for (String field : new String[]{"siteId", "sourceKey", "resource", "hitOrdinal"}) {
            if (FAULT.getProperty(prefix + field) == null)
              throw new IllegalArgumentException("missing fault field " + prefix + field);
          }
        }
      }
      Runtime.getRuntime().addShutdownHook(new Thread(Probe::close, "solrforce-probe-close"));
    } catch (IOException failure) {
      throw new IllegalStateException("SOLR force-leader trace init failed", failure);
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

  private static String quote(String s) {
    if (s == null) return "null";
    StringBuilder b = new StringBuilder(s.length() + 2).append('"');
    for (char c : s.toCharArray()) {
      if (c == '"' || c == '\\') b.append('\\').append(c);
      else if (c == '\n') b.append("\\n");
      else if (c == '\r') b.append("\\r");
      else if (c == '\t') b.append("\\t");
      else if (c < 0x20) b.append(String.format("\\u%04x", (int) c));
      else b.append(c);
    }
    return b.append('"').toString();
  }

  private static synchronized void emit(String event, String marker, String site,
                                         String source, String physicalNode, String resource,
                                         int ordinal, boolean applied, String detail) {
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
    catch (IOException failure) {
      throw new IllegalStateException("SOLR force-leader trace write failed", failure);
    }
  }

  private static String source(SolrQueryRequest request) {
    String collection = request.getParams().get("collection");
    String shard = request.getParams().get("shard");
    if (collection == null || shard == null) return "UNRESOLVED:FORCE_LEADER";
    return "SOLR/FORCE_LEADER/" + collection + "/" + shard;
  }

  public static void targetEnter(SolrQueryRequest request) {
    TARGET_SOURCE.set(source(request));
    emit("TARGET_ENTER", "SOLR31:METHOD", "CollectionsHandler.java:1458",
        source(request), "", "", 0, false, "");
  }

  public static void leader(Replica leader, SolrQueryRequest request) {
    emit("LEADER_OBSERVED", "SOLR31:LEADER", "CollectionsHandler.java:1475",
        source(request), leader == null ? "" : leader.getNodeName(), "", 0, false,
        leader == null ? "leader=null" : "leader=" + leader.getName()
            + ";state=" + leader.getState());
  }

  public static void guard(SolrQueryRequest request) {
    emit("TARGET_CHECK", "SOLR31:ACTIVE_LEADER_GUARD", "CollectionsHandler.java:1476",
        source(request), "", "", 0, false, "");
  }

  public static void targetThrow(Throwable failure, SolrQueryRequest request) {
    if (!(failure instanceof SolrException)) return;
    emit("TARGET_THROW", "SOLR31:ACTIVE_LEADER_THROW", "CollectionsHandler.java:1477",
        source(request), "", "", 0, false, failure.toString());
  }

  private static String pathSource(String path) {
    if (path.startsWith("/collections/")) {
      String suffix = path.substring("/collections/".length());
      return "SOLR/COLLECTION/" + suffix.split("/", 2)[0];
    }
    if (path.startsWith("/live_nodes/")) return "UNRESOLVED:LIVE_NODE_ROLE";
    return "UNRESOLVED:ZK:" + path;
  }

  /** Throw within the callable passed to Solr's ZkCmdExecutor.retryOperation. */
  public static void nativeEntry(String path, String api) throws KeeperException {
    if (path == null) return;
    StackTraceElement[] stack = Thread.currentThread().getStackTrace();
    boolean inTarget = false;
    StackTraceElement caller = null;
    for (StackTraceElement frame : stack) {
      if (frame.getClassName().equals("org.apache.solr.handler.admin.CollectionsHandler")
          && frame.getMethodName().equals("forceLeaderElection")) inTarget = true;
      if (caller == null && frame.getClassName().startsWith("org.apache.solr.")
          && !frame.getClassName().equals("org.apache.solr.common.cloud.SolrZkClient")
          && !frame.getClassName().equals("org.apache.solr.common.cloud.ZkCmdExecutor")) {
        caller = frame;
      }
    }
    String source = inTarget && TARGET_SOURCE.get() != null
        ? TARGET_SOURCE.get() : pathSource(path);
    String resource = path.startsWith("/live_nodes/") ? "/live_nodes/ROLE_UNRESOLVED" : path;
    String site = caller == null ? "UNRESOLVED:CALLER" : caller.getClassName()
        + "." + caller.getMethodName() + "#L" + caller.getLineNumber()
        + "->SolrZkClient." + api;
    int end = api.indexOf('$', "lambda$".length());
    if (!api.startsWith("lambda$") || end < 0)
      throw new IllegalArgumentException("unexpected retry method " + api);
    String marker = "FAULT:ZK_NATIVE:" + api.substring("lambda$".length(), end);
    String key = marker + '\u0000' + site + '\u0000' + source + '\u0000' + resource;
    int ordinal = ORDINALS.computeIfAbsent(key, unused -> new AtomicInteger())
        .incrementAndGet();
    int step = NEXT_STEP.get();
    String prefix = "step." + step + ".";
    boolean matched = step <= plannedSteps
        && site.equals(FAULT.getProperty(prefix + "siteId"))
        && source.equals(FAULT.getProperty(prefix + "sourceKey"))
        && resource.equals(FAULT.getProperty(prefix + "resource"))
        && ordinal == Integer.parseInt(FAULT.getProperty(prefix + "hitOrdinal"));
    if (matched && (source.startsWith("UNRESOLVED:")
        || site.startsWith("UNRESOLVED:")
        || resource.contains("UNRESOLVED")))
      throw new IllegalStateException("refuse fault on unresolved ZK identity");
    if (matched) matched = NEXT_STEP.compareAndSet(step, step + 1);
    String physical = path.startsWith("/live_nodes/")
        ? path.substring("/live_nodes/".length()) : MDC.get("node_name");
    if (physical == null) physical = "";
    emit("IO_OBSERVED", marker, site, source, physical, resource,
        ordinal, matched, "path=" + path + ";mdcCore=" + MDC.get("core")
            + ";mdcReplica=" + MDC.get("replica"));
    if (matched) throw KeeperException.create(KeeperException.Code.CONNECTIONLOSS, path);
  }
}
