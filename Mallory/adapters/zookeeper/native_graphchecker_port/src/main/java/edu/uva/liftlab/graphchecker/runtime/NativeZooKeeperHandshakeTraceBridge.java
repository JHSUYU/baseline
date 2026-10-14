package edu.uva.liftlab.graphchecker.runtime;

import edu.uva.liftlab.graphchecker.contract.GapClass;
import edu.uva.liftlab.graphchecker.contract.GapKind;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.net.Socket;
import java.util.ArrayDeque;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Exact, same-JVM ZooKeeper quorum handshake receipts for the original runtime. */
public final class NativeZooKeeperHandshakeTraceBridge {
    private static final int FOLLOWERINFO = 11;
    private static final int OBSERVERINFO = 16;
    private static final int LEADERINFO = 17;
    private static final String TRANSPORT = "ZOOKEEPER_QUORUM_HANDSHAKE";
    private static final Object LOCK = new Object();
    private static final Map<String, ArrayDeque<Packet>> IN_FLIGHT =
            new HashMap<String, ArrayDeque<Packet>>();
    private static final ThreadLocal<Packet> LEADER_PREPARED = new ThreadLocal<Packet>();
    private static final ThreadLocal<Packet> FOLLOWER_PREPARED = new ThreadLocal<Packet>();
    private static long nextPacket = 1L;

    private NativeZooKeeperHandshakeTraceBridge() { }

    /** Learner.writePacketNow entry; only a flushed learner-info packet is eligible. */
    public static void followerPrepared(Object learner, Object packet, boolean flush) {
        int packetType = type(packet);
        if (!learnerInfo(packetType)) return;
        if (!flush) { gap("LEARNERINFO_UNFLUSHED", "writePacketNow did not request flush"); return; }
        Packet pending = prepare(learner, packet, field(learner, "self"),
                (Socket) field(learner, "sock"), packetType);
        Packet prior = FOLLOWER_PREPARED.get();
        if (prior != null) abandon(prior, "next follower packet replaced unfinished write");
        FOLLOWER_PREPARED.set(pending);
    }

    /** Normal return follows writeRecord and successful BufferedOutputStream.flush. */
    public static void followerFlushed(Object learner, Object packet, boolean flush) {
        if (!learnerInfo(type(packet))) return;
        Packet pending = FOLLOWER_PREPARED.get();
        FOLLOWER_PREPARED.remove();
        complete(pending, packet, flush, "FOLLOWERINFO_SEND_UNCONFIRMED");
    }

    /** LearnerHandler's first readRecord returned with a complete packet. */
    public static void leaderReadFollower(Object handler, Object packet) {
        int packetType = type(packet);
        if (!learnerInfo(packetType)) return;
        receive(handler, packet, field(field(handler, "learnerMaster"), "self"),
                (Socket) field(handler, "sock"), packetType);
    }

    /** Reserve before the exact LEADERINFO writeRecord; publish after flush. */
    public static void leaderPrepared(Object handler, Object packet) {
        if (type(packet) != LEADERINFO) return;
        Packet pending = prepare(handler, packet,
                field(field(handler, "learnerMaster"), "self"),
                (Socket) field(handler, "sock"), LEADERINFO);
        Packet prior = LEADER_PREPARED.get();
        if (prior != null) abandon(prior, "next leader packet replaced unfinished write");
        LEADER_PREPARED.set(pending);
    }

    /** Called only after the successful flush following LEADERINFO writeRecord. */
    public static void leaderFlushed(Object handler, Object packet) {
        Packet pending = LEADER_PREPARED.get();
        LEADER_PREPARED.remove();
        complete(pending, packet, true, "LEADERINFO_SEND_UNCONFIRMED");
    }

    /** Learner.readPacket completed deserialization before the target check. */
    public static void learnerReadLeader(Object learner, Object packet) {
        if (type(packet) != LEADERINFO) return;
        receive(learner, packet, field(learner, "self"),
                (Socket) field(learner, "sock"), LEADERINFO);
    }

    private static Packet prepare(Object alias, Object packet, Object peer,
                                  Socket socket, int expectedType) {
        String direction = direction(socket, true);
        if (peer == null || direction == null || type(packet) != expectedType) {
            gap("HANDSHAKE_SEND_UNRESOLVED", "peer, socket or packet unavailable");
            return null;
        }
        if (!source(alias, peer)) return null;
        long packetZxid = zxid(packet);
        String correlation;
        synchronized (LOCK) {
            correlation = direction + "/type/" + expectedType + "/zxid/"
                    + packetZxid + "/packet/" + nextPacket++;
        }
        Packet pending = new Packet(packet, expectedType, packetZxid, direction,
                correlation, peer, MessageDoors.captureScope());
        synchronized (LOCK) {
            IN_FLIGHT.computeIfAbsent(direction, ignored -> new ArrayDeque<Packet>())
                    .addLast(pending);
        }
        return pending;
    }

    private static void complete(Packet pending, Object packet, boolean flushed,
                                 String subject) {
        if (pending == null || pending.packet != packet || !flushed) {
            if (pending != null) pending.fail("packet identity or successful flush missing");
            gap(subject, "no exact prepared packet and completed flush");
            return;
        }
        try {
            pending.outbound = MessageDoors.outbound(TRANSPORT,
                    pending.correlation, "1", MessageDoors.REQUEST,
                    pending.peer, pending.scope);
        } catch (RuntimeException failure) {
            gap(subject, "native outbound refused: " + failure);
        } finally {
            pending.done.countDown();
        }
    }

