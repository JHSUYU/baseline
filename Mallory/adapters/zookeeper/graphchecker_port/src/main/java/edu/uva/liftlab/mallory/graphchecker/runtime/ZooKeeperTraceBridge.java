package edu.uva.liftlab.mallory.graphchecker.runtime;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.net.Socket;
import java.net.SocketAddress;
import java.nio.ByteBuffer;
import java.util.ArrayDeque;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/**
 * Trace metadata for ZooKeeper's unchanged in-JVM quorum protocol.
 *
 * <p>The adapter never changes a QuorumPacket or its socket bytes.  The
 * directional TCP endpoint pair and FIFO order identify the corresponding
 * write and read within this one test JVM.  A missing or mismatched entry is
 * a graph gap, never a guessed message edge.</p>
 */
public final class ZooKeeperTraceBridge {
    private static final String TRANSPORT = "ZOOKEEPER_QUORUM_TCP";
    private static final int LEADERINFO = 17;
    private static final int ACKEPOCH = 18;
    private static final Map<Long, Long> EPOCHS = new HashMap<Long, Long>();
    private static final IdentityHashMap<Object, Boolean> PEERS =
            new IdentityHashMap<Object, Boolean>();
    private static final Map<String, ArrayDeque<PacketContext>> IN_FLIGHT =
            new HashMap<String, ArrayDeque<PacketContext>>();
    private static final ThreadLocal<PacketContext> PREPARED_LEADER_INFO =
            new ThreadLocal<PacketContext>();
    private static final ThreadLocal<PacketContext> PREPARED_ACK_EPOCH =
            new ThreadLocal<PacketContext>();
    private static long nextPacket = 1L;
    private static final ThreadLocal<Long> PEER_RUN_TICK =
            new ThreadLocal<Long>();
    private static final ThreadLocal<Long> TARGET_TICK =
            new ThreadLocal<Long>();
    private static final ThreadLocal<Long> SELECTED_TARGET_TICK =
            new ThreadLocal<Long>();
    private static final ThreadLocal<Long> PEER_START_TICK =
            new ThreadLocal<Long>();
    private static final ThreadLocal<Long> FOLLOWER_TICK =
            new ThreadLocal<Long>();
    private static final ThreadLocal<Long> HANDLER_TICK =
            new ThreadLocal<Long>();

    private ZooKeeperTraceBridge() {
    }

    /** Called at each real QuorumPeer thread's run entry. */
    public static void registerPeer(Object peer) {
        if (peer == null) return;
        synchronized (PEERS) {
            if (PEERS.containsKey(peer)) return;
            long sid = number(peer, "getMyId");
            long epoch = EPOCHS.containsKey(sid) ? EPOCHS.get(sid) + 1L : 0L;
            EPOCHS.put(sid, epoch);
            PEERS.put(peer, Boolean.TRUE);
            MessageDoors.registerSource(peer, "ZOOKEEPER_PEER", "SERVER",
                    "zk-peer-" + sid, epoch);
        }
    }

    /** A peer's own long-lived thread is its root, including after restart. */
    public static void peerRunEntered(Object peer) {
        registerPeer(peer);
        PEER_RUN_TICK.set(MessageDoors.beginTick(peer, "PEER_RUN"));
    }

    public static void peerRunExited() {
        Long tick = PEER_RUN_TICK.get();
        PEER_RUN_TICK.remove();
        if (tick != null) MessageDoors.endTick(tick);
    }

    /** Attributes the persisted epoch inputs loaded on the JUnit thread. */
    public static void peerStartEntered(Object peer) {
        Long prior = PEER_START_TICK.get();
        if (prior != null) MessageDoors.endTick(prior);
        registerPeer(peer);
        PEER_START_TICK.set(MessageDoors.beginTick(peer, "PEER_START"));
    }

    public static void peerStartExited() {
        Long tick = PEER_START_TICK.get();
        PEER_START_TICK.remove();
        if (tick != null) MessageDoors.endTick(tick);
    }

