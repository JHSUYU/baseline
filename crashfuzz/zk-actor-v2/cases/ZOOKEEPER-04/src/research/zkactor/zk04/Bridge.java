package research.zkactor.zk04;

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

/** Exact original test peer, client session, channel endpoint and target receiver joins. */
public final class Bridge {
  private static final String CHECK = "ZooKeeperServer#processConnectRequest:1431:CLIENT_ZXID_AHEAD";
  private static final ActorRegistry REGISTRY = new ActorRegistry();
  private static final Map<Long, Object> PEERS = new HashMap<>();
  private static final Map<Integer, Long> PEER_PORTS = new HashMap<>();
  private static final IdentityHashMap<Object, Boolean> CLIENTS = new IdentityHashMap<>();
  private static final Map<Integer, Long> CLIENT_PORT_PEER = new HashMap<>();
  private static volatile Object client;
  private static volatile long rawSession;
  private static volatile long follower1;
  private static volatile long follower2;
  private static volatile boolean bound;

  private Bridge() {}

  private static Field field(Class<?> clazz, String name) throws NoSuchFieldException {
    for (Class<?> current = clazz; current != null; current = current.getSuperclass()) {
      try {
        Field result = current.getDeclaredField(name);
        result.setAccessible(true);
        return result;
      } catch (NoSuchFieldException ignored) { }
    }
    throw new NoSuchFieldException(clazz.getName() + "." + name);
  }

  private static Object value(Object object, String name) throws Exception {
    return field(object.getClass(), name).get(object);
  }

  private static Object call(Object object, String method, Class<?>[] types, Object... args)
      throws Exception {
    Method found = object.getClass().getMethod(method, types);
    return found.invoke(object, args);
  }

  private static Object call(Object object, String method) throws Exception {
    return call(object, method, new Class<?>[0]);
  }

  private static void error(String stage, Throwable failure) {
    Probe.diagnostic("BINDING_ERROR", stage, failure.getClass().getName(),
        String.valueOf(failure.getMessage()));
  }

  /** Original QuorumUtil(1): retain the actual receiver, SID, client port and snap owner. */
  public static synchronized void registerTest(Object util, int firstSid, int secondSid,
      Object zooKeeper) {
    bound = false;
    try {
      int all = ((Number) value(util, "ALL")).intValue();
      if (all != 3 || firstSid == secondSid) {
        throw new IllegalStateException("expected three peers and distinct followers");
      }
      Object followers = call(util, "getFollowerQuorumPeers");
      if (!(followers instanceof java.util.List)
          || ((java.util.List<?>) followers).size() != 2
          || ((Number) call(((java.util.List<?>) followers).get(0), "getMyId")).longValue() != firstSid
          || ((Number) call(((java.util.List<?>) followers).get(1), "getMyId")).longValue() != secondSid) {
        throw new IllegalStateException("follower role no longer matches original test locals");
      }
      PEERS.clear();
      PEER_PORTS.clear();
      CLIENT_PORT_PEER.clear();
      for (int sid = 1; sid <= 3; sid++) {
        Object peerStruct = call(util, "getPeer", new Class<?>[] {int.class}, sid);
        Object peer = value(peerStruct, "peer");
        int port = ((Number) value(peerStruct, "clientPort")).intValue();
        if (((Number) call(peer, "getMyId")).longValue() != sid
            || ((Number) call(peer, "getClientPort")).intValue() != port) {
          throw new IllegalStateException("peer receiver/SID/port disagree at " + sid);
        }
        File snap = (File) call(call(peer, "getTxnFactory"), "getSnapDir");
        REGISTRY.registerPeer(peer, sid, snap, port);
        PEERS.put((long) sid, peer);
        PEER_PORTS.put(port, (long) sid);
        Probe.diagnostic("PEER_BIND", Integer.toString(sid), Integer.toString(port),
            snap.getAbsolutePath());
      }
      REGISTRY.assignPeerRole(firstSid, "follower1");
      REGISTRY.assignPeerRole(secondSid, "follower2");
      follower1 = firstSid;
      follower2 = secondSid;
      client = value(zooKeeper, "cnxn");
      CLIENTS.put(client, Boolean.TRUE);
      REGISTRY.registerClient(client, "revalidate-client", "revalidateSession");
      rawSession = 0;
      bound = true;
      Probe.diagnostic("ROLE_BIND", Long.toString(firstSid), Long.toString(secondSid));
      Probe.diagnostic("CLIENT_BIND", "revalidate-client", "revalidateSession");
    } catch (Throwable failure) { error("registerTest", failure); }
  }

  /** Called after the first original waitForConnected, before updateServerList. */
  public static synchronized void bindInitialSession(Object zooKeeper) {
    try {
      Object actualClient = value(zooKeeper, "cnxn");
      long raw = ((Number) call(zooKeeper, "getSessionId")).longValue();
      if (!bound || client != actualClient || raw == 0) {
        throw new IllegalStateException("initial client/session not bound");
      }
      REGISTRY.bindRawSession(actualClient, raw);
      rawSession = raw;
      Probe.diagnostic("SESSION_BIND", Long.toString(raw), "revalidate-client");
    } catch (Throwable failure) { error("bindInitialSession", failure); }
  }

