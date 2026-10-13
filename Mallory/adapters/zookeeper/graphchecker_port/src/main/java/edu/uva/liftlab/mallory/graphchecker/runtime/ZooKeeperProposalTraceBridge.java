package edu.uva.liftlab.mallory.graphchecker.runtime;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.SocketAddress;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Leader proposal/commit wire receipts and the ObserverMaster proposal queue. */
public final class ZooKeeperProposalTraceBridge {
    private static final String WIRE = "ZOOKEEPER_QUORUM_PROPOSAL";
    private static final String QUEUE = "ZOOKEEPER_OBSERVER_PROPOSED";
    private static final int PROPOSAL = 2;
    private static final int COMMIT = 4;
    private static final Object LOCK = new Object();
    private static final IdentityHashMap<Object, List<Pending>> BUFFERED =
            new IdentityHashMap<Object, List<Pending>>();
    private static final Map<String, ArrayDeque<Pending>> IN_FLIGHT =
            new HashMap<String, ArrayDeque<Pending>>();
    private static final IdentityHashMap<Object, String> PROPOSED =
            new IdentityHashMap<Object, String>();
    private static long nextWire = 1;
    private static long nextProposal = 1;

    private ZooKeeperProposalTraceBridge() { }

    /** Called only after writeRecord returned; the buffer is not yet sent. */
    public static void buffered(Object handler, Object packet) {
        int type = (int) number(packet, "getType");
        if (type != PROPOSAL && type != COMMIT) return;
        Object peer = field(field(handler, "learnerMaster"), "self");
        Socket socket = (Socket) field(handler, "sock");
        String connection = direction(socket, true);
        String fingerprint = packetFingerprint(packet);
        if (peer == null || connection == null || fingerprint == null) {
            gap("PROPOSAL_WRITE_UNRESOLVED", "handler lacks peer/socket/packet");
            return;
        }
        ZooKeeperTraceBridge.registerPeer(peer);
        MessageDoors.registerSourceAlias(handler, peer);
        String correlation;
        synchronized (LOCK) { correlation = connection + "/packet/" + nextWire++; }
        long tick = MessageDoors.beginTick(peer, "QUORUM_PACKET_BUFFERED");
        MessageDoors.Outbound outbound;
        try {
            outbound = MessageDoors.prepareOutbound(WIRE, correlation, "1",
                    MessageDoors.REQUEST, peer, null);
        } finally {
            MessageDoors.endTick(tick);
        }
        Pending pending = new Pending(fingerprint, outbound);
        synchronized (LOCK) {
            BUFFERED.computeIfAbsent(handler,
                    ignored -> new ArrayList<Pending>()).add(pending);
            IN_FLIGHT.computeIfAbsent(connection,
                    ignored -> new ArrayDeque<Pending>()).addLast(pending);
        }
    }

    /** Publish every buffered packet only after BufferedOutputStream.flush succeeds. */
    public static void flushed(Object handler) {
        List<Pending> completed;
        synchronized (LOCK) { completed = BUFFERED.remove(handler); }
        if (completed == null) return;
        for (Pending pending : completed) {
            MessageDoors.sent(pending.outbound);
            pending.done.countDown();
        }
    }

