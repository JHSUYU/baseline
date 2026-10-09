package edu.uva.liftlab.mallory.hbase;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Deque;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.WeakHashMap;
import java.util.concurrent.Callable;

/** HBase 2.6.x MiniCluster handoffs. No HBase implementation class is linked at compile time. */
public final class HBaseHooks {
  private static final String ATTRIBUTE = "mallory.causal.context.v1";
  private static final Map<Object, CallToken> CALL_TOKENS =
      Collections.synchronizedMap(new WeakHashMap<Object, CallToken>());
  private static final Map<Object, String> SERVER_NODES =
      Collections.synchronizedMap(new WeakHashMap<Object, String>());
  private static final Map<Object, Object> PROCEDURE_SCHEDULER_OWNERS =
      Collections.synchronizedMap(new WeakHashMap<Object, Object>());
  /** Tokens are attached to queue entries, not to the reusable Procedure instance. */
  private static final Map<Object, IdentityHashMap<Object, Deque<String>>> PROCEDURE_ATTEMPTS =
      Collections.synchronizedMap(new WeakHashMap<Object, IdentityHashMap<Object, Deque<String>>>());
  private static final ThreadLocal<PolledProcedure> POLLED_PROCEDURE =
      new ThreadLocal<PolledProcedure>();
  private static final Map<Object, ScannerTokens> SCANNER_TOKENS =
      Collections.synchronizedMap(new WeakHashMap<Object, ScannerTokens>());
  private static final ThreadLocal<Deque<List<CallToken>>> BLOCKING_CALLS =
      new ThreadLocal<Deque<List<CallToken>>>() {
        @Override protected Deque<List<CallToken>> initialValue() {
          return new ArrayDeque<List<CallToken>>();
        }
      };

  private HBaseHooks() { }

  /** Only an explicitly returned HBaseTestingUtility connection is labelled as the test client. */
  public static void registerClient(Object connection) {
    if (connection != null) Probe.registerNode(connection, "client", 0);
  }

  public static Scope enterClientConnection(Object connection) {
    return new Scope(null, Probe.withRegisteredNode(connection));
  }

  /** The MiniCluster has completed startup; its thread wrappers expose real master/RS objects. */
  public static void registerCluster(Object cluster) {
    registerThreads(cluster, "getMasterThreads", "getMaster", "master");
    registerThreads(cluster, "getRegionServerThreads", "getRegionServer", "rs");
  }

  /** MiniCluster's constructor index is stable before the server thread starts. */
  public static void registerRegionServer(Object server, int index) {
    registerServerAndWatcher(server, "rs" + index);
  }

  public static void registerMaster(Object server, int index) {
    registerServerAndWatcher(server, "master" + index);
  }

  /** Restores that explicit actor on the server's own startup/run thread. */
  public static Scope enterMiniClusterActor(Object server) {
    registerWatcherForServer(server);
    return new Scope(null, Probe.withRegisteredNode(server));
  }

  private static void registerThreads(Object cluster, String listMethod, String serverMethod,
                                      String role) {
    try {
      Object threads = invoke(cluster, listMethod);
      if (!(threads instanceof Iterable<?>)) return;
      int index = 0;
      for (Object thread : (Iterable<?>) threads) {
        Object server = invoke(thread, serverMethod);
        registerServerAndWatcher(server, role + index);
        index++;
      }
    } catch (ReflectiveOperationException ignored) {
      // An unsupported MiniCluster variant remains explicitly unattributed.
    }
  }

  /** Bind the watcher's owner from the explicit MiniCluster server index. */
  private static void registerServerAndWatcher(Object server, String node) {
    if (server == null) return;
    SERVER_NODES.put(server, node);
    Probe.registerNode(server, node, 0);
    registerWatcherForServer(server);
  }

