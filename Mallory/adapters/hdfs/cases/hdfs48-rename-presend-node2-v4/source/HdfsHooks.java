package edu.uva.liftlab.mallory.adapters.hdfs;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.SocketAddress;
import java.util.IdentityHashMap;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.WeakHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/** Hadoop 3.4.3 MiniDFSCluster aliases and IPC request handoffs. */
public final class HdfsHooks {
  private static final AtomicInteger CLUSTERS = new AtomicInteger();
  private static final AtomicInteger JOURNAL_CLUSTERS = new AtomicInteger();
  private static final AtomicInteger IMAGE_TASKS = new AtomicInteger();
  private static final AtomicInteger BLOCK_TASKS = new AtomicInteger();
  private static final AtomicInteger STORAGE_UPGRADE_TASKS = new AtomicInteger();
  private static final AtomicInteger BLOCK_RECOVERY_TASKS = new AtomicInteger();
  private static final AtomicInteger BALANCER_TASKS = new AtomicInteger();
  private static final Map<Object, String> CLUSTER_NAMES = new IdentityHashMap<Object, String>();
  private static final Map<Object, Map<Integer, Integer>> NN_EPOCHS =
      new IdentityHashMap<Object, Map<Integer, Integer>>();
  private static final Map<Object, Map<Integer, Object>> NN_OBJECTS =
      new IdentityHashMap<Object, Map<Integer, Object>>();
  private static final Map<Object, String> JOURNAL_CLUSTER_NAMES = new IdentityHashMap<Object, String>();
  private static final Map<Object, int[]> JOURNAL_EPOCHS = new IdentityHashMap<Object, int[]>();
  private static final Map<Object, Map<Integer, Integer>> DN_EPOCHS =
      new IdentityHashMap<Object, Map<Integer, Integer>>();
  private static final Map<Object, Integer> DN_OBJECT_EPOCHS = new IdentityHashMap<Object, Integer>();
  private static final Map<Object, String> IMAGE_TASK_TOKENS = new IdentityHashMap<Object, String>();
  private static final Map<Object, String> BLOCK_TASK_TOKENS = new IdentityHashMap<Object, String>();
  private static final Map<Object, String> STORAGE_UPGRADE_TASK_TOKENS =
      new IdentityHashMap<Object, String>();
  private static final Map<Object, String> BLOCK_RECOVERY_TASK_TOKENS =
      new IdentityHashMap<Object, String>();
  private static final Map<Object, String> BALANCER_TASK_TOKENS =
      new IdentityHashMap<Object, String>();
  private static final ThreadLocal<Object> ACTOR_DATANODE = new ThreadLocal<Object>();
  private static final ThreadLocal<Boolean> CREATING_NAMENODE = new ThreadLocal<Boolean>();
  private static final ThreadLocal<ResponseConsumerScope> RESPONSE_CONSUMER =
      new ThreadLocal<ResponseConsumerScope>();
  // A completed RPC Call can rethrow the same RemoteException through more
  // than one ATHROW in getRpcResponse. Emit one receive per delivered Call.
  // Call has object identity; weak keys keep completed calls reclaimable.
  private static final Map<Object, Object> RECEIVED_RPC_ERRORS =
      new WeakHashMap<Object, Object>();
  private static final ThreadLocal<Deque<String>> SASL_CLIENT_CONNECTIONS =
      new ThreadLocal<Deque<String>>();
  private static final String SASL_TRANSPORT = "hdfs-data-sasl";
  private static final String SASL_PORT = "initial-message";

  private HdfsHooks() { }

  /** A MiniCluster constructor knows the future actor index before NameNode startup. */
  public static NameNodeCreationScope nameNodeCreationEnter(Object cluster) {
    String node;
    int epoch;
    synchronized (HdfsHooks.class) {
      String prefix = CLUSTER_NAMES.get(cluster);
      if (prefix == null) {
        prefix = "hdfs-cluster-" + CLUSTERS.incrementAndGet();
        CLUSTER_NAMES.put(cluster, prefix);
      }
      try {
        int index = ((Object[]) invoke(cluster, "getNameNodeInfos")).length;
        node = prefix + "/nn" + index;
        epoch = 0;
      } catch (ReflectiveOperationException | ClassCastException failure) {
        throw new IllegalStateException("HDFS NameNode creation index unavailable", failure);
      }
    }
    Boolean previous = CREATING_NAMENODE.get();
    CREATING_NAMENODE.set(Boolean.TRUE);
    return new NameNodeCreationScope(previous, Probe.withNode(node, epoch));
  }

  public static final class NameNodeCreationScope implements AutoCloseable {
    private final Boolean previous;
    private final Probe.NodeScope node;
    private NameNodeCreationScope(Boolean previous, Probe.NodeScope node) {
      this.previous = previous;
      this.node = node;
    }
    @Override public void close() {
      node.close();
      if (previous == null) CREATING_NAMENODE.remove();
      else CREATING_NAMENODE.set(previous);
    }
  }

  /** Bind the concrete namesystem while it is being built inside a known MiniCluster actor. */
  public static void namesystemConstructed(Object namesystem) {
    if (Boolean.TRUE.equals(CREATING_NAMENODE.get())) Probe.registerCurrentNode(namesystem);
  }

