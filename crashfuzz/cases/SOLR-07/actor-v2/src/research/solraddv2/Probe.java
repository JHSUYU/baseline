package research.solraddv2;

import java.io.BufferedWriter;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.Collections;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.Properties;
import org.apache.solr.cloud.ZkController;
import org.apache.solr.common.SolrException;
import org.apache.solr.common.cloud.Replica;
import org.apache.solr.common.util.Utils;
import org.apache.solr.core.CoreDescriptor;
import org.apache.solr.core.SolrCore;
import org.apache.zookeeper.KeeperException;

/** Exact SolrZkClient actor, affected replica, and leader provenance. */
public final class Probe {
  private static final Map<Object, Binding> CLIENTS =
      Collections.synchronizedMap(new IdentityHashMap<Object, Binding>());
  private static final Map<Object, Binding> CONTROLLERS =
      Collections.synchronizedMap(new IdentityHashMap<Object, Binding>());
  private static final Map<String, Binding> NODES = new HashMap<>();
  private static final Map<String, Integer> ORDINALS = new HashMap<>();
  private static final ThreadLocal<Guard> LAST_GUARD = new ThreadLocal<>();
  private static final Properties PLAN = new Properties();
  private static final String COLLECTION = "testAddMultipleReplicas";
  private static BufferedWriter output;
  private static long sequence;
  private static int steps;
  private static int nextStep = 1;

  private static final class Binding {
    final String actor;
    final String node;
    final String home;
    Binding(String actor, String node, String home) {
      this.actor = actor; this.node = node; this.home = home;
    }
  }
  private static final class Guard {
    final String target;
    final String actor;
    final String leader;
    final boolean coreMissing;
    final boolean eligible;
    Guard(String target, String actor, String leader, boolean coreMissing,
          boolean eligible) {
      this.target = target; this.actor = actor; this.leader = leader;
      this.coreMissing = coreMissing; this.eligible = eligible;
    }
  }

  private Probe() {}