  private static void registerWatcherForServer(Object server) {
    String node = SERVER_NODES.get(server);
    if (node == null) return;
    try {
      Object watcher = invoke(server, "getZooKeeper");
      if (watcher != null) Probe.registerNode(watcher, node, 0);
    } catch (ReflectiveOperationException ignored) {
      // A watcher absent during early startup remains unattributed until cluster registration.
    }
  }

  /** Static tracker reads use the ZKWatcher passed by their owning server. */
  public static Scope enterZkWatcher(Object watcher) {
    return new Scope(null, Probe.withRegisteredNode(watcher));
  }

  /** Runs in the thread creating an HBase RPC Call, before its Netty handoff. */
  public static void clientCallCreated(Object call) {
    if (call == null) return;
    String token = Probe.newTaskToken();
    CallToken marker = new CallToken(token, Probe.newTaskToken());
    CALL_TOKENS.put(call, marker);
    Deque<List<CallToken>> pending = BLOCKING_CALLS.get();
    if (!pending.isEmpty()) pending.peek().add(marker);
    try { Probe.registerCurrentNode(call); }
    catch (IllegalStateException unbound) { /* source actor remains unknown */ }
    // This event is request intent. Only a matching receiver proves transport delivery.
    Probe.send("hbase-rpc", token, methodName(call), "hbase:Call.<init>");
  }

  /**
   * Adds a scoped causal attribute through HBase's existing RequestHeader attribute mechanism.
   * This executes for both blocking and Netty clients. The original header is returned if an
   * unsupported HBase version changes the protobuf API; that run then has no paired SEND edge.
   */
  public static Object decorateHeader(Object header, Object call) {
    CallToken marker = CALL_TOKENS.get(call);
    if (header == null || marker == null) return header;
    try {
      Object builder = invoke(header, "toBuilder");
      ClassLoader loader = header.getClass().getClassLoader();
      Class<?> pairClass = Class.forName(
          "org.apache.hadoop.hbase.shaded.protobuf.generated.HBaseProtos$NameBytesPair",
          false, loader);
      Object pairBuilder = pairClass.getMethod("newBuilder").invoke(null);
      pairBuilder.getClass().getMethod("setName", String.class).invoke(pairBuilder, ATTRIBUTE);
      Method setValue = findOneArg(pairBuilder.getClass(), "setValue");
      Object bytes = setValue.getParameterTypes()[0].getMethod("copyFrom", byte[].class)
          .invoke(null, marker.token.getBytes(StandardCharsets.UTF_8));
      setValue.invoke(pairBuilder, bytes);
      Object pair = invoke(pairBuilder, "build");
      builder.getClass().getMethod("addAttribute", pairClass).invoke(builder, pair);
      Object updated = invoke(builder, "build");
      return updated;
    } catch (ReflectiveOperationException | LinkageError | RuntimeException ignored) {
      return header;
    }
  }

  /** Request receiver scope; the token was read from the actual transported request header. */
  public static Scope enterServerCall(Object rpcServer, Object rpcCall) {
    Object server = null;
    try { server = field(rpcServer, "server"); }
    catch (ReflectiveOperationException ignored) { }
    Probe.NodeScope node = Probe.withRegisteredNode(server);
    Probe.ContextScope context = null;
    String responseToken = null;
    String port = methodName(rpcCall);
    try {
      byte[] payload = (byte[]) rpcCall.getClass()
          .getMethod("getRequestAttribute", String.class).invoke(rpcCall, ATTRIBUTE);
      if (payload != null && payload.length > 0) {
        String token = new String(payload, StandardCharsets.UTF_8);
        responseToken = token;
        context = Probe.receiveScope("hbase-rpc", token, methodName(rpcCall),
            "hbase:RpcServer.call");
      }
    } catch (ReflectiveOperationException | RuntimeException ignored) {
      // The service still runs under an explicit node scope; no invented RPC edge is emitted.
    }
    return new Scope(context, node, responseToken, port);
  }

