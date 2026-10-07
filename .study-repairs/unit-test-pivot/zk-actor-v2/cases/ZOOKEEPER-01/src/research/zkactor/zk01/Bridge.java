package research.zkactor.zk01;

import java.io.File;
import java.io.IOException;
import java.lang.reflect.Array;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.net.InetSocketAddress;
import java.net.SocketAddress;
import java.nio.channels.SelectionKey;
import java.nio.channels.SocketChannel;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.Set;
import research.zkactor.ActorRegistry;
import research.zkactor.Probe;

/** Original-test receiver joins for SessionUpgradeQuorumTest, without source edits. */
public final class Bridge {
  private static final ActorRegistry REGISTRY = new ActorRegistry();
  private static final Set<Long> PEER_SIDS = new HashSet<>();
  private static final IdentityHashMap<Object, String> CLIENT_ROLES = new IdentityHashMap<>();
  private static final Set<String> REPORTED_SESSIONS = new HashSet<>();
  private static volatile long selectedLeader = -1;
  private static volatile boolean clusterBound;
  private static final String CHECK = "SessionTrackerImpl#checkSession:316:isClosing";

  private Bridge() {}

  private static Field field(Class<?> owner, String name) throws NoSuchFieldException {
    for (Class<?> current = owner; current != null; current = current.getSuperclass()) {
      try {
        Field result = current.getDeclaredField(name);
        result.setAccessible(true);
        return result;
      } catch (NoSuchFieldException ignored) { }
    }
    throw new NoSuchFieldException(owner.getName() + "." + name);
  }

  private static Object value(Object owner, String name) throws Exception {
    return field(owner.getClass(), name).get(owner);
  }

  private static Object call(Object owner, String method) throws Exception {
    Method found = owner.getClass().getMethod(method);
    return found.invoke(owner);
  }

  private static void error(String stage, Throwable cause) {
    Probe.diagnostic("BINDING_ERROR", stage, cause.getClass().getName(),
        String.valueOf(cause.getMessage()));
  }

  /** Test's selected array slot is a physical leader peer; role alias is stable. */
  public static synchronized void enterTest(Object test, int selectedSlot) {
    clusterBound = false;
    try {
      Object peerArray = value(test, "qpMain");
      int[] ports = (int[]) value(test, "clientPorts");
      if (selectedSlot < 0 || selectedSlot >= Array.getLength(peerArray)
          || ports.length != Array.getLength(peerArray)) {
        throw new IllegalStateException("selected slot or peer/port array mismatch");
      }
      for (int slot = 0; slot < ports.length; slot++) {
        Object qp = value(Array.get(peerArray, slot), "quorumPeer");
        long sid = ((Number) call(qp, "getMyId")).longValue();
        File snapDir = (File) call(call(qp, "getTxnFactory"), "getSnapDir");
        REGISTRY.registerPeer(qp, sid, snapDir, ports[slot]);
        PEER_SIDS.add(sid);
        if (slot == selectedSlot) {
          REGISTRY.assignPeerRole(sid, "leader");
          selectedLeader = sid;
        }
        Probe.diagnostic("PEER_BIND", Integer.toString(slot), Long.toString(sid),
            Integer.toString(ports[slot]), snapDir.getAbsolutePath());
      }
      Probe.diagnostic("SELECTED_LEADER", Integer.toString(selectedSlot),
          Long.toString(selectedLeader));
      clusterBound = true;
    } catch (Throwable failure) { error("enterTest", failure); }
  }

  /** Called immediately after each original ZooKeeper constructor and ASTORE. */
  public static void registerZooKeeper(Object zk, String role, int selectedSlot) {
    try {
      Object client = value(zk, "cnxn");
      REGISTRY.registerClient(client, role, role);
      synchronized (Bridge.class) { CLIENT_ROLES.put(client, role); }
      Probe.diagnostic("CLIENT_BIND", role, Integer.toString(selectedSlot),
          Long.toString(selectedLeader));
    } catch (Throwable failure) { error("registerZooKeeper", failure); }
  }

  /** Only a real socket channel with a registered destination may yield a fault key. */
  public static void clientIo(Object socket, Object client, String site, String operation)
      throws IOException {
    Object channel = null;
    int remotePort = -1;
    try {
      SelectionKey key = (SelectionKey) value(socket, "sockKey");
      if (key != null && key.channel() instanceof SocketChannel) {
        SocketChannel sock = (SocketChannel) key.channel();
        channel = sock;
        SocketAddress address = sock.getRemoteAddress();
        if (address instanceof InetSocketAddress) {
          remotePort = ((InetSocketAddress) address).getPort();
        }
      }
      long session = ((Number) value(socket, "sessionId")).longValue();
      if (session != 0) {
        REGISTRY.bindRawSession(client, session);
        synchronized (Bridge.class) {
          String role = CLIENT_ROLES.get(client);
          String binding = session + ":" + role;
          if (REPORTED_SESSIONS.add(binding)) {
            Probe.diagnostic("SESSION_BIND", Long.toString(session), role,
                Long.toString(selectedLeader));
          }
        }
      }
    } catch (Throwable failure) {
      error("clientIo", failure);
      Probe.io(site, null);
      return;
    }
    clientIoResolved(client, channel, remotePort, site, operation);
  }

  /** Also used by an offline two-actor test; production resolves the actual socket above. */
  static void clientIoResolved(Object client, Object channel, int remotePort,
      String site, String operation) throws IOException {
    Probe.io(site, clusterBound ? REGISTRY.clientIo(client, channel, remotePort, operation)
        : null);
  }

  public static void serverIo(Object connection, String site, String operation)
      throws IOException {
    ActorRegistry.IoIdentity identity = null;
    try {
      Object server = value(connection, "zkServer");
      long sid = ((Number) call(server, "getServerId")).longValue();
      long session = ((Number) value(connection, "sessionId")).longValue();
      synchronized (Bridge.class) {
        if (clusterBound && PEER_SIDS.contains(sid)) {
          REGISTRY.registerServer(server, sid);
          identity = REGISTRY.serverIo(connection, server, session, operation);
        }
      }
    } catch (Throwable failure) { error("serverIo", failure); }
    Probe.io(site, identity);
  }

  public static void peerFileIo(Object peer, String filename, String site, String operation)
      throws IOException {
    ActorRegistry.IoIdentity identity = null;
    try {
      File snapDir = (File) call(call(peer, "getTxnFactory"), "getSnapDir");
      if (clusterBound) {
        identity = REGISTRY.epochFileIo(peer, new File(snapDir, filename), operation);
      }
    } catch (Throwable failure) { error("peerFileIo", failure); }
    Probe.io(site, identity);
  }

  private static ActorRegistry.TargetIdentity target(Object tracker, long session) {
    try {
      Object server = value(tracker, "expirer");
      long sid = ((Number) call(server, "getServerId")).longValue();
      synchronized (Bridge.class) {
        if (!clusterBound || !PEER_SIDS.contains(sid) || sid != selectedLeader) return null;
        REGISTRY.registerServer(server, sid);
        ActorRegistry.TargetIdentity identity = REGISTRY.target(server, "leader", session);
        return identity.bound() && "creatorCloser".equals(identity.sessionTag)
            ? identity : null;
      }
    } catch (Throwable failure) { error("target", failure); return null; }
  }

  public static void targetGuard(Object tracker, long session) {
    Probe.targetGuard(CHECK, target(tracker, session), "isClosing-guard");
  }

  public static void targetThrow(Throwable exception, Object tracker, long session) {
    Probe.targetThrow(CHECK, target(tracker, session), exception.getClass().getName());
  }

}