  /** Register a DN before its daemon starts; Builder.build returns too late for startup checks. */
  public static synchronized void dataNodeStarting(Object dn, Object cluster) {
    if (dn == null || cluster == null) return;
    String prefix = CLUSTER_NAMES.get(cluster);
    if (prefix == null) {
      prefix = "hdfs-cluster-" + CLUSTERS.incrementAndGet();
      CLUSTER_NAMES.put(cluster, prefix);
    }
    try {
      Object existing = field(cluster, "dataNodes");
      if (!(existing instanceof List<?>))
        throw new IllegalStateException("MiniDFSCluster.dataNodes is not a list");
      int index = ((List<?>) existing).size();
      String node = prefix + "/dn" + index;
      Map<Integer, Integer> epochs = DN_EPOCHS.get(cluster);
      if (epochs == null) {
        epochs = new HashMap<Integer, Integer>();
        DN_EPOCHS.put(cluster, epochs);
      }
      int epoch = epochs.containsKey(index) ? epochs.get(index) + 1 : 0;
      epochs.put(index, epoch);
      DN_OBJECT_EPOCHS.put(dn, epoch);
      Probe.registerNode(dn, node, epoch);
      register(field(dn, "storage"), node, epoch);
      register(field(dn, "blockPoolManager"), node, epoch);
    } catch (ReflectiveOperationException failure) {
      throw new IllegalStateException("HDFS early DataNode registration failed", failure);
    }
  }

  /** Called on Builder.build's successful return, after all MiniCluster services exist. */
  public static synchronized void clusterBuilt(Object cluster) {
    String prefix = CLUSTER_NAMES.get(cluster);
    if (prefix == null) {
      prefix = "hdfs-cluster-" + CLUSTERS.incrementAndGet();
      CLUSTER_NAMES.put(cluster, prefix);
    }
    try {
      registerNameNodes(cluster, prefix);
      List<?> dns = (List<?>) invoke(cluster, "getDataNodes");
      for (int i = 0; i < dns.size(); i++) {
        Object dn = dns.get(i);
        if (dn == null) continue;
        String node = prefix + "/dn" + i;
        int epoch = DN_OBJECT_EPOCHS.containsKey(dn) ? DN_OBJECT_EPOCHS.get(dn) : 0;
        Probe.registerNode(dn, node, epoch);
        register(field(dn, "storage"), node, epoch);
        register(field(dn, "ipcServer"), node, epoch);
        Object poolManager = field(dn, "blockPoolManager");
        register(poolManager, node, epoch);
        if (poolManager != null) {
          Object offers = invoke(poolManager, "getAllNamenodeThreads");
          for (Object offer : (List<?>) offers) {
            register(offer, node, epoch);
            Object actors = field(offer, "bpServices");
            if (actors instanceof List<?>) for (Object actor : (List<?>) actors)
              register(actor, node, epoch);
          }
        }
      }
    } catch (ReflectiveOperationException | ClassCastException failure) {
      throw new IllegalStateException("HDFS MiniCluster node registration failed", failure);
    }
  }

  /** The NameNode's IPC servers must be named before DataNode startup handshakes. */
  public static synchronized void nameNodesAvailable(Object cluster) {
    if (cluster == null) return;
    String prefix = CLUSTER_NAMES.get(cluster);
    if (prefix == null) {
      prefix = "hdfs-cluster-" + CLUSTERS.incrementAndGet();
      CLUSTER_NAMES.put(cluster, prefix);
    }
    try {
      registerNameNodes(cluster, prefix);
    } catch (ReflectiveOperationException | ClassCastException failure) {
      throw new IllegalStateException("HDFS early NameNode registration failed", failure);
    }
  }

  private static void registerNameNodes(Object cluster, String prefix)
      throws ReflectiveOperationException {
    Object[] nns = (Object[]) invoke(cluster, "getNameNodeInfos");
    Map<Integer, Integer> epochs = NN_EPOCHS.get(cluster);
    Map<Integer, Object> objects = NN_OBJECTS.get(cluster);
    if (epochs == null) {
      epochs = new HashMap<Integer, Integer>();
      NN_EPOCHS.put(cluster, epochs);
      objects = new HashMap<Integer, Object>();
      NN_OBJECTS.put(cluster, objects);
    }
    for (int i = 0; i < nns.length; i++) {
      Object nn = field(nns[i], "nameNode");
      if (nn == null) continue;
      if (objects.get(i) != nn) {
        epochs.put(i, epochs.containsKey(i) ? epochs.get(i) + 1 : 0);
        objects.put(i, nn);
      }
      int epoch = epochs.get(i);
      String node = prefix + "/nn" + i;
      Probe.registerNode(nn, node, epoch);
      Object namesystem = invoke(nn, "getNamesystem");
      register(namesystem, node, epoch);
      register(invoke(namesystem, "getBlockManager"), node, epoch);
      Object rpc = invoke(nn, "getRpcServer");
      register(rpc, node, epoch);
      for (String name : new String[] {"clientRpcServer", "serviceRpcServer", "lifelineRpcServer"})
        register(field(rpc, name), node, epoch);
    }
  }

  private static void register(Object receiver, String node) {
    if (receiver != null) Probe.registerNode(receiver, node, 0);
  }

  private static void register(Object receiver, String node, int epoch) {
    if (receiver != null) Probe.registerNode(receiver, node, epoch);
  }

