package research.zkactor.zk03;

import java.io.File;
import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.net.InetSocketAddress;
import java.net.SocketAddress;
import java.nio.channels.SelectionKey;
import java.nio.channels.SocketChannel;
import java.util.HashMap;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.Set;
import research.zkactor.ActorRegistry;
import research.zkactor.Probe;

/** Exact peer, handle, moved-session and request-owner joins for QuorumTest. */
public final class Bridge {
  private static final String CHECK = "SessionTrackerImpl#setOwner:329:missingOrClosing";
  private static final ActorRegistry REGISTRY = new ActorRegistry();
  private static final Map<Long, Object> PEERS = new HashMap<>();
  private static final Map<Long, Integer> PEER_PORTS = new HashMap<>();
  private static final IdentityHashMap<Object, Long> EXPECTED_DESTINATION = new IdentityHashMap<>();
  private static final IdentityHashMap<Object, String> HANDLE_ROLES = new IdentityHashMap<>();
  private static final IdentityHashMap<Object, Integer> OWNER_GENERATIONS = new IdentityHashMap<>();
  private static final Map<String, Integer> NEXT_OWNER_GENERATION = new HashMap<>();
  private static final Set<String> REPORTED_SESSIONS = new HashSet<>();
  private static volatile boolean clusterBound;

  private Bridge() {}

  private static Field field(Class<?> clazz, String name) throws NoSuchFieldException {
    for (Class<?> current = clazz; current != null; current = current.getSuperclass()) {
      try {
        Field found = current.getDeclaredField(name);
        found.setAccessible(true);
        return found;
      } catch (NoSuchFieldException ignored) { }
    }
    throw new NoSuchFieldException(clazz.getName() + "." + name);
  }

  private static Object value(Object object, String name) throws Exception {
    return field(object.getClass(), name).get(object);
  }

  private static Object call(Object object, String name) throws Exception {
    Method method = object.getClass().getMethod(name);
    return method.invoke(object);
  }

  private static void error(String stage, Throwable failure) {
    Probe.diagnostic("BINDING_ERROR", stage, failure.getClass().getName(),
        String.valueOf(failure.getMessage()));
  }

  /** Register the actual five QuorumBase peers and their original client ports. */
  public static synchronized void enterTest(Object test) {
    clusterBound = false;
    try {
      Object qb = value(test, "qb");
      String[] listed = ((String) value(qb, "hostPort")).split(",");
      if (listed.length != 5) throw new IllegalStateException("not the five-peer original test");
      int leaders = 0;
      for (int sid = 1; sid <= 5; sid++) {
        Object peer = value(qb, "s" + sid);
        int port = ((Number) value(qb, "portClient" + sid)).intValue();
        int listedPort = Integer.parseInt(listed[sid - 1].substring(
            listed[sid - 1].lastIndexOf(':') + 1));
        if (peer == null || port != listedPort
            || ((Number) call(peer, "getMyId")).longValue() != sid) {
          throw new IllegalStateException("peer SID/port/hostPort disagree at " + sid);
        }
        File snapDir = (File) call(call(peer, "getTxnFactory"), "getSnapDir");
        REGISTRY.registerPeer(peer, sid, snapDir, port);
        PEERS.put((long) sid, peer);
        PEER_PORTS.put((long) sid, port);
        Probe.diagnostic("PEER_BIND", Integer.toString(sid), Integer.toString(port),
            snapDir.getAbsolutePath());
        if (value(peer, "leader") != null) {
          leaders++;
          Probe.diagnostic("LEADER_BIND", Integer.toString(sid));
        }
      }
      if (leaders != 1) throw new IllegalStateException("expected exactly one live leader");
      clusterBound = true;
    } catch (Throwable failure) { error("enterTest", failure); }
  }

  private static Object client(Object zk) throws Exception { return value(zk, "cnxn"); }

  private static void registerHandle(Object zk, String role, long destinationSid) throws Exception {
    if (!clusterBound || !PEERS.containsKey(destinationSid)) {
      throw new IllegalStateException("cluster or destination unbound");
    }
    Object actualClient = client(zk);
    REGISTRY.registerClient(actualClient, role, "movedSession");
    EXPECTED_DESTINATION.put(actualClient, destinationSid);
    HANDLE_ROLES.put(actualClient, role);
    Probe.diagnostic("HANDLE_BIND", role, Long.toString(destinationSid),
        Integer.toString(PEER_PORTS.get(destinationSid)));
  }

