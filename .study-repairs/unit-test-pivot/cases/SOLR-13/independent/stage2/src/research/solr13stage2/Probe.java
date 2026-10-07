package research.solr13stage2;

import java.io.BufferedWriter;
import java.io.IOException;
import java.io.InputStream;
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
import org.apache.zookeeper.KeeperException;
import org.slf4j.MDC;

/** Graph-free exact I/O and routed-alias target feedback. */
public final class Probe {
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final ConcurrentHashMap<String, AtomicInteger> ORDINALS =
      new ConcurrentHashMap<>();
  private static final AtomicInteger NEXT_STEP = new AtomicInteger(1);
  private static final ThreadLocal<String> TARGET_SOURCE = new ThreadLocal<>();
  private static final ThreadLocal<String> TARGET_PHYSICAL = new ThreadLocal<>();
  private static final ThreadLocal<String> OVERSEER_SOURCE = new ThreadLocal<>();
  private static final Properties FAULT = new Properties();
  private static BufferedWriter output;
  private static int plannedSteps;

  private Probe() {}

  public static synchronized void initialize() {
    if (output != null) return;
    String trace = System.getProperty("solr13stage2.trace.file");
    if (trace == null || trace.isEmpty())
      throw new IllegalArgumentException("solr13stage2.trace.file required");
    try {
      Path path = Paths.get(trace);
      Files.createDirectories(path.toAbsolutePath().getParent());
      output = Files.newBufferedWriter(path, StandardCharsets.UTF_8,
          StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
      String plan = System.getProperty("solr13stage2.fault.plan", "");
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
      Runtime.getRuntime().addShutdownHook(new Thread(Probe::close, "solr13stage2-probe-close"));
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

  private static String targetSource(String alias, String collection) {
    return alias == null || collection == null ? "UNRESOLVED:ROUTED_ALIAS" :
        "SOLR/ROUTED_ALIAS/" + alias + "/" + collection;
  }

  public static void targetEnter(String alias, String collection) {
    String source = targetSource(alias, collection);
    TARGET_SOURCE.set(source);
    TARGET_PHYSICAL.set(MDC.get("node_name"));
    emit("TARGET_ENTER", "SOLR13:ALIAS_VISIBILITY_ENTER",
        "RoutedAlias.doSynchronous", source, TARGET_PHYSICAL.get(),
        collection, 0, false, "alias=" + alias);
  }

  /** Client-side payload before the request crosses the Overseer queue. */
  public static void rpcSend(String alias, String targetCollection) {
    String source = targetSource(alias, targetCollection);
    emit("RPC_SEND", "SOLR13:MAINTAIN_ROUTED_ALIAS_SEND",
        "MaintainRoutedAliasCmd.remoteInvoke", source, MDC.get("node_name"),
        targetCollection, 0, false, "alias=" + alias);
  }

  /** Server-side message payload after the Overseer queue handoff. */
  public static void overseerReceive(String alias, String targetCollection) {
    String source = targetSource(alias, targetCollection);
    emit("OVERSEER_RECEIVE", "SOLR13:MAINTAIN_ROUTED_ALIAS_RECEIVE",
        "MaintainRoutedAliasCmd.call", source, MDC.get("node_name"),
        targetCollection, 0, false, "alias=" + alias);
  }

  /** The exact alias/created collection being written through aliases.json. */
  public static void aliasWriteContext(String alias, String createdCollection) {
    String source = targetSource(alias, createdCollection);
    OVERSEER_SOURCE.set(source);
    emit("ALIAS_WRITE_CONTEXT", "SOLR13:ADD_COLLECTION_TO_ALIAS",
        "MaintainRoutedAliasCmd.addCollectionToAlias", source,
        MDC.get("node_name"), createdCollection, 0, false, "alias=" + alias);
  }

  public static void targetGuard(boolean contains, String alias, String collection) {
    emit("TARGET_CHECK", "SOLR13:CREATED_COLLECTION_VISIBLE_GUARD",
        "RoutedAlias.java:348-350", targetSource(alias, collection),
        TARGET_PHYSICAL.get(), collection, 0, false,
        "alias=" + alias + ";contains=" + contains);
  }

  public static void targetThrow(Throwable failure, String alias, String collection) {
    if (!(failure instanceof SolrException)) return;
    String message = failure.getMessage();
    if (message == null || !message.equals("After we attempted to create "
        + collection + " it did not exist")) return;
    emit("TARGET_THROW", "SOLR13:CREATED_COLLECTION_MISSING_THROW",
        "RoutedAlias.java:350", targetSource(alias, collection),
        TARGET_PHYSICAL.get(), collection, 0, false,
        failure.getClass().getName() + ": " + message);
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
    boolean inAliasWrite = false;
    for (StackTraceElement frame : stack) {
      if (frame.getClassName().equals("org.apache.solr.cloud.api.collections.RoutedAlias")
          && frame.getMethodName().equals("doSynchronous")) inDefensiveCheck = true;
      if (frame.getClassName().equals(
          "org.apache.solr.cloud.api.collections.MaintainRoutedAliasCmd")
          && frame.getMethodName().equals("addCollectionToAlias")) inAliasWrite = true;
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
        inAliasWrite && OVERSEER_SOURCE.get() != null &&
            "/aliases.json".equals(path) ? OVERSEER_SOURCE.get() :
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