  /** A parsed response for a known Call, before the response is delivered to its callback. */
  public static void clientResponse(Object call) {
    if (call == null) return;
    CallToken marker = CALL_TOKENS.get(call);
    if (marker == null) return;
    try (Probe.NodeScope node = Probe.withRegisteredNode(call);
         Probe.ContextScope context = Probe.withCausalContext(marker.token)) {
      Probe.receive("hbase-rpc-response", marker.token, methodName(call),
          "hbase:RpcConnection.readResponse");
      marker.responseObserved = true;
      Probe.taskSubmit(marker.completionToken, "hbase:RpcConnection.response-ready");
    }
  }

  /**
   * Wrap the accepted coordinator submission itself. This is invoked only after
   * ProcedureCoordinator's putIfAbsent accepted this Procedure, at the actual
   * ExecutorService.submit call site. The wrapper carries a fresh token into
   * Procedure.call on the pool worker; no thread name or procedure name is used
   * as a causal key. A rejected submission has no worker claim and no graph edge.
   */
  public static Callable<?> coordinatorCallable(Object coordinator, Callable<?> procedure) {
    if (procedure == null) return null;
    Object rpcs = null;
    try { rpcs = field(coordinator, "rpcs"); }
    catch (ReflectiveOperationException ignored) { }
    Probe.NodeScope owner = "unknown".equals(Probe.currentNode())
        ? Probe.withRegisteredNode(rpcs) : null;
    try {
      return Probe.wrapCallable(procedure, "hbase:ProcedureCoordinator.submitProcedure");
    } finally {
      if (owner != null) owner.close();
    }
  }

  /** Capture exactly the Calls created by one synchronous RPC invocation. */
  public static Scope enterBlockingCall(Object ignoredClient) {
    List<CallToken> pending = new ArrayList<CallToken>();
    BLOCKING_CALLS.get().push(pending);
    return new Scope(null, null, null, null, pending);
  }

  /** Binds the scheduler to the real MiniCluster master supplied by MasterProcedureEnv. */
  public static void registerProcedureScheduler(Object environment) {
    try {
      Object scheduler = invoke(environment, "getProcedureScheduler");
      Object master = invoke(environment, "getMasterServices");
      if (scheduler != null && master != null) PROCEDURE_SCHEDULER_OWNERS.put(scheduler, master);
    } catch (ReflectiveOperationException ignored) {
      // A foreign ProcedureScheduler has no proven master actor.
    }
  }

  /** Called after AbstractProcedureScheduler.enqueue, while its scheduler lock is held. */
  public static void procedureEnqueued(Object scheduler, Object procedure, boolean front) {
    Object owner = PROCEDURE_SCHEDULER_OWNERS.get(scheduler);
    if (owner == null || procedure == null) return;
    try (Probe.NodeScope node = Probe.withRegisteredNode(owner)) {
      if ("unknown".equals(Probe.currentNode())) return;
      String token = Probe.newTaskToken();
      synchronized (PROCEDURE_ATTEMPTS) {
        IdentityHashMap<Object, Deque<String>> byProcedure = PROCEDURE_ATTEMPTS.get(scheduler);
        if (byProcedure == null) {
          byProcedure = new IdentityHashMap<Object, Deque<String>>();
          PROCEDURE_ATTEMPTS.put(scheduler, byProcedure);
        }
        Deque<String> attempts = byProcedure.get(procedure);
        if (attempts == null) {
          attempts = new ArrayDeque<String>();
          byProcedure.put(procedure, attempts);
        }
        if (front) attempts.addFirst(token); else attempts.addLast(token);
      }
      Probe.taskSubmit(token, "hbase:AbstractProcedureScheduler.push");
    }
  }