  /** First original constructor, before the first ephemeral create completes. */
  public static synchronized void registerInitial(Object zk) {
    try { registerHandle(zk, "handle:0", 1); }
    catch (Throwable failure) { error("registerInitial", failure); }
  }

  /** Every successor reuses the same raw session, but is a distinct handle. */
  public static synchronized void registerMoved(Object next, int iteration, Object previous) {
    try {
      if (iteration < 0 || iteration >= 10) throw new IllegalStateException("bad handoff index");
      long raw = ((Number) call(previous, "getSessionId")).longValue();
      long reportedNext = ((Number) call(next, "getSessionId")).longValue();
      if (raw == 0 || (reportedNext != 0 && reportedNext != raw)) {
        throw new IllegalStateException("handoff did not reuse previous raw session");
      }
      registerHandle(next, "handle:" + (iteration + 1), (iteration + 1) % 5 + 1);
      REGISTRY.bindRawSession(client(previous), raw);
      REGISTRY.bindRawSession(client(next), raw);
      String previousRole = HANDLE_ROLES.get(client(previous));
      if (previousRole == null) throw new IllegalStateException("previous handle unregistered");
      String previousKey = raw + ":" + previousRole;
      if (REPORTED_SESSIONS.add(previousKey)) {
        Probe.diagnostic("SESSION_BIND", Long.toString(raw), previousRole, "movedSession");
      }
      String key = raw + ":handle:" + (iteration + 1);
      if (REPORTED_SESSIONS.add(key)) {
        Probe.diagnostic("SESSION_BIND", Long.toString(raw), "handle:" + (iteration + 1),
            "movedSession");
      }
    } catch (Throwable failure) { error("registerMoved", failure); }
  }

  public static void clientIo(Object socket, Object client, String site, String operation)
      throws IOException {
    Object channel;
    int port;
    try {
      SelectionKey key = (SelectionKey) value(socket, "sockKey");
      if (key == null || !(key.channel() instanceof SocketChannel)) {
        Probe.io(site, null);
        return;
      }
      SocketChannel actual = (SocketChannel) key.channel();
      SocketAddress remote = actual.getRemoteAddress();
      if (!(remote instanceof InetSocketAddress)) {
        Probe.io(site, null);
        return;
      }
      channel = actual;
      port = ((InetSocketAddress) remote).getPort();
      long raw = ((Number) value(socket, "sessionId")).longValue();
      if (raw != 0) {
        REGISTRY.bindRawSession(client, raw);
        String role;
        synchronized (Bridge.class) { role = HANDLE_ROLES.get(client); }
        if (role != null) {
          String keyName = raw + ":" + role;
          synchronized (Bridge.class) {
            if (REPORTED_SESSIONS.add(keyName)) {
              Probe.diagnostic("SESSION_BIND", Long.toString(raw), role, "movedSession");
            }
          }
        }
      }
    } catch (Throwable failure) {
      error("clientIo", failure);
      Probe.io(site, null);
      return;
    }
    clientIoResolved(client, channel, port, site, operation);
  }

  /** Offline test enters here after using the same test/handle registration hooks. */
  static void clientIoResolved(Object client, Object channel, int port, String site,
      String operation) throws IOException {
    ActorRegistry.IoIdentity identity = clusterBound
        ? REGISTRY.clientIo(client, channel, port, operation) : null;
    Long expected;
    synchronized (Bridge.class) { expected = EXPECTED_DESTINATION.get(client); }
    if (identity != null && identity.bound()
        && (expected == null || !Long.toString(expected).equals(identity.counterpartyPeer))) {
      Probe.diagnostic("DESTINATION_MISMATCH", site, String.valueOf(expected),
          identity.counterpartyPeer);
      identity = null;
    }
    Probe.io(site, identity);
  }

