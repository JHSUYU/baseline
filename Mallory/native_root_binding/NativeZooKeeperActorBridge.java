package edu.uva.liftlab.mallory.nativebinding;

import edu.uva.liftlab.graphchecker.runtime.MessageDoors;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.Map;

/**
 * ZooKeeper actor identity for the original GraphChecker runtime.
 *
 * <p>These hooks sit on actor lifecycle and carrier methods, independent of a
 * selected target check.  A QuorumPeer object is one process-like source; a
 * replacement object with the same server ID starts the next source epoch.
 * The peer's run turn supersedes the inherited JUnit client request on its
 * thread.  Learner objects are aliases of their real {@code self} peer.</p>
 */
public final class NativeZooKeeperActorBridge {
    private static final Map<Object, Long> PEERS = new IdentityHashMap<>();
    private static final Map<Long, Long> EPOCHS = new HashMap<>();
    private static final ThreadLocal<Deque<Long>> START_TICKS =
            ThreadLocal.withInitial(ArrayDeque::new);
    private static final ThreadLocal<Deque<Long>> RUN_TICKS =
            ThreadLocal.withInitial(ArrayDeque::new);

    private NativeZooKeeperActorBridge() { }

    public static void peerStartEntered(Object peer) {
        registerPeer(peer);
        START_TICKS.get().push(MessageDoors.beginTick(peer, "PEER_START"));
    }

    public static void peerStartExited() {
        end(START_TICKS);
    }

    public static void peerRunEntered(Object peer) {
        registerPeer(peer);
        RUN_TICKS.get().push(MessageDoors.beginTick(peer, "PEER_RUN"));
    }

    public static void peerRunExited() {
        end(RUN_TICKS);
    }

    /** Bind every Learner method's receiver before any GraphChecker entry hook. */
    public static void learnerEntered(Object learner) {
        if (learner == null) return;
        Object peer = field(learner, "self");
        // Some inherited Learner methods run during construction, before
        // Follower/Observer installs self.  They have no peer to claim yet.
        if (peer == null) return;
        registerPeer(peer);
        MessageDoors.registerSourceAlias(learner, peer);
    }

    private static synchronized void registerPeer(Object peer) {
        if (peer == null) throw new IllegalArgumentException("peer is null");
        if (PEERS.containsKey(peer)) return;
        long sid = id(peer);
        long epoch = EPOCHS.containsKey(sid) ? EPOCHS.get(sid) + 1L : 0L;
        // The registration must succeed before the local maps advance.
        MessageDoors.registerSource(peer, "ZOOKEEPER_PEER", "SERVER",
                "zk-peer-" + sid, epoch);
        PEERS.put(peer, epoch);
        EPOCHS.put(sid, epoch);
    }

    private static long id(Object peer) {
        try {
            Method method = peer.getClass().getMethod("getMyId");
            Object value = method.invoke(peer);
            if (!(value instanceof Number)) {
                throw new IllegalStateException("QuorumPeer.getMyId is not numeric");
            }
            return ((Number) value).longValue();
        } catch (ReflectiveOperationException failure) {
            throw new IllegalStateException("cannot read QuorumPeer.getMyId", failure);
        }
    }

    private static Object field(Object object, String name) {
        for (Class<?> clazz = object.getClass(); clazz != null;
                clazz = clazz.getSuperclass()) {
            try {
                Field field = clazz.getDeclaredField(name);
                field.setAccessible(true);
                return field.get(object);
            } catch (NoSuchFieldException ignored) {
                // The receiver may be a Follower or Observer subclass.
            } catch (IllegalAccessException failure) {
                throw new IllegalStateException("cannot read Learner.self", failure);
            }
        }
        throw new IllegalStateException("Learner.self field is absent");
    }

    private static void end(ThreadLocal<Deque<Long>> ticks) {
        Deque<Long> held = ticks.get();
        if (held.isEmpty()) {
            throw new IllegalStateException("actor turn exit has no matching entry");
        }
        MessageDoors.endTick(held.pop());
        if (held.isEmpty()) ticks.remove();
    }
}
