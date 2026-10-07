package research.zkactor.zk13;

import java.io.File;
import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.net.InetSocketAddress;
import java.net.SocketAddress;
import java.nio.channels.SelectionKey;
import java.nio.channels.SocketChannel;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.Map;
import research.zkactor.ActorRegistry;
import research.zkactor.Probe;

/** Receiver and raw-session joins for the unchanged read-only cluster JUnit. */
public final class Bridge {
  static final String CHECK = "ReadOnlyZooKeeperServer#validateSession:123:isGlobalSession";
  private static final ActorRegistry REGISTRY = new ActorRegistry();
  private static final Map<Long, Object> PEERS = new HashMap<>();
  private static final Map<Integer, Long> PORTS = new HashMap<>();
  private static final IdentityHashMap<Object, Boolean> CLIENTS = new IdentityHashMap<>();
  private static Object initialClient;
  private static long initialRaw;
  private static boolean clusterBound;
  private static boolean readOnlyPhase;

  private Bridge() {}

  private static Field field(Class<?> type, String name) throws NoSuchFieldException {
    for (Class<?> current = type; current != null; current = current.getSuperclass()) {
      try {
        Field found = current.getDeclaredField(name);
        found.setAccessible(true);
        return found;
      } catch (NoSuchFieldException ignored) { }
    }
    throw new NoSuchFieldException(type.getName() + "." + name);
  }

  private static Object value(Object object, String name) throws Exception {
    return field(object.getClass(), name).get(object);
  }

  private static Object call(Object object, String name, Class<?>[] types, Object... args)
      throws Exception {
    Method method = object.getClass().getMethod(name, types);
    return method.invoke(object, args);
  }

  private static Object call(Object object, String name) throws Exception {
    return call(object, name, new Class<?>[0]);
  }

  private static void error(String stage, Throwable failure) {
    Probe.diagnostic("BINDING_ERROR", stage, failure.getClass().getName(),
        String.valueOf(failure.getMessage()));
  }

  /** Called after the original QuorumUtil.startQuorum returns. */
  public static synchronized void bindCluster(Object test) {
    clusterBound = false;
    readOnlyPhase = false;
    try {
      Object quorum = value(test, "qu");
      if (((Number) value(quorum, "N")).intValue() != 1) {
        throw new IllegalStateException("not the original three-peer QuorumUtil(1)");
      }
      for (int sid = 1; sid <= 3; sid++) {
        Object peerStruct = call(quorum, "getPeer", new Class<?>[] {int.class}, sid);
        Object peer = value(peerStruct, "peer");
        int actualSid = ((Number) call(peer, "getMyId")).intValue();
        int port = ((Number) value(peerStruct, "clientPort")).intValue();
        if (actualSid != sid || port <= 0 || PORTS.containsKey(port)) {
          throw new IllegalStateException("peer receiver/SID/client port mismatch");
        }
        File snap = (File) call(call(peer, "getTxnFactory"), "getSnapDir");
        REGISTRY.registerPeer(peer, sid, snap, port);
        PEERS.put((long) sid, peer);
        PORTS.put(port, (long) sid);
        Probe.diagnostic("PEER_BIND", Integer.toString(sid), Integer.toString(port),
            snap.getAbsolutePath());
      }
      if (PEERS.get(1L) == null || PEERS.get(2L) == null) {
        throw new IllegalStateException("quorum peers 1 and 2 unbound");
      }
      clusterBound = true;
    } catch (Throwable failure) { error("bindCluster", failure); }
  }

  /** Only the first ZooKeeper object is eligible; subsequent clients are excluded. */
  public static synchronized void bindInitialClient(Object zooKeeper) {
    try {
      if (!clusterBound || initialClient != null) {
        throw new IllegalStateException("initial client registration outside healthy phase");
      }
      Object client = value(zooKeeper, "cnxn");
      REGISTRY.registerClient(client, "initialGlobalClient", "initialGlobalSession");
      initialClient = client;
      CLIENTS.put(client, Boolean.TRUE);
      Probe.diagnostic("CLIENT_BIND", "initialGlobalClient");
    } catch (Throwable failure) { error("bindInitialClient", failure); }
  }

  /** Called only after the first original waitForConnected succeeds. */
  public static synchronized void bindInitialSession(Object zooKeeper) {
    try {
      Object client = value(zooKeeper, "cnxn");
      long raw = ((Number) call(zooKeeper, "getSessionId")).longValue();
      if (!clusterBound || client != initialClient || raw == 0 || initialRaw != 0) {
        throw new IllegalStateException("first connected client's raw session changed");
      }
      REGISTRY.bindRawSession(client, raw);
      initialRaw = raw;
      Probe.diagnostic("SESSION_BIND", Long.toString(raw), "initialGlobalClient",
          "initialGlobalSession");
    } catch (Throwable failure) { error("bindInitialSession", failure); }
  }

