package org.apache.hadoop.ipc;

import edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors;

import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.ArrayDeque;
import java.util.Collections;
import java.util.Deque;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * Hadoop 3.4.3 MiniDFSCluster transport adapter for Mallory's GraphChecker
 * runtime. This adapter deliberately does not infer a message edge from time,
 * peer address, or a shared thread name. A pair is keyed by the actual Hadoop
 * client ID, call ID, retry count, and message half.
 *
 * <p>This is an embedded, one-JVM adapter. A multi-JVM cluster must propagate
 * the trace header in the Hadoop IPC protocol instead of using these maps.</p>
 */
public final class MalloryEmbeddedIpcBridge {
  private static final String IPC = "HADOOP_IPC";
  private static final long HANDOFF_WAIT_SECONDS = 10;

  private static final Map<Object, ClientPending> CLIENT_PENDING =
      Collections.synchronizedMap(new IdentityHashMap<Object, ClientPending>());
  private static final ThreadLocal<Transfer> WRITING = new ThreadLocal<Transfer>();
  private static final ThreadLocal<MessageDoors.Inbound> SERVING =
      new ThreadLocal<MessageDoors.Inbound>();
  private static final ConcurrentHashMap<String, Transfer> REQUESTS =
      new ConcurrentHashMap<String, Transfer>();
  private static final ConcurrentHashMap<String, Transfer> RESPONSES =
      new ConcurrentHashMap<String, Transfer>();
  private static final Map<Object, Transfer> SENDING_RESPONSES =
      Collections.synchronizedMap(new IdentityHashMap<Object, Transfer>());
  private static final ConcurrentHashMap<String, Object> SERVER_SCOPES =
      new ConcurrentHashMap<String, Object>();

  private static final Map<Object, Boolean> REGISTERED =
      Collections.synchronizedMap(new IdentityHashMap<Object, Boolean>());
  private static final Map<Object, String> NODE_IDS =
      Collections.synchronizedMap(new IdentityHashMap<Object, String>());
  private static final Map<Object, Object> JOURNAL_IPC_SERVERS =
      Collections.synchronizedMap(new IdentityHashMap<Object, Object>());
  private static final ConcurrentHashMap<String, Object> ACTORS =
      new ConcurrentHashMap<String, Object>();
  private static final ConcurrentHashMap<String, Long> EPOCHS =
      new ConcurrentHashMap<String, Long>();
  private static final ThreadLocal<String> CONSTRUCTING_DN =
      new ThreadLocal<String>();
  private static final ThreadLocal<Long> INITIAL_BP_TICK =
      new ThreadLocal<Long>();
  private static final Map<Object, Object> BP_ACTOR_SCOPES =
      Collections.synchronizedMap(new IdentityHashMap<Object, Object>());
  private static final ThreadLocal<Long> BP_ACTOR_RUN =
      new ThreadLocal<Long>();
  private static final ThreadLocal<Deque<AdminRequest>> ADMIN_REQUESTS =
      new ThreadLocal<Deque<AdminRequest>>() {
        @Override protected Deque<AdminRequest> initialValue() {
          return new ArrayDeque<AdminRequest>();
        }
      };

  private MalloryEmbeddedIpcBridge() { }

  /** Called after each successful MiniDFSCluster.waitActive, including restart. */
  public static void registerCluster(Object cluster) {
    try {
      List<?> dataNodes = (List<?>) invoke(cluster, "getDataNodes");
      for (int i = 0; i < dataNodes.size(); i++) {
        Object node = dataNodes.get(i);
        if (node == null) continue;
        registerDataNodeAt(node, i);
      }
      int names = ((Number) invoke(cluster, "getNumNameNodes")).intValue();
      for (int i = 0; i < names; i++) {
        Object node = invoke(cluster, "getNameNode", int.class, i);
        if (node == null) continue;
        registerNameNodeAt(node, i);
      }
    } catch (ReflectiveOperationException failure) {
      throw new IllegalStateException("MiniDFSCluster source registration failed", failure);
    }
  }