    /** Opens a distinct peer turn for each actual follower rejoin attempt. */
    public static void followerEntered(Object follower) {
        Long prior = FOLLOWER_TICK.get();
        if (prior != null) MessageDoors.endTick(prior);
        Object peer = field(follower, "self");
        if (peer == null) {
            gap("follower-peer-unresolved", "followLeader has no Learner.self");
            FOLLOWER_TICK.remove();
            return;
        }
        registerPeer(peer);
        MessageDoors.registerSourceAlias(follower, peer);
        FOLLOWER_TICK.set(MessageDoors.beginTick(peer, "FOLLOW_LEADER"));
    }

    public static void followerExited() {
        Long tick = FOLLOWER_TICK.get();
        FOLLOWER_TICK.remove();
        if (tick != null) MessageDoors.endTick(tick);
    }

    /** Enters peer attribution before the target's woven region opens. */
    public static void targetEntered(Object learner) {
        Long prior = TARGET_TICK.get();
        if (prior != null) MessageDoors.endTick(prior);
        Object peer = field(learner, "self");
        if (peer == null) {
            gap("target-peer-unresolved", "registerWithLeader has no Learner.self");
            TARGET_TICK.remove();
            return;
        }
        registerPeer(peer);
        MessageDoors.registerSourceAlias(learner, peer);
        TARGET_TICK.set(MessageDoors.beginTick(peer,
                "REGISTER_WITH_LEADER"));
    }

    public static void targetExited() {
        // A received LEADERINFO installs its message context. Restore the
        // enclosing learner request before closing that request's scope.
        MessageDoors.endInbound();
        Long tick = TARGET_TICK.get();
        TARGET_TICK.remove();
        if (tick != null) MessageDoors.endTick(tick);
    }

    /** Opens an exact manifest-selected target outside the built-in turns. */
    public static void selectedTargetEntered(Object actor, String scope) {
        Long prior = SELECTED_TARGET_TICK.get();
        if (prior != null) MessageDoors.endTick(prior);
        SELECTED_TARGET_TICK.remove();
        Object peer;
        if (actor != null && actor.getClass().getName().equals(
                "org.apache.zookeeper.server.quorum.QuorumPeer")) {
            peer = actor;
        } else {
            peer = field(actor, "self");
        }
        if (peer == null) {
            gap("selected-target-peer-unresolved", scope
                    + " has no verified QuorumPeer owner");
            return;
        }
        registerPeer(peer);
        if (actor != peer) MessageDoors.registerSourceAlias(actor, peer);
        // A Leader target may execute while its ACKEPOCH inbound context is
        // active; a QuorumPeer target may execute inside PEER_START. Keep
        // that exact cause instead of creating a disconnected root.
        SELECTED_TARGET_TICK.set(MessageDoors.beginContinuation(peer, scope));
    }

    public static void selectedTargetExited() {
        Long tick = SELECTED_TARGET_TICK.get();
        SELECTED_TARGET_TICK.remove();
        if (tick != null) MessageDoors.endTick(tick);
    }

    /** A separate root for each accepted learner connection on its leader. */
    public static void handlerEntered(Object handler) {
        Object master = field(handler, "learnerMaster");
        Object peer = field(master, "self");
        if (peer == null) {
            gap("handler-peer-unresolved", "LearnerHandler has no Leader.self");
            return;
        }
        registerPeer(peer);
        MessageDoors.registerSourceAlias(handler, peer);
        HANDLER_TICK.set(MessageDoors.beginTick(peer, "LEARNER_HANDLER"));
    }

    public static void handlerExited() {
        // ACKEPOCH likewise installs a response context in this handler.
        MessageDoors.endInbound();
        Long tick = HANDLER_TICK.get();
        HANDLER_TICK.remove();
        if (tick != null) MessageDoors.endTick(tick);
    }

    /** Called when QuorumPeer installs a Follower or Leader actor. */
    public static void registerActor(Object peer, Object actor) {
        if (peer == null || actor == null) return;
        registerPeer(peer);
        MessageDoors.registerSourceAlias(actor, peer);
    }

