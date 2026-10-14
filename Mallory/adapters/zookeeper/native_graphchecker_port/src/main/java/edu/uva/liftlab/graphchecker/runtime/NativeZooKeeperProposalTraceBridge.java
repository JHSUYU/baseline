package edu.uva.liftlab.graphchecker.runtime;

import edu.uva.liftlab.graphchecker.contract.GapClass;
import edu.uva.liftlab.graphchecker.contract.GapKind;
import edu.uva.liftlab.graphchecker.contract.LocationId;
import edu.uva.liftlab.graphchecker.contract.LocationKind;
import edu.uva.liftlab.graphchecker.contract.ReadRow;

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
public final class NativeZooKeeperProposalTraceBridge {
    private static final String WIRE = "ZOOKEEPER_QUORUM_PROPOSAL";
    private static final String QUEUE = "ZOOKEEPER_OBSERVER_PROPOSED";
    private static final int PROPOSAL = 2;
    private static final int COMMIT = 4;
    private static final Object LOCK = new Object();
    private static final IdentityHashMap<Object, List<Pending>> BUFFERED =
            new IdentityHashMap<Object, List<Pending>>();
    private static final Map<String, ArrayDeque<Pending>> IN_FLIGHT =
            new HashMap<String, ArrayDeque<Pending>>();
    private static final IdentityHashMap<Object, ProposalVersion> PROPOSED =
            new IdentityHashMap<Object, ProposalVersion>();
    private static long nextWire = 1;
    private static long nextProposal = 1;

    private NativeZooKeeperProposalTraceBridge() { }

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
        MessageDoors.registerSourceAlias(handler, peer);
        String correlation;
        synchronized (LOCK) { correlation = connection + "/packet/" + nextWire++; }
        // Native GraphChecker must see no SEND while the bytes only sit in
        // BufferedOutputStream. Publication happens in flushed() below.
        Pending pending = new Pending(fingerprint, correlation, peer);
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
            long tick = MessageDoors.beginTick(pending.owner,
                    "QUORUM_PACKET_FLUSHED");
            try {
                pending.outbound = MessageDoors.outbound(WIRE,
                        pending.correlation, "1", MessageDoors.REQUEST,
                        pending.owner, null);
            } finally {
                MessageDoors.endTick(tick);
            }
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
        MessageDoors.registerSourceAlias(learner, peer);
        if (pending.outbound == null || !pending.outbound.active()) return;
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
        MessageDoors.registerSourceAlias(master, peer);
        ProposalVersion version;
        synchronized (LOCK) {
            long ordinal = nextProposal++;
            String item = "proposal-" + ordinal;
            LocationId location = LocationId.of(LocationKind.MAP,
                    "zk-peer-" + number(peer, "getMyId"), item);
            version = new ProposalVersion(location, item + "@0");
            PROPOSED.put(packet, version);
        }
        String source = RuntimeTraceContext.ownedSource(peer).key();
        RowRuntime.write(RowRuntime.occurrenceHere(source, QUEUE), 0L,
                "org.apache.zookeeper.server.quorum.ObserverMaster"
                        + "#proposalReceived#queue-add", version.location, 1L,
                null, "Lorg/apache/zookeeper/server/quorum/QuorumPacket;",
                version.index, null, null, false);
    }

    /** Peek precedes the target mismatch branch; no guessed zxid-only edge. */
    public static void proposalPeeked(Object master, Object packet) {
        if (packet == null) return;
        Object peer = field(master, "self");
        ProposalVersion version;
        synchronized (LOCK) { version = PROPOSED.get(packet); }
        if (peer == null || version == null) {
            gap("OBSERVER_QUEUE_ITEM_UNRESOLVED", "peek has no exact stored object");
            return;
        }
        MessageDoors.registerSourceAlias(master, peer);
        String source = RuntimeTraceContext.ownedSource(peer).key();
        RowRuntime.read(RowRuntime.occurrenceHere(source, QUEUE), 0L,
                "org.apache.zookeeper.server.quorum.ObserverMaster"
                        + "#removeProposedPacket#queue-peek",
                version.location, 1L, "",
                "Lorg/apache/zookeeper/server/quorum/QuorumPacket;", "",
                version.index, ReadRow.UNKNOWN_VERSION);
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
        RowRuntime.gap(GapKind.LINEAGE_LOST, GapClass.DIAGNOSTIC,
                WIRE + ":" + kind, detail);
    }

    private static final class ProposalVersion {
        final LocationId location;
        final String index;

        ProposalVersion(LocationId location, String index) {
            this.location = location;
            this.index = index;
        }
    }

    private static final class Pending {
        final String fingerprint;
        final String correlation;
        final Object owner;
        volatile MessageDoors.Outbound outbound;
        final CountDownLatch done = new CountDownLatch(1);

        Pending(String fingerprint, String correlation, Object owner) {
            this.fingerprint = fingerprint;
            this.correlation = correlation;
            this.owner = owner;
        }
    }
}