  /** Register all JournalNode actors after MiniJournalCluster.Builder.build. */
  public static synchronized void journalClusterBuilt(Object cluster) {
    try {
      Object[] infos = (Object[]) field(cluster, "nodes");
      String prefix = JOURNAL_CLUSTER_NAMES.get(cluster);
      if (prefix == null) {
        prefix = "hdfs-journal-cluster-" + JOURNAL_CLUSTERS.incrementAndGet();
        JOURNAL_CLUSTER_NAMES.put(cluster, prefix);
      }
      int[] epochs = JOURNAL_EPOCHS.get(cluster);
      if (epochs == null || epochs.length != infos.length) {
        epochs = new int[infos.length];
        JOURNAL_EPOCHS.put(cluster, epochs);
      }
      for (int i = 0; i < infos.length; i++)
        registerJournalNode(field(infos[i], "node"), prefix + "/jn" + i, epochs[i]);
    } catch (ReflectiveOperationException | ClassCastException failure) {
      throw new IllegalStateException("HDFS MiniJournalCluster node registration failed", failure);
    }
  }

  /** A restarted JournalNode is a new actor epoch with a new IPC server. */
  public static synchronized void journalNodeRestarted(Object cluster, int index) {
    try {
      Object[] infos = (Object[]) field(cluster, "nodes");
      int[] epochs = JOURNAL_EPOCHS.get(cluster);
      String prefix = JOURNAL_CLUSTER_NAMES.get(cluster);
      if (prefix == null || epochs == null || index < 0 || index >= infos.length)
        throw new IllegalStateException("JournalNode restart before cluster registration");
      registerJournalNode(field(infos[index], "node"), prefix + "/jn" + index,
          ++epochs[index]);
    } catch (ReflectiveOperationException | ClassCastException failure) {
      throw new IllegalStateException("HDFS restarted JournalNode registration failed", failure);
    }
  }

  private static void registerJournalNode(Object jn, String node, int epoch)
      throws ReflectiveOperationException {
    if (jn == null) return;
    Probe.registerNode(jn, node, epoch);
    Object rpc = invoke(jn, "getRpcServer");
    if (rpc != null) {
      Probe.registerNode(rpc, node, epoch);
      Object server = field(rpc, "server");
      if (server != null) Probe.registerNode(server, node, epoch);
    }
    Object journals = field(jn, "journalsById");
    if (journals instanceof Map<?, ?>)
      for (Object journal : ((Map<?, ?>) journals).values())
        if (journal != null) Probe.registerNode(journal, node, epoch);
  }

  /** Bind a lazily constructed Journal to its owning JournalNode. */
  public static void journalObtained(Object journal, Object jn) {
    if (journal == null || jn == null) return;
    try (Probe.NodeScope ignored = Probe.withRegisteredNode(jn)) {
      if (!"unknown".equals(Probe.currentNode()))
        Probe.registerNode(journal, Probe.currentNode(), Probe.currentEpoch());
    }
  }

  public static Probe.NodeScope journalEnter(Object journal) {
    return Probe.withRegisteredNode(journal);
  }

  /** A direct test call into the NameNode's block-report handler is server work. */
  public static Probe.NodeScope blockManagerEnter(Object manager) {
    return Probe.withRegisteredNode(manager);
  }

  /** Bind snapshot serialization to the owning namesystem, even on a test thread. */
  public static Probe.NodeScope snapshotSaverEnter(Object saver) {
    try {
      return Probe.withRegisteredNode(field(saver, "fsn"));
    } catch (ReflectiveOperationException failure) {
      return Probe.withNode("unknown", 0);
    }
  }

  /** Link a concrete FSImageSaver object to its worker without thread-name inference. */
  public static synchronized void imageSaverConstructed(Object saver) {
    if (Boolean.TRUE.equals(CREATING_NAMENODE.get())) {
      try {
        Object context = field(saver, "context");
        Probe.registerCurrentNode(invoke(context, "getSourceNamesystem"));
      } catch (ReflectiveOperationException failure) {
        throw new IllegalStateException("HDFS startup image owner unavailable", failure);
      }
    }
    String token = "hdfs-fsimage:" + IMAGE_TASKS.incrementAndGet();
    IMAGE_TASK_TOKENS.put(saver, token);
    Probe.taskSubmit(token, "hdfs-fsimage");
  }

  public static ImageSaverScope imageSaverEnter(Object saver) {
    Probe.NodeScope node;
    try {
      Object context = field(saver, "context");
      node = Probe.withRegisteredNode(invoke(context, "getSourceNamesystem"));
    } catch (ReflectiveOperationException failure) {
      node = Probe.withNode("unknown", 0);
    }
    String token;
    synchronized (HdfsHooks.class) {
      token = IMAGE_TASK_TOKENS.get(saver);
    }
    Probe.ContextScope task = Probe.taskClaim(token, "hdfs-fsimage");
    return new ImageSaverScope(node, task);
  }

  /** The NameNode RPC handler transfers one concrete block operation into the report queue. */
  public static synchronized void blockOpSubmitted(Object manager, Object action) {
    if (manager == null || action == null) return;
    String token = "hdfs-block-op:" + BLOCK_TASKS.incrementAndGet();
    BLOCK_TASK_TOKENS.put(action, token);
    Probe.taskSubmit(token, "hdfs-block-report-queue");
  }

  /** Claim exactly the queued Runnable consumed by BlockReportProcessingThread. */
  public static BlockOpScope blockOpEnter(Object worker, Object action) {
    Probe.NodeScope node;
    try {
      node = Probe.withRegisteredNode(field(worker, "this$0"));
    } catch (ReflectiveOperationException failure) {
      node = Probe.withNode("unknown", 0);
    }
    String token;
    synchronized (HdfsHooks.class) {
      token = BLOCK_TASK_TOKENS.remove(action);
    }
    Probe.ContextScope task = Probe.taskClaim(token, "hdfs-block-report-queue");
    return new BlockOpScope(node, task);
  }