  /** Bind every embedded JournalNode to the Hadoop IPC server that serves it. */
  public static void registerJournalCluster(Object cluster) {
    try {
      int count = ((Number) invoke(cluster, "getNumNodes")).intValue();
      for (int index = 0; index < count; index++) {
        Object node = invoke(cluster, "getJournalNode", int.class, index);
        if (node != null) registerJournalNodeAt(node, index, false);
      }
    } catch (ReflectiveOperationException failure) {
      throw new IllegalStateException("MiniJournalCluster source registration failed", failure);
    }
  }

  /** Called after restartJournalNode succeeds, including a same-object restart. */
  public static void registerJournalRestart(Object cluster, int index) {
    try {
      Object node = invoke(cluster, "getJournalNode", int.class, index);
      if (node == null) throw new IllegalStateException("restarted JournalNode is null");
      registerJournalNodeAt(node, index, true);
    } catch (ReflectiveOperationException failure) {
      throw new IllegalStateException("JournalNode restart registration failed", failure);
    }
  }

  /** Carry the submitting request across QJM's per-JournalNode executor. */
  public static <T> Callable<T> wrapJournalCallable(final Callable<T> task) {
    final Object scope = MessageDoors.captureScope();
    return new Callable<T>() {
      @Override public T call() throws Exception {
        long carried = MessageDoors.enterCarriedScope(scope, "CLIENT",
            "IPCLoggerChannel.submit(Callable)");
        try { return task.call(); }
        finally { MessageDoors.exitCarriedScope(carried); }
      }
    };
  }

  /** Also carry the scope through QJM's Runnable executor handoffs. */
  public static Runnable wrapJournalRunnable(final Runnable task) {
    final Object scope = MessageDoors.captureScope();
    return new Runnable() {
      @Override public void run() {
        long carried = MessageDoors.enterCarriedScope(scope, "CLIENT",
            "IPCLoggerChannel.submit(Runnable)");
        try { task.run(); }
        finally { MessageDoors.exitCarriedScope(carried); }
      }
    };
  }

  /** Run immediately after NameNode.createNameNode returns, before DNs start. */
  public static void registerEarlyNameNode(Object cluster, Object nameNode) {
    try {
      int index = ((Number) invoke(cluster, "getNumNameNodes")).intValue();
      registerNameNodeAt(nameNode, index);
    } catch (ReflectiveOperationException failure) {
      throw new IllegalStateException("early NameNode registration failed", failure);
    }
  }

  /** Run before a newly instantiated DataNode launches its daemon threads. */
  public static void registerEarlyDataNode(Object cluster, Object dataNode) {
    try {
      int index = ((List<?>) invoke(cluster, "getDataNodes")).size();
      registerDataNodeAt(dataNode, index);
    } catch (ReflectiveOperationException failure) {
      throw new IllegalStateException("early DataNode registration failed", failure);
    }
  }

  /** Construction identity crosses the MiniDFSCluster -> DataNode call. */
  public static void beginConstructInitialDataNode(Object cluster) {
    try {
      int index = ((List<?>) invoke(cluster, "getDataNodes")).size();
      CONSTRUCTING_DN.set("dn" + index);
    } catch (ReflectiveOperationException failure) {
      throw new IllegalStateException("initial DataNode identity failed", failure);
    }
  }

  /** Reuse the logical source ID of the exact DataNodeProperties being restarted. */
  public static void beginConstructRestartDataNode(Object properties) {
    Object oldNode = field(properties, "datanode");
    String id = NODE_IDS.get(oldNode);
    if (id == null) {
      MessageDoors.gap("MISSING_DN_RESTART_IDENTITY", "DataNode.restart",
          "old DataNode was not registered; new epoch cannot be assigned");
      CONSTRUCTING_DN.remove();
    } else {
      CONSTRUCTING_DN.set(id);
    }
  }

  public static void endConstructDataNode() { CONSTRUCTING_DN.remove(); }