    /** Called after Learner.readPacket deserializes a complete packet. */
    public static void learnerRead(Object learner, Object packet) {
        int type = (int) number(packet, "getType");
        if (type != PROPOSAL && type != COMMIT) return;
        Object peer = field(learner, "self");
        Socket socket = (Socket) field(learner, "sock");
        String connection = direction(socket, false);
        String fingerprint = packetFingerprint(packet);
        if (peer == null || connection == null || fingerprint == null) {
            gap("PROPOSAL_READ_UNRESOLVED", "learner lacks peer/socket/packet");
            return;
        }
        Pending pending;
        synchronized (LOCK) {
            ArrayDeque<Pending> queue = IN_FLIGHT.get(connection);
            pending = queue == null ? null : queue.peekFirst();
            if (pending != null && fingerprint.equals(pending.fingerprint)) {
                queue.removeFirst();
                if (queue.isEmpty()) IN_FLIGHT.remove(connection);
            } else {
                pending = null;
            }
        }
        if (pending == null) {
            gap("PROPOSAL_NO_EXACT_SEND", connection + " " + fingerprint);
            return;
        }
        try {
            if (!pending.done.await(5, TimeUnit.SECONDS)) {
                gap("PROPOSAL_SEND_UNCONFIRMED", connection);
                return;
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            gap("PROPOSAL_SEND_INTERRUPTED", connection);
            return;
        }
        ZooKeeperTraceBridge.registerPeer(peer);
        MessageDoors.registerSourceAlias(learner, peer);
        MessageDoors.inbound(pending.outbound.trace, pending.outbound.symbolic,
                WIRE, pending.outbound.correlationId, pending.outbound.attemptId,
                MessageDoors.REQUEST, peer, false);
    }

    public static void followerPacketProcessed() {
        MessageDoors.endInbound();
    }

    /** The exact queue object is a versioned in-JVM state item. */
    public static void proposalQueued(Object master, Object packet) {
        if (packet == null) return;
        Object peer = field(master, "self");
        if (peer == null) { gap("OBSERVER_OWNER_UNRESOLVED", "proposal add"); return; }
        ZooKeeperTraceBridge.registerPeer(peer);
        MessageDoors.registerSourceAlias(master, peer);
        String key;
        synchronized (LOCK) {
            key = number(peer, "getMyId") + "/" + nextProposal++ + "/"
                    + packetFingerprint(packet);
            PROPOSED.put(packet, key);
        }
        MessageDoors.stored(QUEUE, key, peer);
    }

    /** Peek precedes the target mismatch branch; no guessed zxid-only edge. */
    public static void proposalPeeked(Object master, Object packet) {
        if (packet == null) return;
        Object peer = field(master, "self");
        String key;
        synchronized (LOCK) { key = PROPOSED.get(packet); }
        if (peer == null || key == null) {
            gap("OBSERVER_QUEUE_ITEM_UNRESOLVED", "peek has no exact stored object");
            return;
        }
        ZooKeeperTraceBridge.registerPeer(peer);
        MessageDoors.registerSourceAlias(master, peer);
        MessageDoors.fetched(QUEUE, key, peer);
    }

    public static void proposalRemoved(Object packet) {
        if (packet == null) return;
        synchronized (LOCK) { PROPOSED.remove(packet); }
    }

    private static String packetFingerprint(Object packet) {
        if (packet == null) return null;
        long type = number(packet, "getType");
        long zxid = number(packet, "getZxid");
        Object raw = invoke(packet, "getData");
        if (raw != null && !(raw instanceof byte[])) return null;
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            if (raw != null) md.update((byte[]) raw);
            StringBuilder result = new StringBuilder();
            for (byte b : md.digest()) result.append(String.format("%02x", b & 0xff));
            return type + "/" + zxid + "/" + result;
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    private static String direction(Socket socket, boolean outgoing) {
        if (socket == null) return null;
        SocketAddress local = socket.getLocalSocketAddress();
        SocketAddress remote = socket.getRemoteSocketAddress();
        String source = endpoint(outgoing ? local : remote);
        String destination = endpoint(outgoing ? remote : local);
        return source == null || destination == null ? null
                : source + "->" + destination;
    }

    private static String endpoint(SocketAddress address) {
        if (!(address instanceof InetSocketAddress)) return null;
        InetSocketAddress inet = (InetSocketAddress) address;
        if (inet.getAddress() == null) return null;
        return inet.getAddress().getHostAddress() + ":" + inet.getPort();
    }

    private static long number(Object object, String method) {
        Object value = invoke(object, method);
        return value instanceof Number ? ((Number) value).longValue() : Long.MIN_VALUE;
    }

    private static Object invoke(Object object, String name) {
        if (object == null) return null;
        try {
            Method method = object.getClass().getMethod(name);
            return method.invoke(object);
        } catch (ReflectiveOperationException | RuntimeException failed) {
            gap("PROPOSAL_VALUE_UNRESOLVED", name + ":" + failed);
            return null;
        }
    }

    private static Object field(Object object, String name) {
        if (object == null) return null;
        for (Class<?> type = object.getClass(); type != null;
                type = type.getSuperclass()) {
            try {
                Field member = type.getDeclaredField(name);
                member.setAccessible(true);
                return member.get(object);
            } catch (NoSuchFieldException absent) {
                // Search the actual superclass field declaration.
            } catch (ReflectiveOperationException | RuntimeException failed) {
                gap("PROPOSAL_FIELD_UNRESOLVED", name + ":" + failed);
                return null;
            }
        }
        return null;
    }

    private static void gap(String kind, String detail) {
        MessageDoors.gap(kind, WIRE, detail);
    }

    private static final class Pending {
        final String fingerprint;
        final MessageDoors.Outbound outbound;
        final CountDownLatch done = new CountDownLatch(1);

        Pending(String fingerprint, MessageDoors.Outbound outbound) {
            this.fingerprint = fingerprint;
            this.outbound = outbound;
        }
    }
}