  public static final class BlockOpScope implements AutoCloseable {
    private final Probe.NodeScope node;
    private final Probe.ContextScope task;
    private BlockOpScope(Probe.NodeScope node, Probe.ContextScope task) {
      this.node = node;
      this.task = task;
    }
    @Override public void close() {
      task.close();
      node.close();
    }
  }

  public static RpcScope rpcEnter(Object call) {
    Probe.NodeScope nodeScope;
    try {
      Object connection = field(call, "connection");
      Object server = field(connection, "this$0");
      nodeScope = Probe.withRegisteredNode(server);
    } catch (ReflectiveOperationException failure) {
      nodeScope = Probe.withNode("unknown", 0);
    }
    String token = serverCorrelation(call);
    Probe.ContextScope request = Probe.receiveScope("hadoop-ipc", token, "request",
        "org.apache.hadoop.ipc.Server.RpcCall#run");
    return new RpcScope(nodeScope, request);
  }

  /** Observe only a ClientProtocol.rename request before it is queued. */
  public static void rpcBeforeRenameSend(Object call) {
    final Object request;
    try { request = field(call, "rpcRequest"); }
    catch (ReflectiveOperationException failure) {
      throw new IllegalStateException("HDFS client RPC request unavailable", failure);
    }
    if (request == null || !request.getClass().getName().equals(
        "org.apache.hadoop.ipc.ProtobufRpcEngine2$RpcProtobufRequest")) return;
    if (!"org.apache.hadoop.hdfs.protocol.ClientProtocol.rename"
        .equals(request.toString())) return;
    Probe.beforeDoor("hdfs:client-send-rpc-request:rename",
        "java.io.IOException");
  }

  public static void rpcSend(Object connection, Object call) {
    String token = correlationFromConnection(connection, call);
    if ("unknown".equals(Probe.currentNode())) {
      Object actor = ACTOR_DATANODE.get();
      if (actor != null) {
        try (Probe.NodeScope node = Probe.withRegisteredNode(actor)) {
          Probe.send("hadoop-ipc", token, "request",
              "org.apache.hadoop.ipc.Client.Connection#sendRpcRequest");
          return;
        }
      }
    }
    Probe.send("hadoop-ipc", token, "request",
        "org.apache.hadoop.ipc.Client.Connection#sendRpcRequest");
  }

  /** The server has enqueued a concrete response for this exact request. */
  public static void rpcResponseSent(Object call) {
    String token = serverCorrelation(call);
    try {
      Object connection = field(call, "connection");
      Object server = field(connection, "this$0");
      try (Probe.NodeScope ignored = Probe.withRegisteredNode(server)) {
        Probe.send("hadoop-ipc", token, "response",
            "org.apache.hadoop.ipc.Server.Connection#sendResponse");
      }
    } catch (ReflectiveOperationException failure) {
      Probe.send("hadoop-ipc", token, "response",
          "org.apache.hadoop.ipc.Server.Connection#sendResponse");
    }
  }

  /** The caller has finished waiting and received the response value. */
  public static void rpcResponseConsumed(Object response, Object connection, Object call) {
    if (response == null) return; // Timeout/async pending is not a received value.
    String correlation = correlationFromConnection(connection, call);
    ResponseConsumerScope consumer = RESPONSE_CONSUMER.get();
    if (consumer != null && correlation != null) {
      if (consumer.latestOnly) consumer.clearResponses();
      Object actor = consumer.actor;
      if (actor != null) {
        try (Probe.NodeScope node = Probe.withRegisteredNode(actor)) {
          consumer.responses.push(Probe.receiveScope("hadoop-ipc", correlation, "response",
              "org.apache.hadoop.ipc.Client#getRpcResponse"));
        }
      } else {
        consumer.responses.push(Probe.receiveScope("hadoop-ipc", correlation, "response",
            "org.apache.hadoop.ipc.Client#getRpcResponse"));
      }
    } else {
      Probe.receive("hadoop-ipc", correlation, "response",
          "org.apache.hadoop.ipc.Client#getRpcResponse");
    }
  }

  /** Record a completed server error response when the caller consumes it.
   *
   * Client.getRpcResponse throws RemoteException instead of returning a
   * Writable, so the successful-return hook above cannot observe this reply.
   * Match the exact Call.error object and its completed state. Local errors,
   * interruption, and an incomplete asynchronous call are not deliveries.
   */
  public static void rpcErrorConsumed(Object thrown, Object connection, Object call) {
    try {
      Object error = field(call, "error");
      if (thrown != error || error == null ||
          !"org.apache.hadoop.ipc.RemoteException".equals(error.getClass().getName()) ||
          !Boolean.TRUE.equals(field(call, "done"))) return;
      String correlation = correlationFromConnection(connection, call);
      if (correlation == null) return;
      synchronized (RECEIVED_RPC_ERRORS) {
        if (RECEIVED_RPC_ERRORS.get(call) == error) return;
        RECEIVED_RPC_ERRORS.put(call, error);
      }
      ResponseConsumerScope consumer = RESPONSE_CONSUMER.get();
      if (consumer != null && consumer.latestOnly) {
        // A failed heartbeat may cause an immediate retry on this exact
        // BPServiceActor thread. Keep the error reply as that retry's parent
        // until another response replaces it or the state check completes.
        consumer.clearResponses();
        if (consumer.actor != null) {
          try (Probe.NodeScope node = Probe.withRegisteredNode(consumer.actor)) {
            consumer.responses.push(Probe.receiveScope("hadoop-ipc", correlation, "response",
                "org.apache.hadoop.ipc.Client#getRpcResponse.error"));
          }
        } else {
          consumer.responses.push(Probe.receiveScope("hadoop-ipc", correlation, "response",
              "org.apache.hadoop.ipc.Client#getRpcResponse.error"));
        }
      } else {
        Probe.receive("hadoop-ipc", correlation, "response",
            "org.apache.hadoop.ipc.Client#getRpcResponse.error");
      }
    } catch (ReflectiveOperationException ignored) {
      // Missing identity is a graph gap. Never infer a reply from timing.
    }
  }