  /** Called after initIpcServer and before block-pool actors launch. */
  public static long beforeInitialBpRefresh(Object dataNode) {
    String id = CONSTRUCTING_DN.get();
    if (id == null) {
      MessageDoors.gap("MISSING_DN_CONSTRUCTION_SCOPE", "DataNode.startDataNode",
          "no MiniDFSCluster construction identity");
      return 0L;
    }
    register(dataNode, "HDFS", "DATANODE", id);
    alias(field(dataNode, "ipcServer"), dataNode);
    long tick = MessageDoors.beginTick(dataNode, "DataNode.startDataNode");
    INITIAL_BP_TICK.set(tick);
    return tick;
  }

  public static void afterInitialBpRefresh(long tick) {
    MessageDoors.endTick(tick);
    INITIAL_BP_TICK.remove();
  }

  /** Capture the exact parent scope when BPServiceActor's thread starts. */
  public static void bpActorStarting(Object actor, Object dataNode) {
    if (!REGISTERED.containsKey(dataNode)) {
      MessageDoors.gap("MISSING_BP_ACTOR_SOURCE", "BPServiceActor.start",
          "owning DataNode is not registered");
      return;
    }
    if (INITIAL_BP_TICK.get() == null) {
      // A later start has a known DataNode but no proven construction scope.
      // Give it its own named daemon root; do not claim a parent task edge.
      MessageDoors.gap("BP_ACTOR_PARENT_UNPROVEN", "BPServiceActor.start",
          "no carried DataNode construction scope");
      long tick = MessageDoors.beginTick(dataNode, "BPServiceActor.start");
      try { BP_ACTOR_SCOPES.put(actor, MessageDoors.captureScope()); }
      finally { MessageDoors.endTick(tick); }
      return;
    }
    BP_ACTOR_SCOPES.put(actor, MessageDoors.captureScope());
  }

  public static void bpActorRun(Object actor) {
    Object scope = BP_ACTOR_SCOPES.remove(actor);
    long token = MessageDoors.enterCarriedScope(scope, "DATANODE",
        "BPServiceActor.run");
    BP_ACTOR_RUN.set(token);
  }

  public static void bpActorStartFailed(Object actor) {
    BP_ACTOR_SCOPES.remove(actor);
    MessageDoors.gap("BP_ACTOR_START_FAILED", "BPServiceActor.start",
        "thread start failed; captured scope discarded");
  }

  public static void bpActorExit() {
    Long token = BP_ACTOR_RUN.get();
    BP_ACTOR_RUN.remove();
    if (token != null) MessageDoors.exitCarriedScope(token);
  }

  private static void registerDataNodeAt(Object node, int index) {
    register(node, "HDFS", "DATANODE", "dn" + index);
    // The server may be initialized after the node object. Retrying the alias
    // at waitActive is intentional; duplicate aliases with the same source are
    // accepted by MessageDoors.
    alias(field(node, "ipcServer"), node);
  }

  private static void registerNameNodeAt(Object node, int index)
      throws ReflectiveOperationException {
    register(node, "HDFS", "NAMENODE", "nn" + index);
    Object rpc = invoke(node, "getRpcServer");
    alias(rpc, node);
    for (String member : new String[] {
        "clientRpcServer", "serviceRpcServer", "lifelineRpcServer"}) {
      alias(field(rpc, member), node);
    }
  }

  private static void registerJournalNodeAt(Object node, int index,
                                            boolean explicitRestart)
      throws ReflectiveOperationException {
    Object rpc = invoke(node, "getRpcServer");
    Object server = field(rpc, "server");
    if (rpc == null || server == null) {
      throw new IllegalStateException("JournalNode has no live IPC server");
    }
    String id = "jn" + index;
    synchronized (REGISTERED) {
      String previousId = NODE_IDS.get(node);
      if (previousId != null && !previousId.equals(id)) {
        throw new IllegalStateException("JournalNode index changed: " + previousId);
      }
      Object previousServer = JOURNAL_IPC_SERVERS.get(node);
      if (previousServer == null) {
        if (!register(node, "HDFS", "JOURNALNODE", id)) {
          throw new IllegalStateException("JournalNode source already registered");
        }
      } else if (explicitRestart || previousServer != server) {
        long epoch = EPOCHS.get(id) + 1L;
        MessageDoors.restartSource(node, "HDFS", "JOURNALNODE", id, epoch);
        EPOCHS.put(id, epoch);
      }
      JOURNAL_IPC_SERVERS.put(node, server);
      alias(rpc, node);
      alias(server, node);
    }
  }

