package edu.uva.liftlab.mallory.solr;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayDeque;
import java.util.Collections;
import java.util.Deque;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicLong;

/** Runtime bridge at Solr's real HTTP and executor handoffs. */
public final class SolrHooks {
  public static final String HEADER = "X-Mallory-Causal";
  private static final String TRANSPORT = "solr-http";
  private static final String PORT = "request";
  private static final String FORCE_LEADER_COLLECTION = "forceleader_lower_terms_collection";
  public static final String FORCE_LEADER_STATE_DOOR =
      "org.apache.solr.common.cloud.ZkStateReader#fetchCollectionState"
      + "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Ljava/lang/String;)"
      + "Lorg/apache/solr/common/cloud/DocCollection;@1641:door:watcher";
  private static final String PREFIX = UUID.randomUUID().toString();
  private static final AtomicLong SERIAL = new AtomicLong();
  private static final Map<Object, NodeRef> CONTROLLERS = new IdentityHashMap<Object, NodeRef>();
  private static final Map<Object, NodeRef> HTTP_CLIENTS = new IdentityHashMap<Object, NodeRef>();
  private static final Set<Object> AMBIGUOUS_ZK_CLIENTS =
      Collections.newSetFromMap(new IdentityHashMap<Object, Boolean>());
  private static final Map<String, Integer> EPOCHS = new HashMap<String, Integer>();
  private static final ThreadLocal<Deque<Scope>> SCOPES = new ThreadLocal<Deque<Scope>>() {
    @Override protected Deque<Scope> initialValue() { return new ArrayDeque<Scope>(); }
  };
  private static final ThreadLocal<Deque<StateWatch>> STATE_WATCHES =
      new ThreadLocal<Deque<StateWatch>>() {
        @Override protected Deque<StateWatch> initialValue() { return new ArrayDeque<StateWatch>(); }
      };

  private SolrHooks() { }

  public static synchronized void registerController(Object controller) {
    if (controller == null || CONTROLLERS.containsKey(controller)) return;
    String name = callString(controller, "getNodeName");
    if (name == null || name.isEmpty()) return;
    Object container = invoke(controller, "getCoreContainer");
    String logicalName = miniClusterRole(container, name);
    Integer previous = EPOCHS.get(logicalName);
    int epoch = previous == null ? 0 : previous.intValue() + 1;
    EPOCHS.put(logicalName, epoch);
    NodeRef ref = new NodeRef(logicalName, epoch);
    CONTROLLERS.put(controller, ref);
    Probe.registerNode(controller, logicalName, epoch);
    if (container != null) Probe.registerNode(container, logicalName, epoch);
    Object reader = invoke(controller, "getZkStateReader");
    if (reader != null) {
      Probe.registerNode(reader, logicalName, epoch);
      Object aliasesManager = field(reader, "aliasesManager");
      if (aliasesManager != null) Probe.registerNode(aliasesManager, logicalName, epoch);
      registerZkClient(reader, logicalName, epoch);
    }
    System.err.println("MALLORY_SOLR_NODE logical=" + logicalName + " physical=" + name
        + " epoch=" + epoch);
  }

  public static void beginController(Object controller) {
    registerController(controller);
    NodeRef ref;
    synchronized (SolrHooks.class) { ref = CONTROLLERS.get(controller); }
    Probe.NodeScope node = ref == null ? Probe.withNode("unknown", 0)
        : Probe.withNode(ref.name, ref.epoch);
    SCOPES.get().push(new Scope("controller", node, null));
  }

  public static void endController() { end("controller"); }

  /** Overseer collection commands run on the owning CoreContainer's actor. */
  public static void beginOverseer(Object handler) {
    Object overseer = field(handler, "overseer");
    Object container = invoke(overseer, "getCoreContainer");
    Object controller = invoke(container, "getZkController");
    registerController(controller);
    NodeRef ref;
    synchronized (SolrHooks.class) { ref = CONTROLLERS.get(controller); }
    Probe.NodeScope node = ref == null ? Probe.withNode("unknown", 0)
        : Probe.withNode(ref.name, ref.epoch);
    SCOPES.get().push(new Scope("overseer", node, null));
  }

  public static void endOverseer() { end("overseer"); }

  /** Queue reads and executor submissions belong to the overseer's registered server. */
  public static void beginOverseerTaskProcessor(Object processor) {
    Object reader = field(processor, "zkStateReader");
    SCOPES.get().push(new Scope("overseer_task_processor",
        Probe.withRegisteredNode(reader), null));
  }

  public static void endOverseerTaskProcessor() { end("overseer_task_processor"); }