  /** A KeyManager belongs to the Balancer client that constructed it. */
  public static void balancerKeyManagerConstructed(Object manager) {
    Probe.registerCurrentNode(manager);
    try {
      Object updater = field(manager, "blockKeyUpdater");
      if (updater != null) Probe.registerCurrentNode(updater);
    } catch (ReflectiveOperationException ignored) {
      // No updater exists when block tokens are disabled.
    }
  }

  /** The concrete updater object crosses from Balancer startup to its daemon. */
  public static void balancerKeyUpdaterSubmitted(Object manager) {
    try {
      Object updater = field(manager, "blockKeyUpdater");
      if (updater == null) return;
      String token;
      synchronized (HdfsHooks.class) {
        token = "hdfs-balancer-key-updater:" + BALANCER_TASKS.incrementAndGet();
        BALANCER_TASK_TOKENS.put(updater, token);
      }
      try (Probe.NodeScope node = Probe.withRegisteredNode(manager)) {
        Probe.taskSubmit(token, "hdfs-balancer-key-updater");
      }
    } catch (ReflectiveOperationException ignored) {
      // A missing owner is an identity gap, not a synthetic handoff.
    }
  }

  public static BalancerTaskScope balancerKeyUpdaterEnter(Object updater) {
    Probe.NodeScope node = Probe.withRegisteredNode(updater);
    String token;
    synchronized (HdfsHooks.class) {
      token = BALANCER_TASK_TOKENS.remove(updater);
    }
    Probe.ContextScope task = token == null ? null :
        Probe.taskClaim(token, "hdfs-balancer-key-updater");
    return new BalancerTaskScope(node, task);
  }

  /** A PendingMove is submitted by the Balancer client to its move executor.
   * This explicit class-owned actor does not depend on the executor thread name.
   */
  public static void balancerMoveSubmitted(Object move) {
    if (move == null) return;
    String token;
    synchronized (HdfsHooks.class) {
      token = "hdfs-balancer-move:" + BALANCER_TASKS.incrementAndGet();
      BALANCER_TASK_TOKENS.put(move, token);
    }
    try (Probe.NodeScope node = Probe.withNode("hdfs-client", 0)) {
      Probe.taskSubmit(token, "hdfs-balancer-move");
    }
  }

  public static BalancerTaskScope balancerMoveEnter(Object move) {
    Probe.NodeScope node = Probe.withNode("hdfs-client", 0);
    String token;
    synchronized (HdfsHooks.class) {
      token = BALANCER_TASK_TOKENS.remove(move);
    }
    Probe.ContextScope task = token == null ? null :
        Probe.taskClaim(token, "hdfs-balancer-move");
    return new BalancerTaskScope(node, task);
  }

  /** Scope one DFSInputStream block-selection retry loop to its real caller.
   * The same invocation consumes an RPC error and may issue a later key RPC.
   */
  public static ClientOperationScope clientBlockSeekEnter(Object stream) {
    Probe.NodeScope node = Probe.withNode("hdfs-client", 0);
    Probe.regionEnter("org.apache.hadoop.hdfs.DFSInputStream#blockSeekTo");
    return new ClientOperationScope(node);
  }

  /** Bound the continuation of a synchronous RPC reply to its caller method. */
  public static ResponseConsumerScope responseConsumerEnter(Object owner) {
    Object actor;
    try {
      actor = field(owner, "dn");
    } catch (ReflectiveOperationException failure) {
      actor = null;
    }
    ResponseConsumerScope scope = new ResponseConsumerScope(RESPONSE_CONSUMER.get(), actor, false);
    RESPONSE_CONSUMER.set(scope);
    return scope;
  }

  public static final class ResponseConsumerScope implements AutoCloseable {
    private final ResponseConsumerScope previous;
    private final Object actor;
    private final boolean latestOnly;
    private final Deque<Probe.ContextScope> responses = new ArrayDeque<Probe.ContextScope>();
    private ResponseConsumerScope(ResponseConsumerScope previous, Object actor,
                                  boolean latestOnly) {
      this.previous = previous;
      this.actor = actor;
      this.latestOnly = latestOnly;
    }
    private void clearResponses() {
      while (!responses.isEmpty()) responses.pop().close();
    }
    @Override public void close() {
      clearResponses();
      if (previous == null) RESPONSE_CONSUMER.remove();
      else RESPONSE_CONSUMER.set(previous);
    }
  }