  private static boolean register(Object anchor, String kind, String role,
                                  String id) {
    synchronized (REGISTERED) {
      if (REGISTERED.containsKey(anchor)) return false;
      Object previous = ACTORS.put(id, anchor);
      long epoch = previous == null ? 0L : EPOCHS.get(id) + 1L;
      EPOCHS.put(id, epoch);
      MessageDoors.registerSource(anchor, kind, role, id, epoch);
      REGISTERED.put(anchor, Boolean.TRUE);
      NODE_IDS.put(anchor, id);
      return true;
    }
  }

  private static void alias(Object value, Object source) {
    if (value != null) MessageDoors.registerSourceAlias(value, source);
  }

  /** Each original DFSAdmin command has a distinct root and force argument. */
  public static void beginAdmin(Object admin, String[] argv, int index) {
    synchronized (REGISTERED) {
      if (!REGISTERED.containsKey(admin)) {
        MessageDoors.registerSource(admin, "EXTERNAL_APP", "CLIENT", "dfsadmin", 0L);
        REGISTERED.put(admin, Boolean.TRUE);
      }
    }
    boolean force = argv != null && index + 2 < argv.length
        && "force".equals(argv[index + 2]);
    String api = "DFSAdmin.deleteBlockPool(force=" + force + ")";
    ADMIN_REQUESTS.get().push(new AdminRequest(
        MessageDoors.beginRequest(admin, api), api));
  }

  public static void endAdmin() {
    Deque<AdminRequest> requests = ADMIN_REQUESTS.get();
    if (requests.isEmpty()) return;
    AdminRequest request = requests.pop();
    MessageDoors.endRequest(request.id, request.api);
    if (requests.isEmpty()) ADMIN_REQUESTS.remove();
  }

  /** Captures the caller's scope before it offers a Pair to the sender. */
  public static void clientPrepare(Object call, Object connection) {
    // The Call belongs to one client operation. The Connection can be reused
    // by later roots, so bind the response recipient to this exact Call.
    MessageDoors.registerCurrentSourceAlias(call);
    CLIENT_PENDING.put(call, new ClientPending(connection,
        MessageDoors.captureScope()));
  }

  /** Only a true SynchronousQueue.offer counts as accepted. */
  public static void clientQueueAccepted(Object pair) {
    Object call = left(pair);
    synchronized (CLIENT_PENDING) {
      ClientPending pending = CLIENT_PENDING.get(call);
      if (pending != null) pending.accepted = true;
    }
  }

  /** Drops calls closed or interrupted before any queue handoff. */
  public static void clientQueueAttemptDone(Object call) {
    synchronized (CLIENT_PENDING) {
      ClientPending pending = CLIENT_PENDING.get(call);
      if (pending != null && !pending.accepted) CLIENT_PENDING.remove(call);
    }
  }

  /**
   * Runs in RpcRequestSender after a successful poll, before sendRequest.
   * Preparing carries the caller's scope but emits no SEND yet.
   */
  public static void clientDequeued(Object pair) {
    if (pair == null) return;
    Object rawCall = left(pair);
    ClientPending pending = CLIENT_PENDING.remove(rawCall);
    if (pending == null) {
      MessageDoors.gap("MISSING_IPC_SCOPE", IPC,
          "sender dequeued a call with no caller scope");
      return;
    }
    Client.Call call = (Client.Call) rawCall;
    byte[] clientId = (byte[]) field(field(pending.connection, "this$0"),
        "clientId");
    String correlation = correlation(clientId, call.id);
    String attempt = Integer.toString(call.retry);
    // The physical Connection can be reused by later request roots. The
    // exact Call is aliased to its caller in clientPrepare, so it names the
    // producer without assigning one mutable source to the Connection.
    MessageDoors.Outbound outbound = MessageDoors.prepareOutbound(IPC,
        correlation, attempt, MessageDoors.REQUEST, rawCall, pending.scope);
    Transfer transfer = new Transfer(outbound);
    WRITING.set(transfer);
    if (outbound.active()) REQUESTS.put(key(correlation, attempt), transfer);
  }