  public static void clientIo(Object socket, Object actualClient, String site, String operation)
      throws IOException {
    try {
      SelectionKey key = (SelectionKey) value(socket, "sockKey");
      if (key != null && key.channel() instanceof SocketChannel && bound
          && CLIENTS.containsKey(actualClient)) {
        SocketChannel channel = (SocketChannel) key.channel();
        SocketAddress remote = channel.getRemoteAddress();
        SocketAddress local = channel.getLocalAddress();
        if (remote instanceof InetSocketAddress && local instanceof InetSocketAddress) {
          int remotePort = ((InetSocketAddress) remote).getPort();
          int localPort = ((InetSocketAddress) local).getPort();
          clientIoResolved(actualClient, channel, localPort, remotePort, site, operation);
          return;
        }
      }
    } catch (IOException injected) { throw injected; }
    catch (Throwable failure) { error("clientIo", failure); }
    Probe.io(site, null);
  }

  /** Also used by the offline wrong-peer and wrong-client smoke. */
  static void clientIoResolved(Object actualClient, Object channel, int localPort,
      int remotePort, String site, String operation) throws IOException {
    ActorRegistry.IoIdentity identity = null;
    try {
      Long sid = PEER_PORTS.get(remotePort);
      if (bound && CLIENTS.containsKey(actualClient) && sid != null && localPort > 0) {
        synchronized (Bridge.class) {
          Long old = CLIENT_PORT_PEER.putIfAbsent(localPort, sid);
          if (old != null && old.longValue() != sid) {
            throw new IllegalStateException("client local port reused for another peer");
          }
        }
        identity = REGISTRY.clientIo(actualClient, channel, remotePort, operation);
        if (identity.bound()) {
          Probe.diagnostic("CHANNEL_BIND", Integer.toString(localPort),
              Long.toString(sid), Long.toString(rawSession), identity.resource);
        }
      }
    } catch (Throwable failure) { error("clientIoResolved", failure); }
    Probe.io(site, identity);
  }

  public static void serverIo(Object connection, String site, String operation)
      throws IOException {
    ActorRegistry.IoIdentity identity = null;
    try {
      Object server = value(connection, "zkServer");
      if (server != null && bound) {
        long sid = ((Number) call(server, "getServerId")).longValue();
        Object peer = PEERS.get(sid);
        if (peer != null && call(peer, "getActiveServer") == server) {
          REGISTRY.registerServer(server, sid);
          long raw = ((Number) value(connection, "sessionId")).longValue();
          identity = REGISTRY.serverIo(connection, server, raw, operation);
        }
      }
    } catch (Throwable failure) { error("serverIo", failure); }
    Probe.io(site, identity);
  }

  public static void peerFileIo(Object peer, String filename, String site, String operation)
      throws IOException {
    ActorRegistry.IoIdentity identity = null;
    try {
      if (bound && PEERS.containsValue(peer)) {
        File snap = (File) call(call(peer, "getTxnFactory"), "getSnapDir");
        identity = REGISTRY.epochFileIo(peer, new File(snap, filename), operation);
      }
    } catch (Throwable failure) { error("peerFileIo", failure); }
    Probe.io(site, identity);
  }

  private static ActorRegistry.TargetIdentity selectedTarget(Object server, Object connection,
      Object request, long raw) {
    try {
      if (!bound || raw == 0 || raw != rawSession || client == null) return null;
      long sid = ((Number) call(server, "getServerId")).longValue();
      Object peer = PEERS.get(sid);
      if (sid != follower2 || peer == null || call(peer, "getActiveServer") != server
          || value(connection, "zkServer") != server
          || ((Number) call(request, "getSessionId")).longValue() != raw) return null;
      InetSocketAddress remote = (InetSocketAddress) call(connection, "getRemoteSocketAddress");
      Long sourcePeer;
      synchronized (Bridge.class) { sourcePeer = CLIENT_PORT_PEER.get(remote.getPort()); }
      if (sourcePeer == null || sourcePeer.longValue() != sid) return null;
      REGISTRY.registerServer(server, sid);
      ActorRegistry.TargetIdentity target = REGISTRY.target(server, "follower2", raw);
      if (!target.bound() || !"revalidateSession".equals(target.sessionTag)) return null;
      Probe.diagnostic("TARGET_OWNER_BIND", Long.toString(sid), Long.toString(raw),
          Integer.toString(remote.getPort()), target.actor,
          Long.toString(((Number) call(request, "getLastZxidSeen")).longValue()));
      return target;
    } catch (Throwable failure) { error("selectedTarget", failure); return null; }
  }

  public static void targetGuard(int compare, Object server, Object connection,
      Object request, long raw) {
    ActorRegistry.TargetIdentity target = selectedTarget(server, connection, request, raw);
    Probe.targetGuard(CHECK, target, compare > 0 ? "ahead" : "normal");
  }

  public static void targetThrow(Throwable exception, Object server, Object connection,
      Object request, long raw) {
    ActorRegistry.TargetIdentity target = selectedTarget(server, connection, request, raw);
    if (exception.getClass().getName().equals(
        "org.apache.zookeeper.server.ServerCnxn$CloseRequestException")) {
      Probe.targetThrow(CHECK, target, exception.getClass().getName());
    } else {
      Probe.diagnostic("OTHER_THROW", CHECK, exception.getClass().getName());
    }
  }
}