  /** Keep a heartbeat's concrete DataNode actor through its reply and state check.
   *
   * BPServiceActor.offerService consumes sendHeartBeat's response and then calls
   * BPOfferService.updateActorStatesFromHeartbeat. A scope only on sendHeartBeat
   * would close before that target check. Retain only the latest exact response
   * context across the offerService loop so old replies cannot accumulate.
   */
  public static HeartbeatScope heartbeatEnter(Object actor) {
    ActorScope node = actorEnter(actor);
    Object dn;
    try { dn = field(actor, "dn"); }
    catch (ReflectiveOperationException failure) { dn = null; }
    ResponseConsumerScope response = new ResponseConsumerScope(RESPONSE_CONSUMER.get(), dn, true);
    RESPONSE_CONSUMER.set(response);
    return new HeartbeatScope(node, response);
  }

  /** End the exact reply's continuation after the heartbeat state check. */
  public static void heartbeatStateUpdated() {
    ResponseConsumerScope consumer = RESPONSE_CONSUMER.get();
    if (consumer != null && consumer.latestOnly) consumer.clearResponses();
  }

  public static final class HeartbeatScope implements AutoCloseable {
    private final ActorScope node;
    private final ResponseConsumerScope response;
    private boolean closed;
    private HeartbeatScope(ActorScope node, ResponseConsumerScope response) {
      this.node = node;
      this.response = response;
    }
    @Override public void close() {
      if (closed) return;
      closed = true;
      response.close();
      node.close();
    }
  }

  public static ActorScope actorEnter(Object actor) {
    Object previous = ACTOR_DATANODE.get();
    Probe.NodeScope node;
    try {
      Object dn = field(actor, "dn");
      ACTOR_DATANODE.set(dn);
      node = Probe.withRegisteredNode(dn);
    } catch (ReflectiveOperationException failure) {
      ACTOR_DATANODE.remove();
      node = Probe.withNode("unknown", 0);
    }
    return new ActorScope(previous, node);
  }

  public static Probe.NodeScope offerEnter(Object offer) {
    try {
      return Probe.withRegisteredNode(field(offer, "dn"));
    } catch (ReflectiveOperationException failure) {
      return Probe.withNode("unknown", 0);
    }
  }

  public static Probe.NodeScope serviceActorEnter(Object actor) {
    try {
      return Probe.withRegisteredNode(field(actor, "dn"));
    } catch (ReflectiveOperationException failure) {
      return Probe.withNode("unknown", 0);
    }
  }

  /** DataStorage returns its own concrete block-pool slice instance. */
  public static void blockPoolStorageObtained(Object pool, Object storage) {
    if (pool == null) return;
    try (Probe.NodeScope ignored = Probe.withRegisteredNode(storage)) {
      if (!"unknown".equals(Probe.currentNode()))
        Probe.registerNode(pool, Probe.currentNode(), Probe.currentEpoch());
    }
  }

  public static Probe.NodeScope blockPoolStorageEnter(Object pool) {
    return Probe.withRegisteredNode(pool);
  }

  /** Connect one concrete block-pool upgrade Callable to its executor thread. */
  public static synchronized void storageUpgradeSubmitted(Object callable) {
    if (callable == null) return;
    String token = "hdfs-storage-upgrade:" + STORAGE_UPGRADE_TASKS.incrementAndGet();
    STORAGE_UPGRADE_TASK_TOKENS.put(callable, token);
    try (Probe.NodeScope ignored = Probe.withRegisteredNode(field(callable, "this$0"))) {
      Probe.taskSubmit(token, "hdfs-storage-upgrade");
    } catch (ReflectiveOperationException failure) {
      try (Probe.NodeScope ignored = Probe.withNode("unknown", 0)) {
        Probe.taskSubmit(token, "hdfs-storage-upgrade");
      }
    }
  }

  public static StorageUpgradeScope storageUpgradeEnter(Object callable) {
    Probe.NodeScope node;
    try {
      node = Probe.withRegisteredNode(field(callable, "this$0"));
    } catch (ReflectiveOperationException failure) {
      node = Probe.withNode("unknown", 0);
    }
    String token;
    synchronized (HdfsHooks.class) {
      token = STORAGE_UPGRADE_TASK_TOKENS.remove(callable);
    }
    return new StorageUpgradeScope(node, Probe.taskClaim(token, "hdfs-storage-upgrade"));
  }

  public static final class StorageUpgradeScope implements AutoCloseable {
    private final Probe.NodeScope node;
    private final Probe.ContextScope task;
    private StorageUpgradeScope(Probe.NodeScope node, Probe.ContextScope task) {
      this.node = node;
      this.task = task;
    }
    @Override public void close() {
      task.close();
      node.close();
    }
  }

  public static Probe.NodeScope dataStorageEnter(Object storage) {
    return Probe.withRegisteredNode(storage);
  }

  public static Probe.NodeScope blockRecoveryEnter(Object worker) {
    try {
      return Probe.withRegisteredNode(field(worker, "datanode"));
    } catch (ReflectiveOperationException failure) {
      return Probe.withNode("unknown", 0);
    }
  }

  /** The DataNode submits the exact Runnable later consumed by its recovery daemon. */
  public static synchronized void blockRecoverySubmitted(Object runnable) {
    if (runnable == null) return;
    String token = "hdfs-block-recovery:" + BLOCK_RECOVERY_TASKS.incrementAndGet();
    BLOCK_RECOVERY_TASK_TOKENS.put(runnable, token);
    try {
      Object worker = field(runnable, "this$0");
      try (Probe.NodeScope ignored = Probe.withRegisteredNode(field(worker, "datanode"))) {
        Probe.taskSubmit(token, "hdfs-block-recovery");
      }
    } catch (ReflectiveOperationException failure) {
      try (Probe.NodeScope ignored = Probe.withNode("unknown", 0)) {
        Probe.taskSubmit(token, "hdfs-block-recovery");
      }
    }
  }