    private static void receive(Object alias, Object packet, Object peer,
                                Socket socket, int expectedType) {
        String direction = direction(socket, false);
        if (peer == null || direction == null) {
            gap("HANDSHAKE_READ_UNRESOLVED", "peer or socket unavailable");
            return;
        }
        Packet pending;
        synchronized (LOCK) {
            ArrayDeque<Packet> queue = IN_FLIGHT.get(direction);
            pending = queue == null ? null : queue.peekFirst();
            if (pending != null && pending.type == expectedType
                    && pending.zxid == zxid(packet)) {
                queue.removeFirst();
                if (queue.isEmpty()) IN_FLIGHT.remove(direction);
            } else {
                pending = null;
            }
        }
        if (pending == null) {
            gap("HANDSHAKE_NO_EXACT_SEND", direction + " type=" + expectedType
                    + " zxid=" + zxid(packet));
            return;
        }
        try {
            if (!pending.done.await(5L, TimeUnit.SECONDS)) {
                gap("HANDSHAKE_SEND_TIMEOUT", direction);
                return;
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            gap("HANDSHAKE_SEND_INTERRUPTED", direction);
            return;
        }
        if (pending.outbound == null || !pending.outbound.active()) {
            gap("HANDSHAKE_SEND_NO_CONTEXT", direction);
            return;
        }
        if (!source(alias, peer)) return;
        MessageDoors.inbound(pending.outbound.trace, pending.outbound.symbolic,
                TRANSPORT, pending.outbound.correlationId,
                pending.outbound.attemptId, MessageDoors.REQUEST, peer, false);
    }

    private static boolean source(Object alias, Object peer) {
        try {
            if (RuntimeTraceContext.sourceFor(peer) == null) {
                gap("HANDSHAKE_SOURCE_UNREGISTERED",
                        "original actor binder has not registered the peer");
                return false;
            }
            if (alias != peer) MessageDoors.registerSourceAlias(alias, peer);
            return true;
        } catch (RuntimeException failure) {
            gap("HANDSHAKE_SOURCE_UNRESOLVED", failure.toString());
            return false;
        }
    }

    private static int type(Object packet) { return (int) number(packet, "getType"); }
    private static boolean learnerInfo(int packetType) {
        return packetType == FOLLOWERINFO || packetType == OBSERVERINFO;
    }
    private static long zxid(Object packet) { return number(packet, "getZxid"); }

    private static long number(Object object, String method) {
        if (object == null) return Long.MIN_VALUE;
        try {
            Method getter = object.getClass().getMethod(method);
            return ((Number) getter.invoke(object)).longValue();
        } catch (ReflectiveOperationException | RuntimeException failure) {
            gap("HANDSHAKE_VALUE_UNREADABLE", method + ": " + failure);
            return Long.MIN_VALUE;
        }
    }

    private static Object field(Object object, String name) {
        if (object == null) return null;
        for (Class<?> type = object.getClass(); type != null; type = type.getSuperclass()) {
            try {
                Field member = type.getDeclaredField(name);
                member.setAccessible(true);
                return member.get(object);
            } catch (NoSuchFieldException absent) {
                // Search the superclass.
            } catch (ReflectiveOperationException | RuntimeException failure) {
                gap("HANDSHAKE_FIELD_UNREADABLE", name + ": " + failure);
                return null;
            }
        }
        return null;
    }

    private static String direction(Socket socket, boolean outbound) {
        if (socket == null || !socket.isConnected()) return null;
        return outbound ? socket.getLocalSocketAddress() + "->"
                + socket.getRemoteSocketAddress()
                : socket.getRemoteSocketAddress() + "->"
                + socket.getLocalSocketAddress();
    }

    private static void gap(String subject, String detail) {
        RowRuntime.gap(GapKind.MESSAGE_CONTEXT_REFUSED, GapClass.BLOCKING,
                TRANSPORT + ":" + subject, detail);
    }

    private static void abandon(Packet pending, String reason) {
        synchronized (LOCK) {
            ArrayDeque<Packet> queue = IN_FLIGHT.get(pending.connection);
            if (queue != null) {
                queue.remove(pending);
                if (queue.isEmpty()) IN_FLIGHT.remove(pending.connection);
            }
        }
        pending.fail(reason);
    }

    private static final class Packet {
        final Object packet;
        final int type;
        final long zxid;
        final String connection;
        final String correlation;
        final Object peer;
        final Object scope;
        final CountDownLatch done = new CountDownLatch(1);
        volatile MessageDoors.Outbound outbound;

        Packet(Object packet, int type, long zxid, String connection,
               String correlation, Object peer, Object scope) {
            this.packet = packet;
            this.type = type;
            this.zxid = zxid;
            this.connection = connection;
            this.correlation = correlation;
            this.peer = peer;
            this.scope = scope;
        }

        void fail(String reason) {
            gap("HANDSHAKE_SEND_ABORTED", connection + ": " + reason);
            done.countDown();
        }
    }
}