  /** Called only after IpcStreams.sendRequest returned successfully. */
  public static void clientSent() {
    Transfer transfer = WRITING.get();
    WRITING.remove();
    if (transfer == null) return;
    MessageDoors.sent(transfer.outbound);
    transfer.complete(true);
  }

  public static void clientSendFailed(IOException error) {
    Transfer transfer = WRITING.get();
    WRITING.remove();
    if (transfer != null) {
      transfer.complete(false);
      REQUESTS.remove(key(transfer.outbound.correlationId,
          transfer.outbound.attemptId), transfer);
    }
  }

  /** Runs immediately before Server.call, after RpcCall's closed-channel gate. */
  public static void serverEnter(Object rawCall, Object server) {
    Server.Call call = (Server.Call) rawCall;
    String correlation = correlation(call.clientId, call.callId);
    String attempt = Integer.toString(call.retryCount);
    String key = key(correlation, attempt);
    Transfer transfer = REQUESTS.remove(key);
    if (transfer == null) {
      MessageDoors.gap("UNMATCHED_IPC_REQUEST", key,
          "no exact in-JVM client transfer; no request edge installed");
      return;
    }
    if (!transfer.awaitSent(key)) return;
    MessageDoors.Inbound inbound = MessageDoors.inbound(
        transfer.outbound.trace, transfer.outbound.symbolic, IPC,
        correlation, attempt, MessageDoors.REQUEST, server, false);
    SERVING.set(inbound);
    SERVER_SCOPES.put(key, MessageDoors.captureScope());
  }

  public static void serverExit() {
    MessageDoors.Inbound inbound = SERVING.get();
    SERVING.remove();
    if (inbound != null) MessageDoors.endInbound(inbound);
  }

  /** Prepares the response before Responder.doRespond can hand it off. */
  public static void serverResponsePrepare(Object rawCall) {
    Server.Call call = (Server.Call) rawCall;
    String correlation = correlation(call.clientId, call.callId);
    String attempt = Integer.toString(call.retryCount);
    String key = key(correlation, attempt);
    Object server = invokeUnchecked(field(rawCall, "connection"), "getServer");
    Object scope = SERVER_SCOPES.get(key);
    if (scope == null) {
      MessageDoors.gap("MISSING_IPC_RESPONSE_SCOPE", key,
          "response has no exact serviced request scope");
      return;
    }
    MessageDoors.Outbound outbound = MessageDoors.prepareOutbound(IPC,
        correlation, attempt, MessageDoors.RESPONSE, server, scope);
    Transfer transfer = new Transfer(outbound);
    SENDING_RESPONSES.put(rawCall, transfer);
    if (outbound.active()) RESPONSES.put(key, transfer);
  }

  /** A successful Responder.doRespond is the server's response handoff. */
  public static void serverResponseSent(Object rawCall) {
    Transfer transfer = SENDING_RESPONSES.remove(rawCall);
    if (transfer == null) return;
    MessageDoors.sent(transfer.outbound);
    transfer.complete(true);
    Server.Call call = (Server.Call) rawCall;
    SERVER_SCOPES.remove(key(correlation(call.clientId, call.callId),
        Integer.toString(call.retryCount)));
  }

  public static void serverResponseFailed(Object rawCall, IOException error) {
    Transfer transfer = SENDING_RESPONSES.remove(rawCall);
    if (transfer != null) {
      transfer.complete(false);
      String identity = key(transfer.outbound.correlationId,
          transfer.outbound.attemptId);
      RESPONSES.remove(identity, transfer);
      SERVER_SCOPES.remove(identity);
    }
  }

  /** Leaves the response scope active through the caller's next target check. */
  public static void clientResponseConsumed(Object rawCall, Object connection,
                                            Object response) {
    if (response != null) receiveResponse(rawCall, connection);
  }