  public static BlockRecoveryTaskScope blockRecoveryTaskEnter(Object runnable) {
    Probe.NodeScope node;
    try {
      Object worker = field(runnable, "this$0");
      node = Probe.withRegisteredNode(field(worker, "datanode"));
    } catch (ReflectiveOperationException failure) {
      node = Probe.withNode("unknown", 0);
    }
    String token;
    synchronized (HdfsHooks.class) {
      token = BLOCK_RECOVERY_TASK_TOKENS.remove(runnable);
    }
    return new BlockRecoveryTaskScope(node, Probe.taskClaim(token, "hdfs-block-recovery"));
  }

  public static final class BlockRecoveryTaskScope implements AutoCloseable {
    private final Probe.NodeScope node;
    private final Probe.ContextScope task;
    private BlockRecoveryTaskScope(Probe.NodeScope node, Probe.ContextScope task) {
      this.node = node;
      this.task = task;
    }
    @Override public void close() {
      task.close();
      node.close();
    }
  }

  public static Probe.NodeScope volumeBuilderEnter(Object builder) {
    try {
      return Probe.withRegisteredNode(field(builder, "storage"));
    } catch (ReflectiveOperationException failure) {
      return Probe.withNode("unknown", 0);
    }
  }

  /** Bind a data-transfer worker to the registered DataNode that owns it. */
  public static Probe.NodeScope datanodeEnter(Object xceiver) {
    try {
      return Probe.withRegisteredNode(field(xceiver, "datanode"));
    } catch (ReflectiveOperationException failure) {
      return Probe.withNode("unknown", 0);
    }
  }

  /** Keep the exact TCP endpoints through the client's private handshake methods. */
  public static SaslClientScope saslClientEnter(Object endpoint) {
    Deque<String> connections = SASL_CLIENT_CONNECTIONS.get();
    if (connections == null) {
      connections = new ArrayDeque<String>();
      SASL_CLIENT_CONNECTIONS.set(connections);
    }
    String tuple = clientTuple(endpoint);
    connections.push(tuple == null ? "" : tuple);
    return new SaslClientScope();
  }

  public static final class SaslClientScope implements AutoCloseable {
    private boolean closed;
    @Override public void close() {
      if (closed) return;
      closed = true;
      Deque<String> connections = SASL_CLIENT_CONNECTIONS.get();
      if (connections == null || connections.isEmpty()) return;
      connections.pop();
      if (connections.isEmpty()) SASL_CLIENT_CONNECTIONS.remove();
    }
  }

  /** Called only after the first SASL protobuf has been written successfully. */
  public static void saslInitialMessageSent() {
    Deque<String> connections = SASL_CLIENT_CONNECTIONS.get();
    String tuple = connections == null || connections.isEmpty() ? null : connections.peek();
    if (tuple != null && !tuple.isEmpty()) {
      Probe.send(SASL_TRANSPORT, tuple, SASL_PORT, "hdfs:sasl-initial-message-written");
      // The next operation reads the DataNode's first response. A fault here
      // leaves the flushed request on the wire, so the server can still reach
      // the secret-key check. The SEND and door share one client occurrence.
      Probe.beforeDoor("hdfs:sasl-first-response-read", "java.io.IOException");
    }
  }

  /** Called only after the DataNode has parsed that same first protobuf. */
  public static Probe.ContextScope saslInitialMessageReceived(Object peer) {
    String tuple = serverTuple(peer);
    return Probe.receiveScope(SASL_TRANSPORT, tuple, SASL_PORT,
        "hdfs:sasl-initial-message-read");
  }

  static String clientTuple(Object endpoint) {
    if (endpoint instanceof Socket) {
      Socket socket = (Socket) endpoint;
      String local = socketEndpoint(socket.getLocalSocketAddress());
      String remote = socketEndpoint(socket.getRemoteSocketAddress());
      return local == null || remote == null ? null : local + "->" + remote;
    }
    try {
      String local = peerEndpoint((String) invoke(endpoint, "getLocalAddressString"));
      String remote = peerEndpoint((String) invoke(endpoint, "getRemoteAddressString"));
      return local == null || remote == null ? null : local + "->" + remote;
    } catch (ReflectiveOperationException | ClassCastException failure) {
      return null;
    }
  }

  static String serverTuple(Object peer) {
    try {
      String client = peerEndpoint((String) invoke(peer, "getRemoteAddressString"));
      String server = peerEndpoint((String) invoke(peer, "getLocalAddressString"));
      return client == null || server == null ? null : client + "->" + server;
    } catch (ReflectiveOperationException | ClassCastException failure) {
      return null;
    }
  }

  private static String socketEndpoint(SocketAddress address) {
    if (!(address instanceof InetSocketAddress)) return null;
    InetSocketAddress inet = (InetSocketAddress) address;
    if (inet.getAddress() == null || inet.getPort() <= 0) return null;
    return endpoint(inet.getAddress().getHostAddress(), inet.getPort());
  }