    /** Reserve FIFO identity before bytes can become visible to the learner. */
    public static void leaderInfoPrepared(Object handler, Object packet) {
        if (number(packet, "getType") != LEADERINFO) return;
        Object master = field(handler, "learnerMaster");
        Object peer = field(master, "self");
        if (peer == null) {
            gap("leader-peer-unresolved", "LearnerHandler has no Leader.self");
            return;
        }
        registerPeer(peer);
        MessageDoors.registerSourceAlias(handler, peer);
        Socket socket = (Socket) field(handler, "sock");
        if (socket == null) {
            gap("leader-socket-unresolved", "LEADERINFO write has no socket");
            return;
        }
        String connection = directional(socket, true);
        long zxid = number(packet, "getZxid");
        String correlation;
        synchronized (IN_FLIGHT) {
            correlation = connection + "/packet/" + nextPacket++;
        }
        Object sidValue = field(handler, "sid");
        if (!(sidValue instanceof Number)) {
            gap("learner-sid-unresolved", "LEADERINFO handler has no sid");
            return;
        }
        long learnerSid = ((Number) sidValue).longValue();
        String transport = TRANSPORT + "_TO_" + learnerSid;
        PacketContext prepared = new PacketContext(LEADERINFO, zxid,
                Long.MIN_VALUE, connection, transport, correlation, peer, packet,
                "EPOCH_PROPOSE_TO_" + learnerSid);
        PacketContext prior = PREPARED_LEADER_INFO.get();
        if (prior != null) abandon(prior, "prior LEADERINFO write did not complete");
        PREPARED_LEADER_INFO.set(prepared);
        synchronized (IN_FLIGHT) {
            ArrayDeque<PacketContext> queue = IN_FLIGHT.get(connection);
            if (queue == null) {
                queue = new ArrayDeque<PacketContext>();
                IN_FLIGHT.put(connection, queue);
            }
            queue.addLast(prepared);
        }
    }

    /** Publish SEND only when the actual bufferedOutput.flush returned. */
    public static void leaderInfoFlushed(Object handler, Object packet) {
        PacketContext prepared = PREPARED_LEADER_INFO.get();
        PREPARED_LEADER_INFO.remove();
        if (prepared == null || prepared.packet != packet) {
            gap("leader-send-unprepared", "LEADERINFO flush has no exact "
                    + "prepared packet");
            return;
        }
        long tick = MessageDoors.beginTick(prepared.peer, prepared.tickKind);
        try {
            MessageDoors.Outbound outbound = MessageDoors.outbound(prepared.transport,
                    prepared.correlation, "1", MessageDoors.REQUEST,
                    prepared.peer, null, packet);
            MessageDoors.sent(outbound);
            prepared.sent(outbound);
        } catch (RuntimeException failure) {
            prepared.fail("LEADERINFO context publication failed: " + failure);
            throw failure;
        } finally {
            MessageDoors.endTick(tick);
        }
    }

    /** The matching read in Learner.readPacket, before its caller's guard. */
    public static void learnerPacketRead(Object learner, Object packet) {
        if (number(packet, "getType") != LEADERINFO) return;
        Object peer = field(learner, "self");
        if (peer == null) {
            gap("learner-peer-unresolved", "LEADERINFO read has no Learner.self");
            return;
        }
        registerPeer(peer);
        MessageDoors.registerSourceAlias(learner, peer);
        Socket socket = (Socket) field(learner, "sock");
        if (socket == null) {
            gap("learner-socket-unresolved", "LEADERINFO read has no socket");
            return;
        }
        String connection = directional(socket, false);
        PacketContext sent;
        synchronized (IN_FLIGHT) {
            ArrayDeque<PacketContext> queue = IN_FLIGHT.get(connection);
            sent = queue == null ? null : queue.pollFirst();
            if (queue != null && queue.isEmpty()) IN_FLIGHT.remove(connection);
        }
        if (sent == null) {
            gap(connection, "LEADERINFO read has no same-connection write");
            return;
        }
        long zxid = number(packet, "getZxid");
        if (sent.type != LEADERINFO || sent.zxid != zxid) {
            gap(connection, "LEADERINFO FIFO packet mismatch: write zxid="
                    + sent.zxid + ", read zxid=" + zxid);
            return;
        }
        MessageDoors.Outbound outbound = sent.awaitCompleted(connection);
        if (outbound == null) return;
        MessageDoors.inbound(outbound.trace, outbound.symbolic,
                sent.transport, outbound.correlationId,
                outbound.attemptId, MessageDoors.REQUEST, peer, false);
    }