  /** Consumes the token for the exact dequeued queue entry on this worker thread. */
  public static void procedurePolled(Object scheduler, Object procedure) {
    POLLED_PROCEDURE.remove();
    if (procedure == null) return;
    String token = null;
    synchronized (PROCEDURE_ATTEMPTS) {
      IdentityHashMap<Object, Deque<String>> byProcedure = PROCEDURE_ATTEMPTS.get(scheduler);
      if (byProcedure != null) {
        Deque<String> attempts = byProcedure.get(procedure);
        if (attempts != null) {
          token = attempts.pollFirst();
          if (attempts.isEmpty()) byProcedure.remove(procedure);
        }
      }
    }
    if (token != null) POLLED_PROCEDURE.set(new PolledProcedure(procedure, token));
  }

  /** Queue clear invalidates any attempts that can no longer reach a worker. */
  public static void procedureQueueCleared(Object scheduler) {
    synchronized (PROCEDURE_ATTEMPTS) { PROCEDURE_ATTEMPTS.remove(scheduler); }
  }

  /** Pair the actual QueueingFuture instance across executor.execute and run(). */
  public static void scannerTaskSubmitted(Object future) {
    if (future == null) return;
    try {
      Probe.registerCurrentNode(future);
    } catch (IllegalStateException unbound) {
      // Startup and daemon tasks have no established actor; do not invent an edge.
      return;
    }
    ScannerTokens tokens = new ScannerTokens(Probe.newTaskToken(), Probe.newTaskToken());
    SCANNER_TOKENS.put(future, tokens);
    Probe.taskSubmit(tokens.input, "hbase:ResultBoundedCompletionService.submit");
  }

  public static Scope enterScannerTask(Object future) {
    Probe.NodeScope node = Probe.withRegisteredNode(future);
    ScannerTokens tokens = SCANNER_TOKENS.get(future);
    Probe.ContextScope context = tokens == null ? null :
        Probe.taskClaim(tokens.input, "hbase:QueueingFuture.run");
    return new Scope(context, node);
  }

  /** The result is published immediately before QueueingFuture notifies its waiter. */
  public static void scannerTaskCompleted(Object future) {
    ScannerTokens tokens = SCANNER_TOKENS.get(future);
    if (tokens == null) return;
    synchronized (tokens) {
      if (tokens.resultPublished) return;
      tokens.resultPublished = true;
    }
    Probe.taskSubmit(tokens.result, "hbase:QueueingFuture.complete");
  }

  /** poll/take returned this exact future to the waiting scanner in the target occurrence. */
  public static void scannerResultReceived(Object future) {
    ScannerTokens tokens = SCANNER_TOKENS.get(future);
    if (tokens == null) return;
    synchronized (tokens) {
      if (!tokens.resultPublished || tokens.resultClaimed) return;
      tokens.resultClaimed = true;
    }
    try (Probe.ContextScope ignored = Probe.taskClaim(tokens.result,
        "hbase:ResultBoundedCompletionService.result")) { }
  }

  /** Restores the master actor and this one scheduler attempt on a worker thread. */
  public static Scope enterProcedure(Object executor, Object procedure) {
    Object owner = null;
    try {
      Object environment = invoke(executor, "getEnvironment");
      owner = invoke(environment, "getMasterServices");
    } catch (ReflectiveOperationException ignored) { }
    Probe.NodeScope node = Probe.withRegisteredNode(owner);
    PolledProcedure attempt = POLLED_PROCEDURE.get();
    POLLED_PROCEDURE.remove();
    Probe.ContextScope context = attempt == null || attempt.procedure != procedure
        || "unknown".equals(Probe.currentNode()) ? null :
        Probe.taskClaim(attempt.token, "hbase:ProcedureExecutor.executeProcedure");
    return new Scope(context, node);
  }

  private static final class PolledProcedure {
    final Object procedure;
    final String token;
    PolledProcedure(Object procedure, String token) {
      this.procedure = procedure;
      this.token = token;
    }
  }

  /** Selected master procedure checks can run in a constructor's caller before submission. */
  public static Scope enterMasterEnvironment(Object procedure, Object environment) {
    Object master = null;
    try { master = invoke(environment, "getMasterServices"); }
    catch (ReflectiveOperationException ignored) { }
    return new Scope(null, Probe.withRegisteredNode(master));
  }