  public static synchronized void initialize() {
    if (output != null) return;
    String trace = System.getProperty("solr07v2.trace", "");
    if (trace.isEmpty()) throw new IllegalArgumentException("solr07v2.trace required");
    try {
      Path path = Paths.get(trace);
      Files.createDirectories(path.toAbsolutePath().getParent());
      output = Files.newBufferedWriter(path, StandardCharsets.UTF_8,
          StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
      String plan = System.getProperty("solr07v2.plan", "");
      if (!plan.isEmpty()) {
        try (InputStream input = Files.newInputStream(Paths.get(plan))) { PLAN.load(input); }
        steps = Integer.parseInt(PLAN.getProperty("count", "0"));
        if (steps < 1 || steps > 10) throw new IllegalArgumentException("fault count must be 1..10");
        if (!PLAN.getProperty("targetActor", "").matches("JETTY/node[1-3]"))
          throw new IllegalArgumentException("physical target actor required");
        for (int step = 1; step <= steps; step++)
          for (String key : new String[]{"actorKey", "sourceKey", "operation", "siteId",
              "resource", "hitOrdinal", "kind"})
            if (PLAN.getProperty("step." + step + "." + key) == null)
              throw new IllegalArgumentException("missing step " + step + " " + key);
      }
      Runtime.getRuntime().addShutdownHook(new Thread(Probe::close, "solr07v2-close"));
    } catch (IOException failure) { throw new IllegalStateException(failure); }
  }

  public static synchronized void close() {
    if (output == null) return;
    emit("SUMMARY", "", "", "", "", "", 0, false, "", "",
        "applied=" + (nextStep - 1) + "/" + steps);
    try { output.flush(); output.close(); }
    catch (IOException failure) { failure.printStackTrace(System.err); }
    output = null;
  }

  private static String quote(String value) {
    if (value == null) return "null";
    StringBuilder out = new StringBuilder("\"");
    for (char c : value.toCharArray()) {
      if (c == '"' || c == '\\') out.append('\\').append(c);
      else if (c == '\n') out.append("\\n");
      else if (c == '\r') out.append("\\r");
      else if (c == '\t') out.append("\\t");
      else if (c < 0x20) out.append(String.format("\\u%04x", (int)c));
      else out.append(c);
    }
    return out.append('"').toString();
  }

  private static synchronized void emit(String event, String actor, String source,
                                        String operation, String site, String resource,
                                        int ordinal, boolean applied, String target,
                                        String leader, String detail) {
    if (output == null) return;
    String row = "{\"event\":" + quote(event) + ",\"seq\":" + (++sequence)
        + ",\"threadId\":" + Thread.currentThread().getId()
        + ",\"actorKey\":" + quote(actor)
        + ",\"sourceKey\":" + quote(source)
        + ",\"operation\":" + quote(operation)
        + ",\"siteId\":" + quote(site)
        + ",\"resource\":" + quote(resource)
        + ",\"hitOrdinal\":" + ordinal
        + ",\"applied\":" + applied
        + ",\"targetKey\":" + quote(target)
        + ",\"leaderKey\":" + quote(leader)
        + ",\"detail\":" + quote(detail) + "}";
    try { output.write(row); output.newLine(); output.flush(); }
    catch (IOException failure) { throw new IllegalStateException("trace write failed", failure); }
  }

  private static String slot(String home) {
    if (home == null) return "UNBOUND:SOLR_HOME";
    String normalized = home.replace('\\', '/');
    while (normalized.endsWith("/")) normalized = normalized.substring(0, normalized.length() - 1);
    String end = normalized.substring(normalized.lastIndexOf('/') + 1);
    return end.matches("node[1-3]") ? "JETTY/" + end : "UNBOUND:SOLR_HOME:" + end;
  }

  public static synchronized void bind(Object controller, Object client,
                                        String nodeName, String home) {
    if (controller == null || client == null || nodeName == null || home == null)
      throw new IllegalStateException("incomplete ZkController/SolrZkClient binding");
    Binding binding = new Binding(slot(home), nodeName, home);
    Binding priorClient = CLIENTS.get(client);
    Binding priorController = CONTROLLERS.get(controller);
    Binding priorNode = NODES.get(nodeName);
    if ((priorClient != null && (!priorClient.node.equals(nodeName) ||
                                 !priorClient.home.equals(home))) ||
        (priorController != null && (!priorController.node.equals(nodeName) ||
                                     !priorController.home.equals(home))) ||
        (priorNode != null && (!priorNode.actor.equals(binding.actor) ||
                               !priorNode.home.equals(home))))
      throw new IllegalStateException("ambiguous ZK actor binding");
    for (Binding existing : NODES.values())
      if (existing.actor.equals(binding.actor) && !existing.node.equals(nodeName))
        throw new IllegalStateException("two physical nodes claimed one Jetty role");
    CLIENTS.put(client, binding);
    CONTROLLERS.put(controller, binding);
    NODES.put(nodeName, binding);
    emit("CLIENT_BIND", binding.actor, "", "", "ZkController.<init>", "",
        0, false, "", "", "clientIdentity=" + System.identityHashCode(client)
            + ";controllerIdentity=" + System.identityHashCode(controller)
            + ";nodeName=" + nodeName + ";solrHome=" + home);
  }

  private static String operation(String api) {
    if (api.startsWith("exists(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;"))
      return "EXISTS_WATCH";
    if (api.startsWith("exists(")) return "EXISTS";
    if (api.startsWith("getChildren(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;"
        + "Lorg/apache/zookeeper/data/Stat;")) return "GET_CHILDREN_STAT";
    if (api.startsWith("getChildren(")) return "GET_CHILDREN";
    if (api.startsWith("getData(")) return "GET_DATA";
    if (api.startsWith("setData(")) return "SET_DATA";
    return "UNBOUND:OPERATION";
  }

  private static String caller() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      String owner = frame.getClassName();
      if (owner.startsWith("org.apache.solr.") &&
          !owner.equals("org.apache.solr.common.cloud.SolrZkClient"))
        return owner + "#" + frame.getMethodName() + ":" + frame.getLineNumber();
    }
    return "UNBOUND:CALLER";
  }

  private static String source(String path) {
    String root = "/collections/" + COLLECTION;
    String prefix = "/collections/" + COLLECTION + "/";
    return path != null && (path.equals(root) || path.startsWith(prefix)) ?
        "SOLR/COLLECTION/" + COLLECTION : "UNBOUND:COLLECTION";
  }

  private static boolean matches(String actor, String source, String op,
                                 String site, String path, int ordinal) {
    if (!actor.startsWith("JETTY/") || !source.startsWith("SOLR/COLLECTION/")
        || site.startsWith("UNBOUND:")) return false;
    if (!actor.equals(PLAN.getProperty("targetActor"))) return false;
    if (nextStep > steps) return false;
    String prefix = "step." + nextStep + ".";
    return actor.equals(PLAN.getProperty(prefix + "actorKey"))
        && source.equals(PLAN.getProperty(prefix + "sourceKey"))
        && op.equals(PLAN.getProperty(prefix + "operation"))
        && site.equals(PLAN.getProperty(prefix + "siteId"))
        && path.equals(PLAN.getProperty(prefix + "resource"))
        && Integer.toString(ordinal).equals(PLAN.getProperty(prefix + "hitOrdinal"))
        && "CONNECTION_LOSS".equals(PLAN.getProperty(prefix + "kind"));
  }

  static boolean smokeMatch(String actor, String path) {
    String source = "SOLR/COLLECTION/" + COLLECTION;
    String site = "org.apache.solr.cloud.ZkController#getLeader:1";
    PLAN.setProperty("step.1.actorKey", "JETTY/node2");
    PLAN.setProperty("targetActor", "JETTY/node2");
    PLAN.setProperty("step.1.sourceKey", source);
    PLAN.setProperty("step.1.operation", "GET_DATA");
    PLAN.setProperty("step.1.siteId", site);
    PLAN.setProperty("step.1.resource", "/collections/" + COLLECTION + "/leaders/shard1/leader");
    PLAN.setProperty("step.1.hitOrdinal", "1");
    PLAN.setProperty("step.1.kind", "CONNECTION_LOSS");
    steps = 1; nextStep = 1;
    return matches(actor, source, "GET_DATA", site, path, 1);
  }

  static boolean smokeSameClient(Object controller, Object client) {
    Binding binding = CONTROLLERS.get(controller);
    return binding != null && CLIENTS.get(client) == binding;
  }

  public static synchronized void io(Object client, String path, String api)
      throws KeeperException.ConnectionLossException {
    Binding binding = CLIENTS.get(client);
    String actor = binding == null ? "UNBOUND:SOLRZKCLIENT" : binding.actor;
    String src = source(path);
    String op = operation(api);
    String site = caller();
    String key = actor + "|" + src + "|" + op + "|" + site + "|" + path;
    int ordinal = ORDINALS.containsKey(key) ? ORDINALS.get(key) + 1 : 1;
    ORDINALS.put(key, ordinal);
    String raw = "clientIdentity=" + System.identityHashCode(client)
        + ";nodeName=" + (binding == null ? "" : binding.node)
        + ";solrHome=" + (binding == null ? "" : binding.home)
        + ";api=" + api;
    emit("IO_OBSERVED", actor, src, op, site, path, ordinal, false,
        "", "", raw);
    if (!matches(actor, src, op, site, path, ordinal)) return;
    int step = nextStep++;
    emit("IO_APPLIED", actor, src, op, site, path, ordinal, true,
        "", "", raw + ";planStep=" + step + ";kind=CONNECTION_LOSS");
    throw new KeeperException.ConnectionLossException();
  }

  private static String base(Binding binding) {
    if (binding == null) return "";
    return Utils.getBaseUrlForNodeName(binding.node, "http");
  }

  private static String leader(String leaderUrl) {
    if (leaderUrl == null) return "UNBOUND:LEADER_URL";
    String found = null;
    for (Binding binding : NODES.values()) {
      if (!binding.actor.startsWith("JETTY/")) continue;
      String prefix = base(binding) + "/";
      if (!leaderUrl.startsWith(prefix)) continue;
      String core = leaderUrl.substring(prefix.length());
      if (core.endsWith("/")) core = core.substring(0, core.length() - 1);
      if (core.isEmpty() || core.contains("/")) return "UNBOUND:LEADER_CORE";
      String candidate = binding.actor + "/" + core;
      if (found != null && !found.equals(candidate)) return "UNBOUND:AMBIGUOUS_LEADER";
      found = candidate;
    }
    return found == null ? "UNBOUND:LEADER_URL" : found;
  }

  public static synchronized void guard(ZkController controller, CoreDescriptor descriptor,
                                         Replica replica, SolrCore liveCore, String leaderUrl,
                                         String ourUrl, boolean isLeader) {
    Binding binding = CONTROLLERS.get(controller);
    String actor = binding == null ? "UNBOUND:ZKCONTROLLER" : binding.actor;
    String collection = descriptor.getCollectionName();
    String shard = descriptor.getCloudDescriptor().getShardId();
    String core = descriptor.getName();
    String coreNode = descriptor.getCloudDescriptor().getCoreNodeName();
    String replicaName = replica == null ? "" : replica.getName();
    String type = replica == null ? "null" : replica.getType().name();
    String leader = leader(leaderUrl);
    String target = "SOLR/CORE/" + collection + "/" + shard + "/" + replicaName + "/" + core;
    Binding clientBinding = CLIENTS.get(controller.getZkClient());
    boolean sameClient = binding != null && clientBinding == binding;
    boolean ourNode = binding != null && ourUrl != null &&
        ourUrl.equals(base(binding) + "/" + core + "/");
    boolean eligible = COLLECTION.equals(collection) && replica != null
        && replicaName.equals(coreNode) && !replicaName.isEmpty()
        && actor.startsWith("JETTY/") && sameClient && ourNode
        && leader.startsWith("JETTY/");
    LAST_GUARD.set(new Guard(target, actor, leader, liveCore == null, eligible));
    String detail = "eligible=" + eligible + ";isLeader=" + isLeader
        + ";corePresent=" + (liveCore != null)
        + ";replicaType=" + type + ";replicaName=" + replicaName
        + ";coreNode=" + coreNode
        + ";coreName=" + core + ";ourUrl=" + ourUrl + ";leaderUrl=" + leaderUrl
        + ";controllerIdentity=" + System.identityHashCode(controller)
        + ";clientIdentity=" + (controller.getZkClient() == null ? "" :
            System.identityHashCode(controller.getZkClient()))
        + ";nodeName=" + (binding == null ? "" : binding.node)
        + ";solrHome=" + (binding == null ? "" : binding.home);
    emit("TARGET_CHECK", actor, "SOLR/COLLECTION/" + collection,
        "CORE_AVAILABILITY", "ZkController.register:1325", core, 0, false,
        target, leader, detail);
  }

  public static synchronized void targetThrow(Throwable failure, ZkController controller,
                                               CoreDescriptor descriptor) {
    if (!(failure instanceof SolrException) || ((SolrException) failure).code() != 503 ||
        !"SolrCore is no longer available to register".equals(failure.getMessage())) return;
    Guard guard = LAST_GUARD.get();
    Binding binding = CONTROLLERS.get(controller);
    String actor = binding == null ? "UNBOUND:ZKCONTROLLER" : binding.actor;
    String target = "SOLR/CORE/" + descriptor.getCollectionName() + "/"
        + descriptor.getCloudDescriptor().getShardId() + "/"
        + descriptor.getCloudDescriptor().getCoreNodeName() + "/" + descriptor.getName();
    if (guard == null || !guard.coreMissing || !guard.eligible ||
        !target.equals(guard.target) || !actor.equals(guard.actor)) return;
    emit("TARGET_THROW", actor, "SOLR/COLLECTION/" + descriptor.getCollectionName(),
        "CORE_AVAILABILITY", "ZkController.register:1326", descriptor.getName(), 0,
        false, target, guard.leader,
        "failure=" + failure + ";controllerIdentity=" + System.identityHashCode(controller));
  }
}