  /** Called after the original qu.shutdown(2); peer 1 must serve read-only. */
  public static synchronized void enterReadOnlyPhase(Object test) {
    try {
      if (!clusterBound || initialRaw == 0 || PEERS.get(1L) == null) {
        throw new IllegalStateException("read-only phase without peer and global session");
      }
      readOnlyPhase = true;
      Probe.diagnostic("RO_PHASE", "peer:1", Long.toString(initialRaw));
    } catch (Throwable failure) { error("enterReadOnlyPhase", failure); }
  }

  public static void clientIo(Object socket, Object client, String site, String operation)
      throws IOException {
    ActorRegistry.IoIdentity identity = null;
    try {
      SelectionKey key = (SelectionKey) value(socket, "sockKey");
      if (key != null && key.channel() instanceof SocketChannel) {
        SocketChannel channel = (SocketChannel) key.channel();
        SocketAddress remote = channel.getRemoteAddress();
        if (remote instanceof InetSocketAddress) {
          int port = ((InetSocketAddress) remote).getPort();
          synchronized (Bridge.class) {
            if (clusterBound && client == initialClient && initialRaw != 0
                && CLIENTS.containsKey(client)
                && ((Number) value(socket, "sessionId")).longValue() == initialRaw) {
              identity = REGISTRY.clientIo(client, channel, port, operation);
            }
          }
        }
      }
    } catch (Throwable failure) { error("clientIo", failure); }
    Probe.io(site, identity);
  }

  public static void serverIo(Object connection, String site, String operation)
      throws IOException {
    ActorRegistry.IoIdentity identity = null;
    try {
      Object server = value(connection, "zkServer");
      long raw = ((Number) value(connection, "sessionId")).longValue();
      synchronized (Bridge.class) {
        if (readOnlyPhase && raw == initialRaw && targetServer(server)) {
          REGISTRY.registerServer(server, 1);
          identity = REGISTRY.serverIo(connection, server, raw, operation);
        }
      }
    } catch (Throwable failure) { error("serverIo", failure); }
    Probe.io(site, identity);
  }

  private static boolean targetServer(Object server) throws Exception {
    if (!readOnlyPhase || server == null || !server.getClass().getName().equals(
        "org.apache.zookeeper.server.quorum.ReadOnlyZooKeeperServer")) return false;
    Object peer = PEERS.get(1L);
    return peer != null && value(server, "self") == peer
        && call(peer, "getActiveServer") == server
        && ((Number) call(server, "getServerId")).longValue() == 1L;
  }

  private static ActorRegistry.TargetIdentity selected(Object server, Object connection,
      long raw, boolean[] isGlobal) {
    try {
      synchronized (Bridge.class) {
        if (!targetServer(server) || connection == null || initialRaw == 0
            || raw != initialRaw || value(connection, "zkServer") != server) return null;
        Object tracker = value(server, "sessionTracker");
        isGlobal[0] = (Boolean) call(tracker, "isGlobalSession",
            new Class<?>[] {long.class}, raw);
        REGISTRY.registerServer(server, 1);
        ActorRegistry.TargetIdentity identity = REGISTRY.target(server, "readOnlyPeer1", raw);
        if (!identity.bound() || !"initialGlobalSession".equals(identity.sessionTag)) return null;
        Probe.diagnostic("TARGET_BIND", "1", Long.toString(raw),
            Boolean.toString(isGlobal[0]));
        return identity;
      }
    } catch (Throwable failure) { error("selected", failure); return null; }
  }

  public static void targetGuard(Object server, Object connection, long raw) {
    boolean[] global = new boolean[1];
    ActorRegistry.TargetIdentity identity = selected(server, connection, raw, global);
    Probe.targetGuard(CHECK, identity, global[0] ? "global" : "not-global");
  }

  public static void targetThrow(Throwable exception, Object server, Object connection,
      long raw) {
    boolean[] global = new boolean[1];
    ActorRegistry.TargetIdentity identity = selected(server, connection, raw, global);
    if (identity != null && global[0] && exception.getClass().getName().equals(
        "org.apache.zookeeper.server.ServerCnxn$CloseRequestException")) {
      Probe.targetThrow(CHECK, identity, exception.getClass().getName());
    }
  }
}