    /** Reserve the exact ACKEPOCH FIFO slot before its physical write. */
    public static void learnerAckPrepared(Object learner, Object packet,
                                          boolean willFlush) {
        if (packet == null) return;
        if (number(packet, "getType") != ACKEPOCH) return;
        if (!willFlush) {
            gap("ack-not-flushed", "ACKEPOCH writePacketNow does not flush; "
                    + "its later completion is not observed");
            return;
        }
        Object peer = field(learner, "self");
        if (peer == null) {
            gap("ack-sender-unresolved", "ACKEPOCH write has no Learner.self");
            return;
        }
        registerPeer(peer);
        MessageDoors.registerSourceAlias(learner, peer);
        Socket socket = (Socket) field(learner, "sock");
        if (socket == null) {
            gap("ack-socket-unresolved", "ACKEPOCH write has no socket");
            return;
        }
        String connection = directional(socket, true);
        String correlation;
        synchronized (IN_FLIGHT) {
            correlation = connection + "/packet/" + nextPacket++;
        }
        String transport = TRANSPORT + "_ACKEPOCH";
        PacketContext prepared = new PacketContext(ACKEPOCH,
                number(packet, "getZxid"), packetEpoch(packet), connection, transport,
                correlation, peer, packet, "ACKEPOCH_SEND");
        PacketContext prior = PREPARED_ACK_EPOCH.get();
        if (prior != null) abandon(prior, "prior ACKEPOCH write did not complete");
        PREPARED_ACK_EPOCH.set(prepared);
        synchronized (IN_FLIGHT) {
            ArrayDeque<PacketContext> queue = IN_FLIGHT.get(connection);
            if (queue == null) {
                queue = new ArrayDeque<PacketContext>();
                IN_FLIGHT.put(connection, queue);
            }
            queue.addLast(prepared);
        }
    }

    /** Publish ACKEPOCH SEND only on writePacketNow's normal return. */
    public static void learnerAckFlushed(Object learner, Object packet,
                                         boolean flushed) {
        if (packet == null) return;
        if (number(packet, "getType") != ACKEPOCH) return;
        PacketContext prepared = PREPARED_ACK_EPOCH.get();
        PREPARED_ACK_EPOCH.remove();
        if (!flushed || prepared == null || prepared.packet != packet) {
            if (prepared != null) prepared.fail("ACKEPOCH was not flushed");
            gap("ack-send-unprepared", "ACKEPOCH completion has no exact "
                    + "prepared flush");
            return;
        }
        try {
            MessageDoors.Outbound outbound = MessageDoors.outbound(
                    prepared.transport, prepared.correlation, "1",
                    MessageDoors.RESPONSE, prepared.peer, null, packet);
            MessageDoors.sent(outbound);
            prepared.sent(outbound);
        } catch (RuntimeException failure) {
            prepared.fail("ACKEPOCH context publication failed: " + failure);
            throw failure;
        }
    }

    /** The leader's ACKEPOCH read before it constructs the StateSummary. */
    public static void leaderAckRead(Object handler, Object packet) {
        if (number(packet, "getType") != ACKEPOCH) return;
        Object master = field(handler, "learnerMaster");
        Object peer = field(master, "self");
        if (peer == null) {
            gap("ack-receiver-unresolved", "ACKEPOCH read has no Leader.self");
            return;
        }
        registerPeer(peer);
        MessageDoors.registerSourceAlias(handler, peer);
        Socket socket = (Socket) field(handler, "sock");
        if (socket == null) {
            gap("ack-leader-socket-unresolved", "ACKEPOCH read has no socket");
            return;
        }
        String connection = directional(socket, false);
        PacketContext sent;
        synchronized (IN_FLIGHT) {
            ArrayDeque<PacketContext> queue = IN_FLIGHT.get(connection);
            sent = queue == null ? null : queue.pollFirst();
            if (queue != null && queue.isEmpty()) IN_FLIGHT.remove(connection);
        }
        if (sent == null) {
            gap(connection, "ACKEPOCH read has no same-connection write");
            return;
        }
        long zxid = number(packet, "getZxid");
        long epoch = packetEpoch(packet);
        if (sent.type != ACKEPOCH || sent.zxid != zxid
                || sent.epoch != epoch || epoch == Long.MIN_VALUE) {
            gap(connection, "ACKEPOCH FIFO packet mismatch: write zxid="
                    + sent.zxid + ", epoch=" + sent.epoch
                    + "; read zxid=" + zxid + ", epoch=" + epoch);
            return;
        }
        MessageDoors.Outbound outbound = sent.awaitCompleted(connection);
        if (outbound == null) return;
        MessageDoors.inbound(outbound.trace, outbound.symbolic,
                sent.transport, outbound.correlationId,
                outbound.attemptId, MessageDoors.RESPONSE, peer, false);
    }