  /** Only a completed Hadoop RemoteException is a received error response. */
  public static void clientErrorConsumed(Object rawCall, Object connection,
                                         IOException error) {
    Client.Call call = (Client.Call) rawCall;
    if (call.done && call.error == error && error instanceof RemoteException) {
      receiveResponse(rawCall, connection);
    }
  }

  private static void receiveResponse(Object rawCall, Object connection) {
    Client.Call call = (Client.Call) rawCall;
    byte[] clientId = (byte[]) field(field(connection, "this$0"), "clientId");
    String correlation = correlation(clientId, call.id);
    String attempt = Integer.toString(call.retry);
    String key = key(correlation, attempt);
    Transfer transfer = RESPONSES.remove(key);
    if (transfer == null) {
      MessageDoors.gap("UNMATCHED_IPC_RESPONSE", key,
          "completed client call has no exact server response handoff");
      return;
    }
    if (!transfer.awaitSent(key)) return;
    MessageDoors.inbound(transfer.outbound.trace, transfer.outbound.symbolic,
        IPC, correlation, attempt, MessageDoors.RESPONSE, rawCall, false);
  }

  private static String key(String correlation, String attempt) {
    return correlation + "/" + attempt;
  }

  private static String correlation(byte[] clientId, int callId) {
    StringBuilder result = new StringBuilder("hadoop-ipc-");
    if (clientId == null) throw new IllegalArgumentException("missing client ID");
    for (byte b : clientId) {
      result.append(Character.forDigit((b >>> 4) & 15, 16));
      result.append(Character.forDigit(b & 15, 16));
    }
    return result.append('-').append(callId).toString();
  }

  private static Object left(Object pair) {
    return invokeUnchecked(pair, "getLeft");
  }

  private static Object invokeUnchecked(Object object, String name) {
    try { return invoke(object, name); }
    catch (ReflectiveOperationException failure) {
      throw new IllegalStateException("cannot invoke " + name, failure);
    }
  }

  private static Object invoke(Object object, String name)
      throws ReflectiveOperationException {
    Method method = object.getClass().getMethod(name);
    method.setAccessible(true);
    return method.invoke(object);
  }

  private static Object invoke(Object object, String name,
                               Class<?> argType, Object arg)
      throws ReflectiveOperationException {
    Method method = object.getClass().getMethod(name, argType);
    method.setAccessible(true);
    return method.invoke(object, arg);
  }

  private static Object field(Object object, String name) {
    if (object == null) return null;
    Class<?> type = object.getClass();
    while (type != null) {
      try {
        Field field = type.getDeclaredField(name);
        field.setAccessible(true);
        return field.get(object);
      } catch (NoSuchFieldException missing) {
        type = type.getSuperclass();
      } catch (ReflectiveOperationException failure) {
        throw new IllegalStateException("cannot read " + name, failure);
      }
    }
    return null;
  }

  private static final class ClientPending {
    final Object connection;
    final Object scope;
    boolean accepted;
    ClientPending(Object connection, Object scope) {
      this.connection = connection;
      this.scope = scope;
    }
  }

  private static final class AdminRequest {
    final long id;
    final String api;
    AdminRequest(long id, String api) { this.id = id; this.api = api; }
  }

  private static final class Transfer {
    final MessageDoors.Outbound outbound;
    final CountDownLatch handoff = new CountDownLatch(1);
    volatile boolean sent;
    Transfer(MessageDoors.Outbound outbound) { this.outbound = outbound; }
    void complete(boolean success) {
      sent = success;
      handoff.countDown();
    }
    boolean awaitSent(String subject) {
      try {
        if (handoff.await(HANDOFF_WAIT_SECONDS, TimeUnit.SECONDS) && sent)
          return true;
        MessageDoors.gap("IPC_HANDOFF_UNCONFIRMED", subject,
            "request or response reached consumer without confirmed send");
      } catch (InterruptedException interrupted) {
        Thread.currentThread().interrupt();
        MessageDoors.gap("IPC_HANDOFF_INTERRUPTED", subject,
            "interrupted while waiting for exact send confirmation");
      }
      return false;
    }
  }
}
