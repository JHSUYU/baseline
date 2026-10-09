package research.solrsplit;

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
import org.apache.solr.common.cloud.SolrZkClient;
import org.apache.solr.common.cloud.ZkNodeProps;
import org.apache.zookeeper.KeeperException;
import org.apache.zookeeper.Watcher;
import org.apache.zookeeper.data.Stat;

/** Records exact split guards and live-node reads; fault plans preserve logical identity. */
public final class Probe {
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final ConcurrentHashMap<String, AtomicInteger> ORDINALS = new ConcurrentHashMap<>();
  private static final ThreadLocal<ZkNodeProps> SPLIT_CONTEXT = new ThreadLocal<>();
  private static final AtomicInteger NEXT_STEP = new AtomicInteger(1);
  private static final Properties FAULT = new Properties();
  private static BufferedWriter output;
  private static int plannedSteps;

  private Probe() {}

  public static synchronized void initialize() {
    if (output != null) return;
    String trace = System.getProperty("solrsplit.trace.file");
    if (trace == null || trace.isEmpty())
      throw new IllegalArgumentException("solrsplit.trace.file required");
    try {
      Path path = Paths.get(trace);
      Files.createDirectories(path.toAbsolutePath().getParent());
      output = Files.newBufferedWriter(path, StandardCharsets.UTF_8,
          StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
      String plan = System.getProperty("solrsplit.fault.plan", "");
      if (!plan.isEmpty()) {
        try (java.io.InputStream input = Files.newInputStream(Paths.get(plan))) {
          FAULT.load(input);
        }
        plannedSteps = Integer.parseInt(FAULT.getProperty("count", "1"));
        if (plannedSteps < 1 || plannedSteps > 10)
          throw new IllegalArgumentException("fault plan count must be 1..10");
        for (int step = 1; step <= plannedSteps; step++) {
          String p = "step." + step + ".";
          for (String field : new String[]{"siteId", "sourceKey", "resource", "hitOrdinal"}) {
            if (FAULT.getProperty(p + field) == null)
              throw new IllegalArgumentException("missing fault field " + p + field);
          }
        }
      }
      Runtime.getRuntime().addShutdownHook(new Thread(Probe::close, "solrsplit-probe-close"));
    } catch (IOException failure) {
      throw new IllegalStateException("SOLR split trace init failed", failure);
    }
  }

  public static synchronized void close() {
    if (output == null) return;
    emit("SUMMARY", "", "", "", "", "", 0, false, false,
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
                                         int ordinal,
                                         boolean matched, boolean applied, String detail) {
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
        + ",\"matched\":" + matched
        + ",\"applied\":" + applied
        + ",\"detail\":" + quote(detail) + "}";
    try { output.write(row); output.newLine(); }
    catch (IOException failure) { throw new IllegalStateException("SOLR split trace write failed", failure); }
  }

  private static String source(ZkNodeProps message) {
    String collection = message.getStr("collection");
    String shard = message.getStr("shard");
    if (collection == null || shard == null) return "UNRESOLVED:SPLIT:" + collection + "/" + shard;
    return "SOLR/SPLIT/" + collection + "/" + shard + "/PARENT_LEADER";
  }

  public static void splitEnter(ZkNodeProps message) {
    SPLIT_CONTEXT.set(message);
  }

  public static void guard(int line, ZkNodeProps message) {
    String marker = line == 165 ? "TARGET:SOLR14:CHECK"
        : line == 524 ? "TARGET:SOLR15_16:OUTER"
        : line == 536 ? "TARGET:SOLR15:FINAL" : "TARGET:SOLR16:FINAL";
    emit("TARGET_CHECK", marker, "SplitShardCmd.java:" + line,
        source(message), "", "/live_nodes/PARENT_LEADER", 0, false, false, "");
  }

  public static void targetThrow(Throwable failure, ZkNodeProps message, int line) {
    if (!(failure instanceof org.apache.solr.common.SolrException)) return;
    String marker = line == 167 ? "TARGET:SOLR14:THROW"
        : line == 538 ? "TARGET:SOLR15:THROW" : "TARGET:SOLR16:THROW";
    emit("TARGET_THROW", marker, "SplitShardCmd.java:" + line,
        source(message), "", "/live_nodes/PARENT_LEADER", 0, false, false,
        failure.toString());
  }

  public static Stat exists(SolrZkClient client, String path, Watcher watcher,
                            boolean retry, ZkNodeProps message, String site)
      throws KeeperException, InterruptedException {
    String source = source(message);
    String physical = path.startsWith("/live_nodes/") ? path.substring("/live_nodes/".length()) : path;
    String key = site + '\u0000' + source + "\u0000/live_nodes/PARENT_LEADER";
    int ordinal = ORDINALS.computeIfAbsent(key, k -> new AtomicInteger()).incrementAndGet();
    int step = NEXT_STEP.get();
    String p = "step." + step + ".";
    boolean matched = step <= plannedSteps
        && site.equals(FAULT.getProperty(p + "siteId"))
        && source.equals(FAULT.getProperty(p + "sourceKey"))
        && "/live_nodes/PARENT_LEADER".equals(FAULT.getProperty(p + "resource"))
        && ordinal == Integer.parseInt(FAULT.getProperty(p + "hitOrdinal"));
    if (matched && source.startsWith("UNRESOLVED:"))
      throw new IllegalStateException("refuse fault on unresolved split source identity");
    if (matched) matched = NEXT_STEP.compareAndSet(step, step + 1);
    emit("IO_OBSERVED", "FAULT:ZK:EXISTS", site, source, physical,
        "/live_nodes/PARENT_LEADER", ordinal, matched, matched, "path=" + path);
    if (matched) throw KeeperException.create(KeeperException.Code.CONNECTIONLOSS, path);
    Stat result = client.exists(path, watcher, retry);
    emit("IO_RESULT", "FAULT:ZK:EXISTS", site, source, physical,
        "/live_nodes/PARENT_LEADER", ordinal, false, false,
        result == null ? "stat=null" : "owner=" + result.getEphemeralOwner());
    return result;
  }

  private static String stableResource(String path) {
    if (path.startsWith("/live_nodes/")) return "/live_nodes/NODE";
    if (path.startsWith("/overseer/") || path.contains("/queue")) return "UNRESOLVED:ZK_QUEUE";
    return path;
  }

  private static String pathSource(String path) {
    if (path.startsWith("/collections/")) {
      String suffix = path.substring("/collections/".length());
      return "SOLR/COLLECTION/" + suffix.split("/", 2)[0];
    }
    if (path.startsWith("/live_nodes")) return "SOLR/LIVE_NODES";
    if (path.startsWith("/configs/")) {
      String suffix = path.substring("/configs/".length());
      return "SOLR/CONFIG/" + suffix.split("/", 2)[0];
    }
    return "UNRESOLVED:ZK:" + path;
  }

  /** Broader healthy-run ZK I/O feedback at original SolrZkClient method entries. */
  public static void zkEntry(String path, String api) throws KeeperException {
    if (path == null) return;
    StackTraceElement[] stack = Thread.currentThread().getStackTrace();
    boolean inSplit = false;
    StackTraceElement caller = null;
    for (StackTraceElement frame : stack) {
      if (frame.getClassName().equals("org.apache.solr.cloud.api.collections.SplitShardCmd")
          && frame.getMethodName().equals("split")) inSplit = true;
      if (caller == null && frame.getClassName().startsWith("org.apache.solr.")
          && !frame.getClassName().equals("org.apache.solr.common.cloud.SolrZkClient")) {
        caller = frame;
      }
    }
    String source = inSplit && SPLIT_CONTEXT.get() != null
        ? source(SPLIT_CONTEXT.get()) : pathSource(path);
    String resource = stableResource(path);
    if (resource.startsWith("UNRESOLVED:")) source = "UNRESOLVED:ZK_QUEUE";
    String site = caller == null ? "UNRESOLVED:CALLER" : caller.getClassName()
        + "." + caller.getMethodName() + "#L" + caller.getLineNumber()
        + "->SolrZkClient." + api;
    String marker = "FAULT:ZK:" + api.substring(0, api.indexOf('('));
    String key = marker + '\u0000' + site + '\u0000' + source + '\u0000' + resource;
    int ordinal = ORDINALS.computeIfAbsent(key, k -> new AtomicInteger()).incrementAndGet();
    int step = NEXT_STEP.get();
    String p = "step." + step + ".";
    boolean matched = step <= plannedSteps
        && site.equals(FAULT.getProperty(p + "siteId"))
        && source.equals(FAULT.getProperty(p + "sourceKey"))
        && resource.equals(FAULT.getProperty(p + "resource"))
        && ordinal == Integer.parseInt(FAULT.getProperty(p + "hitOrdinal"));
    if (matched && (source.startsWith("UNRESOLVED:")
        || site.startsWith("UNRESOLVED:")))
      throw new IllegalStateException("refuse fault on unresolved ZK identity");
    if (matched) matched = NEXT_STEP.compareAndSet(step, step + 1);
    String physical = path.startsWith("/live_nodes/")
        ? path.substring("/live_nodes/".length()) : "";
    emit("IO_OBSERVED", marker, site, source, physical, resource,
        ordinal, matched, matched, "path=" + path);
    if (matched) throw KeeperException.create(KeeperException.Code.CONNECTIONLOSS, path);
  }
}