  /** Test procedure members use separate ZooKeeper sessions and explicit member names. */
  public static void registerZkMember(Object controller, String memberName) {
    if (controller != null && memberName != null && !memberName.isEmpty())
      Probe.registerNode(controller, "zk-member:" + memberName, 0);
  }

  public static void registerZkCoordinator(Object controller, String coordinatorName) {
    if (controller != null && coordinatorName != null && !coordinatorName.isEmpty())
      Probe.registerNode(controller, "zk-coordinator:" + coordinatorName, 0);
  }

  public static Scope enterZkActor(Object controller) {
    return new Scope(null, Probe.withRegisteredNode(controller));
  }

  private static String methodName(Object object) {
    try {
      Object descriptor = invoke(object, "getMethod");
      return String.valueOf(invoke(descriptor, "getFullName"));
    } catch (ReflectiveOperationException ignored) {
      try {
        Object descriptor = field(object, "md");
        return String.valueOf(invoke(descriptor, "getFullName"));
      } catch (ReflectiveOperationException alsoIgnored) {
        return "unknown-method";
      }
    }
  }

  private static Object field(Object target, String name) throws ReflectiveOperationException {
    if (target == null) throw new NoSuchFieldException(name);
    for (Class<?> type = target.getClass(); type != null; type = type.getSuperclass()) {
      try {
        Field field = type.getDeclaredField(name);
        field.setAccessible(true);
        return field.get(target);
      } catch (NoSuchFieldException ignored) { }
    }
    throw new NoSuchFieldException(name);
  }

  private static Object invoke(Object target, String name) throws ReflectiveOperationException {
    if (target == null) throw new NoSuchMethodException(name);
    Method method = target.getClass().getMethod(name);
    method.setAccessible(true);
    return method.invoke(target);
  }

  private static Method findOneArg(Class<?> type, String name) throws NoSuchMethodException {
    for (Method method : type.getMethods())
      if (method.getName().equals(name) && method.getParameterTypes().length == 1) return method;
    throw new NoSuchMethodException(name);
  }

  private static final class CallToken {
    final String token;
    final String completionToken;
    volatile boolean responseObserved;
    CallToken(String token, String completionToken) {
      this.token = token;
      this.completionToken = completionToken;
    }
  }

  private static final class ScannerTokens {
    final String input;
    final String result;
    boolean resultPublished;
    boolean resultClaimed;
    ScannerTokens(String input, String result) { this.input = input; this.result = result; }
  }

  public static final class Scope implements AutoCloseable {
    private final Probe.ContextScope context;
    private final Probe.NodeScope node;
    private final String responseToken;
    private final String responsePort;
    private final List<CallToken> blockingCalls;
    private Scope(Probe.ContextScope context, Probe.NodeScope node) {
      this(context, node, null, null, null);
    }
    private Scope(Probe.ContextScope context, Probe.NodeScope node,
                  String responseToken, String responsePort) {
      this(context, node, responseToken, responsePort, null);
    }
    private Scope(Probe.ContextScope context, Probe.NodeScope node,
                  String responseToken, String responsePort, List<CallToken> blockingCalls) {
      this.context = context;
      this.node = node;
      this.responseToken = responseToken;
      this.responsePort = responsePort;
      this.blockingCalls = blockingCalls;
    }
    @Override public void close() {
      if (blockingCalls != null) {
        BLOCKING_CALLS.get().pop();
        for (CallToken marker : blockingCalls) {
          if (!marker.responseObserved) continue;
          Probe.taskObserve(marker.completionToken,
              "hbase:AbstractRpcClient.callBlockingMethod");
        }
      }
      if (responseToken != null)
        Probe.send("hbase-rpc-response", responseToken, responsePort,
            "hbase:RpcServer.call:completion");
      if (context != null) context.close();
      if (node != null) node.close();
    }
  }
}