  /** A new reader can share a uniquely owned SolrZkClient with a registered reader. */
  public static void beginAliasesManager(Object manager) {
    Object reader = field(manager, "this$0");
    Object client = invoke(reader, "getZkClient");
    Probe.NodeScope node;
    synchronized (SolrHooks.class) {
      node = client != null && !AMBIGUOUS_ZK_CLIENTS.contains(client)
          ? Probe.withRegisteredNode(client) : Probe.withNode("unknown", 0);
      if (!"unknown".equals(Probe.currentNode())) {
        try {
          Probe.registerCurrentNode(reader);
          Probe.registerCurrentNode(manager);
        } catch (IllegalStateException conflictingOwner) {
          node.close();
          node = Probe.withNode("unknown", 0);
        }
      }
    }
    SCOPES.get().push(new Scope("aliases", node, null));
  }

  public static void endAliasesManager() { end("aliases"); }

  /** Scope the reader-owned ZooKeeper client before its callback is submitted. */
  public static void beginZkWatchDispatch(Object wrapper) {
    Object client = field(wrapper, "this$0");
    Probe.NodeScope node;
    synchronized (SolrHooks.class) {
      node = client != null && AMBIGUOUS_ZK_CLIENTS.contains(client)
          ? Probe.withNode("unknown", 0) : Probe.withRegisteredNode(client);
    }
    SCOPES.get().push(new Scope("zk_watch_dispatch",
        node, null));
  }

  public static void endZkWatchDispatch() { end("zk_watch_dispatch"); }

  /** Diagnostic scope for a real collection-state watch callback. */
  public static void beginStateWatcher(Object watcher) {
    Object reader = field(watcher, "this$0");
    Object collField = field(watcher, "coll");
    String collection = collField instanceof String ? (String) collField : null;
    Probe.NodeScope node = Probe.withRegisteredNode(reader);
    SCOPES.get().push(new Scope("state_watcher", node, null));
    Probe.regionEnter("solr31:ZkStateReader.StateWatcher.refreshAndWatch");
    StateWatch watch = new StateWatch(watcher, reader, collection, Probe.captureContext());
    STATE_WATCHES.get().push(watch);
    stateDiagnostic("before", watch.reader, watch.collection, watch.occurrence);
  }

  public static void endStateWatcher() {
    Deque<StateWatch> watches = STATE_WATCHES.get();
    if (!watches.isEmpty()) {
      StateWatch watch = watches.pop();
      stateDiagnostic("after", watch.reader, watch.collection, watch.occurrence);
    }
    Probe.regionExit("solr31:ZkStateReader.StateWatcher.refreshAndWatch");
    end("state_watcher");
    if (watches.isEmpty()) STATE_WATCHES.remove();
  }

  /** Only the selected real watcher read can receive this diagnostic fault. */
  public static void beforeQualifiedStateRead(String collection, String path, Object watcher) {
    Deque<StateWatch> watches = STATE_WATCHES.get();
    if (watches.isEmpty()) return;
    StateWatch active = watches.peek();
    if (active.watcher != watcher || !FORCE_LEADER_COLLECTION.equals(collection)
        || !collection.equals(active.collection)
        || !("/collections/" + collection + "/state.json").equals(path)
        || "unknown".equals(Probe.currentNode())) return;
    Probe.beforeDoor(FORCE_LEADER_STATE_DOOR,
        "org.apache.zookeeper.KeeperException$ConnectionLossException");
  }

  /** Exposes the exact cached leader operand immediately before the selected guard. */
  public static void forceLeaderOperand(Object leader, Object slice,
      Object docCollection, String collection, Object controller) {
    Object state = invoke(leader, "getState");
    Object name = invoke(leader, "getName");
    Object sliceName = invoke(slice, "getName");
    System.err.println("MALLORY_SOLR31_STATE phase=target ts=" + System.nanoTime()
        + " node=" + Probe.currentNode()
        + " epoch=" + Probe.currentEpoch() + " thread_id=" + Thread.currentThread().getId()
        + " occurrence=" + Probe.captureContext() + " collection=" + collection
        + " reader_id=" + identity(invoke(controller, "getZkStateReader"))
        + " shard=" + sliceName + " version=" + invoke(docCollection, "getZNodeVersion")
        + " leader=" + name + " leader_state=" + state);
  }

