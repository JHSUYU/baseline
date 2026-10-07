package research.solrforcev2;

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
import org.apache.solr.common.cloud.SolrZkClient;
import org.apache.solr.cloud.ZkController;
import org.apache.solr.handler.admin.CollectionsHandler;
import org.apache.solr.request.SolrQueryRequest;
import org.apache.zookeeper.KeeperException;
import org.slf4j.MDC;

/** Exact target events, physical node evidence, and retry-internal ZK fault points. */
public final class Probe {
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final ConcurrentHashMap<String, AtomicInteger> ORDINALS =
      new ConcurrentHashMap<>();
  private static final ThreadLocal<String> TARGET_SOURCE = new ThreadLocal<>();
  private static final ThreadLocal<Binding> TARGET_BINDING = new ThreadLocal<>();
  private static final AtomicInteger NEXT_STEP = new AtomicInteger(1);
  private static final Properties FAULT = new Properties();
  private static BufferedWriter output;
  private static int plannedSteps;

  private static final class Binding {
    final Object client;
    final String node;
    final String source;
    final String collection;
    final String shard;
    Binding(Object client, String node, String source, String collection, String shard) {
      this.client = client;
      this.node = node;
      this.source = source;
      this.collection = collection;
      this.shard = shard;
    }
  }

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
          for (String field : new String[]{"siteId", "sourceKey", "resource", "actorRole", "hitOrdinal"}) {
            if (FAULT.getProperty(prefix + field) == null)
              throw new IllegalArgumentException("missing fault field " + prefix + field);
          }
          if (!"forceleader-request-jetty".equals(FAULT.getProperty(prefix + "actorRole")))
            throw new IllegalArgumentException("fault actor must be the bound force-leader Jetty");
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
    emit(event, marker, site, source, physicalNode, resource, ordinal, applied,
        detail, "", -1);
  }

  private static synchronized void emit(String event, String marker, String site,
                                         String source, String physicalNode, String resource,
                                         int ordinal, boolean applied, String detail,
                                         String actorRole, int receiverClientId) {
    if (output == null) return;
    Binding binding = TARGET_BINDING.get();
    String row = "{\"event\":" + quote(event)
        + ",\"seq\":" + SEQUENCE.incrementAndGet()
        + ",\"timeNs\":" + System.nanoTime()
        + ",\"threadId\":" + Thread.currentThread().getId()
        + ",\"marker\":" + quote(marker)
        + ",\"siteId\":" + quote(site)
        + ",\"sourceKey\":" + quote(source)
        + ",\"physicalNode\":" + quote(physicalNode)
        + ",\"targetNode\":" + quote(binding == null ? "" : binding.node)
        + ",\"targetClientId\":" + (binding == null ? -1 : System.identityHashCode(binding.client))
        + ",\"receiverClientId\":" + receiverClientId
        + ",\"actorRole\":" + quote(actorRole)
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

  public static void targetEnter(SolrQueryRequest request, CollectionsHandler handler) {
    ZkController controller = handler.getCoreContainer().getZkController();
    SolrZkClient client = controller.getZkClient();
    String node = controller.getNodeName();
    String collection = request.getParams().get("collection");
    String shard = request.getParams().get("shard");
    if (client == null || node == null || collection == null || shard == null)
      throw new IllegalStateException("SOLR31 target client/node/collection/shard unresolved");
    String target = source(request);
    TARGET_SOURCE.set(target);
    TARGET_BINDING.set(new Binding(client, node, target, collection, shard));
    emit("TARGET_ENTER", "SOLR31:METHOD", "CollectionsHandler.java:1458",
        target, node, "", 0, false,
        "actorRole=forceleader-request-jetty;clientId=" + System.identityHashCode(client));
  }

  public static void leader(Replica leader, SolrQueryRequest request) {
    emit("LEADER_OBSERVED", "SOLR31:LEADER", "CollectionsHandler.java:1475",
        source(request), targetNode(), "", 0, false,
        leader == null ? "leader=null" : "leader=" + leader.getName()
            + ";state=" + leader.getState() + ";leaderNode=" + leader.getNodeName());
  }

  public static void guard(SolrQueryRequest request) {
    emit("TARGET_CHECK", "SOLR31:ACTIVE_LEADER_GUARD", "CollectionsHandler.java:1476",
        source(request), targetNode(), "", 0, false, "");
  }

  public static void targetThrow(Throwable failure, SolrQueryRequest request) {
    if (!(failure instanceof SolrException)) return;
    emit("TARGET_THROW", "SOLR31:ACTIVE_LEADER_THROW", "CollectionsHandler.java:1477",
        source(request), targetNode(), "", 0, false, failure.toString());
  }

  private static String targetNode() {
    Binding binding = TARGET_BINDING.get();
    return binding == null ? "" : binding.node;
  }

  private static boolean exactRequestPath(Binding binding, String path) {
    if (binding == null) return false;
    String root = "/collections/" + binding.collection;
    return path.equals(root) || path.equals(root + "/state.json")
        || path.equals(root + "/terms")
        || path.equals(root + "/terms/" + binding.shard);
  }

  private static boolean eligible(Binding binding, Object receiver, String path,
                                  boolean inTarget) {
    return inTarget && binding != null && receiver == binding.client
        && exactRequestPath(binding, path);
  }

  static void bindForSmoke(Object client, String node, String collection, String shard) {
    TARGET_BINDING.set(new Binding(client, node,
        "SOLR/FORCE_LEADER/" + collection + "/" + shard, collection, shard));
  }

  static boolean eligibleForSmoke(Object receiver, String path) {
    return eligible(TARGET_BINDING.get(), receiver, path, true);
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
  public static void nativeEntry(SolrZkClient receiver, String path, String api) throws KeeperException {
    nativeEntryBound(receiver, path, api);
  }

  /** Package-visible entry used by the offline smoke with two distinct client objects. */
  static void nativeEntryBound(Object receiver, String path, String api) throws KeeperException {
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
    Binding binding = TARGET_BINDING.get();
    boolean sameClient = inTarget && binding != null && receiver == binding.client;
    String source = inTarget && binding != null ? binding.source : pathSource(path);
    String resource = path.startsWith("/live_nodes/") ? "/live_nodes/ROLE_UNRESOLVED" : path;
    String site = caller == null ? "UNRESOLVED:CALLER" : caller.getClassName()
        + "." + caller.getMethodName() + "#L" + caller.getLineNumber()
        + "->SolrZkClient." + api;
    int end = api.indexOf('$', "lambda$".length());
    if (!api.startsWith("lambda$") || end < 0)
      throw new IllegalArgumentException("unexpected retry method " + api);
    String marker = "FAULT:ZK_NATIVE:" + api.substring("lambda$".length(), end);
    String actorRole = sameClient ? "forceleader-request-jetty" : "other-client";
    boolean exactRequestPath = exactRequestPath(binding, path);
    String key = marker + '\u0000' + site + '\u0000' + source + '\u0000' + resource
        + '\u0000' + actorRole;
    int ordinal = ORDINALS.computeIfAbsent(key, unused -> new AtomicInteger())
        .incrementAndGet();
    int step = NEXT_STEP.get();
    String prefix = "step." + step + ".";
    boolean matched = step <= plannedSteps
        && site.equals(FAULT.getProperty(prefix + "siteId"))
        && source.equals(FAULT.getProperty(prefix + "sourceKey"))
        && resource.equals(FAULT.getProperty(prefix + "resource"))
        && actorRole.equals(FAULT.getProperty(prefix + "actorRole"))
        && ordinal == Integer.parseInt(FAULT.getProperty(prefix + "hitOrdinal"));
    if (matched && (!eligible(binding, receiver, path, inTarget)
        || source.startsWith("UNRESOLVED:")
        || site.startsWith("UNRESOLVED:")
        || resource.contains("UNRESOLVED")))
      throw new IllegalStateException("refuse fault outside bound SOLR31 request actor/path");
    if (matched) matched = NEXT_STEP.compareAndSet(step, step + 1);
    String physical = sameClient ? binding.node : MDC.get("node_name");
    if (physical == null) physical = "";
    emit("IO_OBSERVED", marker, site, source, physical, resource,
        ordinal, matched, "path=" + path + ";actorRole=" + actorRole
            + ";receiverClientId=" + System.identityHashCode(receiver)
            + ";sameTargetClient=" + sameClient + ";exactRequestPath=" + exactRequestPath
            + ";mdcCore=" + MDC.get("core")
            + ";mdcReplica=" + MDC.get("replica"), actorRole,
        System.identityHashCode(receiver));
    if (matched) throw KeeperException.create(KeeperException.Code.CONNECTIONLOSS, path);
  }
}