  /** Peer strings may be hostname/ip:port or /ip:port; never resolve hostnames. */
  private static String peerEndpoint(String value) {
    if (value == null || value.startsWith("unix:") || value.equals("<local>")) return null;
    int slash = value.lastIndexOf('/');
    if (slash >= 0) value = value.substring(slash + 1);
    String host;
    String portText;
    if (value.startsWith("[")) {
      int bracket = value.indexOf(']');
      if (bracket < 0 || bracket + 1 >= value.length() || value.charAt(bracket + 1) != ':')
        return null;
      host = value.substring(1, bracket);
      portText = value.substring(bracket + 2);
    } else {
      int colon = value.lastIndexOf(':');
      if (colon < 0) return null;
      host = value.substring(0, colon);
      if (host.indexOf(':') >= 0) return null; // IPv6 must carry explicit brackets.
      portText = value.substring(colon + 1);
    }
    if (host.isEmpty() || !host.matches("[0-9a-fA-F:.%]+")) return null;
    try {
      int port = Integer.parseInt(portText);
      return port > 0 && port <= 65535 ? endpoint(host, port) : null;
    } catch (NumberFormatException failure) {
      return null;
    }
  }

  private static String endpoint(String host, int port) {
    return (host.indexOf(':') >= 0 ? "[" + host + "]" : host) + ":" + port;
  }

  private static String serverCorrelation(Object call) {
    try {
      int id = ((Number) field(call, "callId")).intValue();
      int retry = ((Number) field(call, "retryCount")).intValue();
      byte[] client = (byte[]) field(call, "clientId");
      StringBuilder token = new StringBuilder(2 * client.length + 32);
      for (byte b : client) {
        int value = b & 0xff;
        token.append(Character.forDigit(value >>> 4, 16));
        token.append(Character.forDigit(value & 15, 16));
      }
      return token.append(':').append(id).append(':').append(retry).toString();
    } catch (ReflectiveOperationException | ClassCastException failure) {
      return null; // An unmatched event is a recorded graph gap, not a guessed edge.
    }
  }

  /** Client.Call has no clientId; its enclosing Client owns the header field. */
  private static String correlationFromConnection(Object connection, Object call) {
    try {
      Object client = field(connection, "this$0");
      byte[] clientId = (byte[]) field(client, "clientId");
      int id = ((Number) field(call, "id")).intValue();
      int retry = ((Number) field(call, "retry")).intValue();
      StringBuilder token = new StringBuilder(2 * clientId.length + 32);
      for (byte b : clientId) {
        int value = b & 0xff;
        token.append(Character.forDigit(value >>> 4, 16));
        token.append(Character.forDigit(value & 15, 16));
      }
      return token.append(':').append(id).append(':').append(retry).toString();
    } catch (ReflectiveOperationException | ClassCastException failure) {
      return null;
    }
  }

  /** The selected JUnit method is a client root, independent of server objects. */
  public static Probe.NodeScope clientEnter() {
    return Probe.withNode("hdfs-client", 0);
  }

  private static Object field(Object receiver, String name) throws ReflectiveOperationException {
    if (receiver == null) return null;
    for (Class<?> type = receiver.getClass(); type != null; type = type.getSuperclass()) {
      try {
        Field member = type.getDeclaredField(name);
        member.setAccessible(true);
        return member.get(receiver);
      } catch (NoSuchFieldException ignored) { }
    }
    throw new NoSuchFieldException(receiver.getClass().getName() + "." + name);
  }

  private static Object invoke(Object receiver, String name) throws ReflectiveOperationException {
    if (receiver == null) return null;
    for (Class<?> type = receiver.getClass(); type != null; type = type.getSuperclass()) {
      try {
        Method method = type.getDeclaredMethod(name);
        method.setAccessible(true);
        return method.invoke(receiver);
      } catch (NoSuchMethodException ignored) { }
    }
    throw new NoSuchMethodException(receiver.getClass().getName() + "." + name);
  }

  public static final class RpcScope implements AutoCloseable {
    private final Probe.NodeScope node;
    private final Probe.ContextScope request;
    private boolean closed;
    private RpcScope(Probe.NodeScope node, Probe.ContextScope request) {
      this.node = node;
      this.request = request;
    }
    @Override public void close() {
      if (closed) return;
      closed = true;
      request.close();
      node.close();
    }
  }

  public static final class ActorScope implements AutoCloseable {
    private final Object previous;
    private final Probe.NodeScope node;
    private ActorScope(Object previous, Probe.NodeScope node) {
      this.previous = previous;
      this.node = node;
    }
    @Override public void close() {
      if (previous == null) ACTOR_DATANODE.remove();
      else ACTOR_DATANODE.set(previous);
      node.close();
    }
  }

  public static final class ImageSaverScope implements AutoCloseable {
    private final Probe.NodeScope node;
    private final Probe.ContextScope task;
    private boolean closed;
    private ImageSaverScope(Probe.NodeScope node, Probe.ContextScope task) {
      this.node = node;
      this.task = task;
    }
    @Override public void close() {
      if (closed) return;
      closed = true;
      task.close();
      node.close();
    }
  }

  public static final class BalancerTaskScope implements AutoCloseable {
    private final Probe.NodeScope node;
    private final Probe.ContextScope task;
    private boolean closed;
    private BalancerTaskScope(Probe.NodeScope node, Probe.ContextScope task) {
      this.node = node;
      this.task = task;
    }
    @Override public void close() {
      if (closed) return;
      closed = true;
      if (task != null) task.close();
      node.close();
    }
  }

  public static final class ClientOperationScope implements AutoCloseable {
    private final Probe.NodeScope node;
    private boolean closed;
    private ClientOperationScope(Probe.NodeScope node) { this.node = node; }
    @Override public void close() {
      if (closed) return;
      closed = true;
      Probe.regionExit("org.apache.hadoop.hdfs.DFSInputStream#blockSeekTo");
      node.close();
    }
  }
}