  private static void stateDiagnostic(String phase, Object reader, String collection,
      String occurrence) {
    Object state = invoke(reader, "getClusterState");
    Object doc = invokeStringArg(state, "getCollectionOrNull", collection);
    Object slice = invokeStringArg(doc, "getSlice", "shard1");
    Object leader = invoke(slice, "getLeader");
    Object version = invoke(doc, "getZNodeVersion");
    System.err.println("MALLORY_SOLR31_STATE phase=" + phase + " ts=" + System.nanoTime()
        + " node=" + Probe.currentNode()
        + " epoch=" + Probe.currentEpoch() + " thread_id=" + Thread.currentThread().getId()
        + " occurrence=" + occurrence + " collection=" + collection
        + " reader_id=" + identity(reader)
        + " path=/collections/" + collection + "/state.json"
        + " shard=shard1 version=" + version + " leader=" + invoke(leader, "getName")
        + " leader_state=" + invoke(leader, "getState"));
  }

  private static String identity(Object value) {
    return value == null ? "null" : Integer.toHexString(System.identityHashCode(value));
  }

  private static Object invokeStringArg(Object receiver, String method, String argument) {
    if (receiver == null || argument == null) return null;
    try { return receiver.getClass().getMethod(method, String.class).invoke(receiver, argument); }
    catch (ReflectiveOperationException | SecurityException failure) { return null; }
  }

  /** A standalone SolrJ ZooKeeper reader belongs to the test client actor. */
  public static void registerClientReader(Object reader) {
    if (reader == null) return;
    // A server may construct a SolrJ provider over its own ZkStateReader.
    // Keep the server lifecycle binding when that reader was registered first.
    try {
      Probe.registerNode(reader, "client", 0);
    } catch (IllegalStateException alreadyServerOwned) {
      return;
    }
    Object manager = field(reader, "aliasesManager");
    if (manager != null) {
      try {
        Probe.registerNode(manager, "client", 0);
      } catch (IllegalStateException alreadyServerOwned) {
        // The existing server binding is authoritative.
      }
    }
    registerZkClient(reader, "client", 0);
  }

  /** A SolrZkClient can be shared; conflicting owners make its callbacks unattributable. */
  private static synchronized void registerZkClient(Object reader, String node, int epoch) {
    Object client = invoke(reader, "getZkClient");
    if (client == null || AMBIGUOUS_ZK_CLIENTS.contains(client)) return;
    try {
      Probe.registerNode(client, node, epoch);
    } catch (IllegalStateException conflictingOwner) {
      AMBIGUOUS_ZK_CLIENTS.add(client);
    }
  }

  public static void registerClientProvider(Object provider) {
    registerClientReader(field(provider, "zkStateReader"));
  }

  /** SolrJ executes in the JUnit client process, distinct from the embedded servers. */
  public static void beginClient(Object provider) {
    Probe.registerNode(provider, "client", 0);
    SCOPES.get().push(new Scope("client", Probe.withRegisteredNode(provider), null));
  }

  public static void endClient() { end("client"); }

  public static void beginHttp(Object filter, Object request, boolean retry) {
    Object container = field(filter, "cores");
    Object controller = invoke(container, "getZkController");
    registerController(controller);
    NodeRef ref;
    synchronized (SolrHooks.class) { ref = CONTROLLERS.get(controller); }
    Probe.NodeScope node = ref == null ? Probe.withNode("unknown", 0)
        : Probe.withNode(ref.name, ref.epoch);
    String token = callString(request, "getHeader", HEADER);
    // SolrDispatchFilter recurses for retry. The outer invocation owns the receive edge.
    Probe.ContextScope context = retry ? null : Probe.receiveScope(TRANSPORT, token, PORT,
        "SolrDispatchFilter#doFilter");
    SCOPES.get().push(new Scope("http", node, context));
  }

  public static void endHttp() { end("http"); }

  /** A SolrJ instance belongs to its constructing server or to the test client. */
  public static synchronized void registerHttpClient(Object client) {
    if (client == null || HTTP_CLIENTS.containsKey(client)) return;
    String node = Probe.currentNode();
    int epoch = Probe.currentEpoch();
    if (node == null || "unknown".equals(node)) {
      node = "client";
      epoch = 0;
    }
    Probe.registerNode(client, node, epoch);
    HTTP_CLIENTS.put(client, new NodeRef(node, epoch));
  }

  /** Keep SolrJ request I/O doors on the same actor as the outbound SEND. */
  public static void beginHttpClient(Object client) {
    registerHttpClient(client);
    SCOPES.get().push(new Scope("http_client", Probe.withRegisteredNode(client), null));
  }

  public static void endHttpClient() { end("http_client"); }