    private static long packetEpoch(Object packet) {
        try {
            Method read = packet.getClass().getMethod("getData");
            byte[] data = (byte[]) read.invoke(packet);
            if (data != null && data.length >= Integer.BYTES) {
                return ByteBuffer.wrap(data).getInt();
            }
        } catch (ReflectiveOperationException | RuntimeException failed) {
            gap("ack-epoch", "Cannot read ACKEPOCH data: " + failed);
        }
        return Long.MIN_VALUE;
    }

    private static String directional(Socket socket, boolean outgoing) {
        SocketAddress local = socket.getLocalSocketAddress();
        SocketAddress remote = socket.getRemoteSocketAddress();
        return outgoing ? local + "->" + remote : remote + "->" + local;
    }

    private static long number(Object object, String method) {
        try {
            Method read = object.getClass().getMethod(method);
            return ((Number) read.invoke(object)).longValue();
        } catch (ReflectiveOperationException | RuntimeException failed) {
            gap(method, "Cannot read quorum packet or peer value: " + failed);
            return Long.MIN_VALUE;
        }
    }

    private static Object field(Object object, String name) {
        if (object == null) return null;
        Class<?> type = object.getClass();
        while (type != null) {
            try {
                Field member = type.getDeclaredField(name);
                member.setAccessible(true);
                return member.get(object);
            } catch (NoSuchFieldException absent) {
                type = type.getSuperclass();
            } catch (ReflectiveOperationException | RuntimeException failed) {
                gap(name, "Cannot read quorum owner/socket field: " + failed);
                return null;
            }
        }
        return null;
    }

    private static void gap(String subject, String detail) {
        MessageDoors.gap("MESSAGE_CONTEXT_REFUSED",
                TRANSPORT + ":" + subject, detail);
    }

    private static void abandon(PacketContext packet, String reason) {
        synchronized (IN_FLIGHT) {
            ArrayDeque<PacketContext> queue = IN_FLIGHT.get(packet.connection);
            if (queue != null) {
                queue.remove(packet);
                if (queue.isEmpty()) IN_FLIGHT.remove(packet.connection);
            }
        }
        packet.fail(reason);
    }

    private static final class PacketContext {
        final int type;
        final long zxid;
        final long epoch;
        final String connection;
        final String transport;
        final String correlation;
        final Object peer;
        final Object packet;
        final String tickKind;
        final CountDownLatch ready = new CountDownLatch(1);
        volatile MessageDoors.Outbound outbound;
        volatile String failure;

        PacketContext(int type, long zxid, long epoch, String connection,
                      String transport, String correlation, Object peer,
                      Object packet, String tickKind) {
            this.type = type;
            this.zxid = zxid;
            this.epoch = epoch;
            this.connection = connection;
            this.transport = transport;
            this.correlation = correlation;
            this.peer = peer;
            this.packet = packet;
            this.tickKind = tickKind;
        }

        void sent(MessageDoors.Outbound completed) {
            if (completed != null && completed.active()) {
                outbound = completed;
            } else {
                failure = "completed transport has no active trace context";
            }
            ready.countDown();
        }

        void fail(String reason) {
            failure = reason;
            ready.countDown();
        }

        MessageDoors.Outbound awaitCompleted(String subject) {
            try {
                if (!ready.await(5L, TimeUnit.SECONDS)) {
                    gap(subject, "packet was read before a confirmed "
                            + "successful send; completion timed out");
                    return null;
                }
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                gap(subject, "packet send completion wait interrupted");
                return null;
            }
            if (outbound == null) {
                gap(subject, "packet has no confirmed send: " + failure);
            }
            return outbound;
        }
    }
}