  public static void serverIo(Object connection, String site, String operation)
      throws IOException {
    ActorRegistry.IoIdentity identity = null;
    try {
      Object server = value(connection, "zkServer");
      long sid = ((Number) call(server, "getServerId")).longValue();
      long raw = ((Number) value(connection, "sessionId")).longValue();
      if (clusterBound && PEERS.containsKey(sid)) {
        REGISTRY.registerServer(server, sid);
        identity = REGISTRY.serverIo(connection, server, raw, operation);
      }
    } catch (Throwable failure) { error("serverIo", failure); }
    Probe.io(site, identity);
  }

  public static void peerFileIo(Object peer, String filename, String site, String operation)
      throws IOException {
    ActorRegistry.IoIdentity identity = null;
    try {
      if (clusterBound) {
        File snapDir = (File) call(call(peer, "getTxnFactory"), "getSnapDir");
        identity = REGISTRY.epochFileIo(peer, new File(snapDir, filename), operation);
      }
    } catch (Throwable failure) { error("peerFileIo", failure); }
    Probe.io(site, identity);
  }

  private static boolean isLeaderServer(Object server, long sid) throws Exception {
    Object peer = PEERS.get(sid);
    return peer != null && value(peer, "leader") != null;
  }

  private static String ownerKey(Object owner, Object server, long localSid) throws Exception {
    if (owner == null) return null;
    Class<?> serverCnxn = Class.forName("org.apache.zookeeper.server.ServerCnxn");
    if (owner == field(serverCnxn, "me").get(null)) return "local:" + localSid;
    if (!Class.forName("org.apache.zookeeper.server.quorum.LearnerHandler").isInstance(owner)) {
      return null;
    }
    long forwardedSid = ((Number) value(owner, "sid")).longValue();
    if (!PEERS.containsKey(forwardedSid) || value(value(owner, "learnerMaster"), "zk") != server) {
      return null;
    }
    String base = "forwarder:" + forwardedSid;
    synchronized (Bridge.class) {
      Integer generation = OWNER_GENERATIONS.get(owner);
      if (generation == null) {
        generation = NEXT_OWNER_GENERATION.getOrDefault(base, 0) + 1;
        NEXT_OWNER_GENERATION.put(base, generation);
        OWNER_GENERATIONS.put(owner, generation);
      }
      return base + ":generation:" + generation;
    }
  }

  private static ActorRegistry.TargetIdentity target(Object tracker, long raw, Object requestOwner,
      Object session, String[] ownerDetails) {
    try {
      if (!clusterBound || requestOwner == null) return null;
      Object server = value(tracker, "expirer");
      long sid = ((Number) call(server, "getServerId")).longValue();
      if (!isLeaderServer(server, sid)) return null;
      REGISTRY.registerServer(server, sid);
      ActorRegistry.TargetIdentity identity = REGISTRY.target(server, "leader", raw);
      if (!identity.bound() || !"movedSession".equals(identity.sessionTag)) return null;
      String requestedKey = ownerKey(requestOwner, server, sid);
      if (requestedKey == null) return null;
      String state = session == null ? "missing" :
          ((Boolean) call(session, "isClosing")) ? "closing" : "present-open";
      ownerDetails[0] = requestedKey;
      ownerDetails[1] = state;
      Probe.diagnostic("OWNER_BIND", Long.toString(sid), Long.toString(raw),
          requestedKey, state);
      return identity;
    } catch (Throwable failure) { error("target", failure); return null; }
  }

  public static void targetGuard(Object tracker, long raw, Object requestOwner, Object session) {
    String[] details = new String[2];
    ActorRegistry.TargetIdentity identity = target(tracker, raw, requestOwner, session, details);
    Probe.targetGuard(CHECK, identity, identity == null ? "unbound" : details[1]);
  }

  public static void targetThrow(Throwable exception, Object tracker, long raw,
      Object requestOwner, Object session) {
    String[] details = new String[2];
    ActorRegistry.TargetIdentity identity = target(tracker, raw, requestOwner, session, details);
    if (identity != null && !"present-open".equals(details[1])
        && exception.getClass().getName().equals(
            "org.apache.zookeeper.KeeperException$SessionExpiredException")) {
      Probe.targetThrow(CHECK, identity, exception.getClass().getName());
    }
  }
}