  /** Adds a real request header and records SEND under the SolrJ owner. */
  public static void outbound(Object client, Object request) {
    if (request == null) return;
    registerHttpClient(client);
    String token = PREFIX + ":" + SERIAL.incrementAndGet();
    boolean written = invokeVoid(request, "header", HEADER, token)
        || invokeVoid(request, "setHeader", HEADER, token);
    if (!written) return;
    String node = Probe.currentNode();
    if (node == null || "unknown".equals(node)) {
      try (Probe.NodeScope ignored = Probe.withRegisteredNode(client)) {
        Probe.send(TRANSPORT, token, PORT, request.getClass().getName() + "#outbound");
      }
    } else {
      Probe.send(TRANSPORT, token, PORT, request.getClass().getName() + "#outbound");
    }
  }

  /** Preserves the exact submit/claim token and the submitting logical node. */
  public static Runnable wrapTask(final Runnable delegate) {
    if (delegate == null) return null;
    final String token = PREFIX + ":task:" + SERIAL.incrementAndGet();
    final String node = Probe.currentNode();
    final int epoch = Probe.currentEpoch();
    Probe.taskSubmit(token, "ExecutorUtil#execute");
    return new Runnable() {
      @Override public void run() {
        try (Probe.NodeScope ignoredNode = Probe.withNode(node, epoch);
             Probe.ContextScope ignoredContext = Probe.taskClaim(token, "ExecutorUtil#execute")) {
          delegate.run();
        }
      }
    };
  }

  private static void end(String expected) {
    Deque<Scope> stack = SCOPES.get();
    if (stack.isEmpty() || !expected.equals(stack.peek().kind)) return;
    Scope scope = stack.pop();
    if (scope.context != null) scope.context.close();
    scope.node.close();
    if (stack.isEmpty()) SCOPES.remove();
  }

  private static Object field(Object receiver, String name) {
    if (receiver == null) return null;
    for (Class<?> type = receiver.getClass(); type != null; type = type.getSuperclass()) {
      try {
        Field found = type.getDeclaredField(name);
        found.setAccessible(true);
        return found.get(receiver);
      } catch (NoSuchFieldException missing) {
        // Check the superclass.
      } catch (ReflectiveOperationException | SecurityException inaccessible) {
        return null;
      }
    }
    return null;
  }

  private static Object invoke(Object receiver, String method) {
    if (receiver == null) return null;
    try { return receiver.getClass().getMethod(method).invoke(receiver); }
    catch (ReflectiveOperationException | SecurityException failure) { return null; }
  }

  private static String callString(Object receiver, String method) {
    Object value = invoke(receiver, method);
    return value instanceof String ? (String) value : null;
  }

  private static String callString(Object receiver, String method, String argument) {
    if (receiver == null) return null;
    try {
      Object value = receiver.getClass().getMethod(method, String.class).invoke(receiver, argument);
      return value instanceof String ? (String) value : null;
    } catch (ReflectiveOperationException | SecurityException failure) { return null; }
  }

  /** Cluster tests use stable instance roles even when HTTP ports and temp suffixes change. */
  private static String miniClusterRole(Object container, String physicalName) {
    Object home = invoke(container, "getSolrHome");
    if (home instanceof Path || home instanceof String) {
      try {
        Path path = home instanceof Path ? (Path) home : Paths.get((String) home);
        String basename = path.getFileName().toString();
        if (basename.matches("node[0-9]+")) return basename;
        // AbstractFullDistribZkTestBase creates shard-<index>-<temp counter>.
        // The shard index names the Jetty role; the trailing counter is per run.
        if (basename.matches("shard-[0-9]+-[0-9]+"))
          return basename.substring(0, basename.lastIndexOf('-'));
        if (basename.matches("control-[0-9]+")) return "control";
      } catch (RuntimeException invalidPath) {
        // Keep the concrete physical name for unrecognized test layouts.
      }
    }
    return physicalName;
  }

  private static boolean invokeVoid(Object receiver, String method, String first, String second) {
    try {
      Method target = receiver.getClass().getMethod(method, String.class, String.class);
      target.invoke(receiver, first, second);
      return true;
    } catch (ReflectiveOperationException | SecurityException failure) { return false; }
  }

  private static final class NodeRef {
    final String name;
    final int epoch;
    NodeRef(String name, int epoch) { this.name = name; this.epoch = epoch; }
  }

  private static final class StateWatch {
    final Object watcher;
    final Object reader;
    final String collection;
    final String occurrence;
    StateWatch(Object watcher, Object reader, String collection, String occurrence) {
      this.watcher = watcher;
      this.reader = reader;
      this.collection = collection;
      this.occurrence = occurrence;
    }
  }

  private static final class Scope {
    final String kind;
    final Probe.NodeScope node;
    final Probe.ContextScope context;
    Scope(String kind, Probe.NodeScope node, Probe.ContextScope context) {
      this.kind = kind;
      this.node = node;
      this.context = context;
    }
  }
}
