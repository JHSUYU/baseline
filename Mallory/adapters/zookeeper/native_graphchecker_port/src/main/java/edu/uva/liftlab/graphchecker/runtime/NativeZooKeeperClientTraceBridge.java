package edu.uva.liftlab.graphchecker.runtime;

import edu.uva.liftlab.graphchecker.contract.GapClass;
import edu.uva.liftlab.graphchecker.contract.GapKind;

import java.lang.reflect.Field;
import java.net.SocketAddress;
import java.net.InetSocketAddress;
import java.nio.ByteBuffer;
import java.nio.channels.SelectionKey;
import java.nio.channels.SocketChannel;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayDeque;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Exact, in-JVM receipts for ZooKeeper's framed NIO client protocol. */
public final class NativeZooKeeperClientTraceBridge {
    private static final String TRANSPORT = "ZOOKEEPER_CLIENT_NIO";
    private static final Object LOCK = new Object();
    private static final IdentityHashMap<Object, Pending> BY_PACKET =
            new IdentityHashMap<Object, Pending>();
    private static final Map<String, ArrayDeque<Pending>> BY_CONNECTION =
            new java.util.HashMap<String, ArrayDeque<Pending>>();
    private static final IdentityHashMap<Object, Object> SERVER_OWNER =
            new IdentityHashMap<Object, Object>();
    private static long nextFrame = 1;
    private static long nextServer = 1;

    private NativeZooKeeperClientTraceBridge() { }

    /** Called after Packet.createBB, before the first socket write. */
    public static void clientPrepared(Object socket, Object packet) {
        if (socket == null || packet == null) return;
        synchronized (LOCK) {
            if (BY_PACKET.containsKey(packet)) return;
        }
        SocketChannel channel = clientChannel(socket);
        ByteBuffer framed = (ByteBuffer) field(packet, "bb");
        String connection = channel == null ? null : direction(channel, true);
        String fingerprint = digest(framed, true);
        if (connection == null || fingerprint == null) {
            gap("CLIENT_FRAME_UNRESOLVED", "createBB has no connected channel/frame");
            return;
        }
        String correlation;
        synchronized (LOCK) {
            correlation = connection + "/frame/" + nextFrame++;
        }
        // ClientCnxnSocketNIO is reused across reconnects. The channel is
        // the actual per-connection owner; a new channel gets a new identity.
        MessageDoors.registerSource(channel, "ZOOKEEPER_CLIENT", "CLIENT",
                connection.substring(0, connection.indexOf("->")), 0);
        // A prepared frame is not a SEND. Native GraphChecker publishes its
        // outbound receipt only after the complete socket write succeeds.
        Pending pending = new Pending(connection, fingerprint, correlation,
                channel);
        synchronized (LOCK) {
            if (BY_PACKET.containsKey(packet)) return;
            BY_PACKET.put(packet, pending);
            BY_CONNECTION.computeIfAbsent(connection,
                    ignored -> new ArrayDeque<Pending>()).addLast(pending);
        }
    }

    /** Called only after complete write/removal, or a complete direct send. */
    public static void clientSent(Object socket, Object packet) {
        if (socket == null || packet == null) return;
        ByteBuffer framed = (ByteBuffer) field(packet, "bb");
        if (framed == null || framed.hasRemaining()) return;
        Pending pending;
        synchronized (LOCK) {
            pending = BY_PACKET.remove(packet);
        }
        if (pending == null) {
            gap("CLIENT_SEND_UNPREPARED", "completed frame has no prepared receipt");
            return;
        }
        long tick = MessageDoors.beginTick(pending.owner, "CLIENT_FRAME_SEND");
        try {
            pending.outbound = MessageDoors.outbound(TRANSPORT,
                    pending.correlation, "1", MessageDoors.REQUEST,
                    pending.owner, null);
        } finally {
            MessageDoors.endTick(tick);
        }
        pending.done.countDown();
    }

    /** Called with a complete, flipped payload before connect/request dispatch. */
    public static void serverRead(Object connection, Object payload) {
        try {
            serverReadImpl(connection, payload);
        } catch (Throwable instrumentationFailure) {
            gap("SERVER_FRAME_HOOK_FAILED", instrumentationFailure.toString());
        }
    }

    private static void serverReadImpl(Object connection, Object payload) {
        if (!(payload instanceof ByteBuffer)) {
            gap("SERVER_FRAME_UNRESOLVED", "payload is not a ByteBuffer");
            return;
        }
        SocketChannel channel = (SocketChannel) field(connection, "sock");
        String direction = channel == null ? null : direction(channel, false);
        String fingerprint = digest((ByteBuffer) payload, false);
        if (direction == null || fingerprint == null) {
            gap("SERVER_FRAME_UNRESOLVED", "complete frame has no socket/payload");
            return;
        }
        Pending pending;
        synchronized (LOCK) {
            ArrayDeque<Pending> queue = BY_CONNECTION.get(direction);
            pending = queue == null ? null : queue.peekFirst();
            if (pending != null && fingerprint.equals(pending.fingerprint)) {
                queue.removeFirst();
                if (queue.isEmpty()) BY_CONNECTION.remove(direction);
            } else {
                pending = null;
            }
        }
        if (pending == null) {
            gap("CLIENT_FRAME_NO_EXACT_SEND", direction + " payload=" + fingerprint);
            return;
        }
        try {
            if (!pending.done.await(5, TimeUnit.SECONDS)) {
                gap("CLIENT_FRAME_SEND_UNCONFIRMED", direction);
                return;
            }
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            gap("CLIENT_FRAME_SEND_INTERRUPTED", direction);
            return;
        }
        Object server = field(connection, "zkServer");
        Object owner = bindServer(server);
        if (owner == null) {
            gap("CLIENT_FRAME_SERVER_UNRESOLVED", direction);
            return;
        }
        // A completed client frame is already sufficient to identify the
        // installed tracker.  Bind it here so the transport pass does not
        // rewrite ZooKeeperServer's unrelated lifecycle methods.
        serverTrackerCreated(server);
        MessageDoors.registerSourceAlias(connection, owner);
        if (pending.outbound == null || !pending.outbound.active()) return;
        MessageDoors.inbound(pending.outbound.trace, pending.outbound.symbolic,
                TRANSPORT, pending.outbound.correlationId,
                pending.outbound.attemptId, MessageDoors.REQUEST, owner, false);
    }

    /** The inbound context must not leak into the next NIO request. */
    public static void serverReadExited() {
        MessageDoors.endInbound();
    }

    /** Bind the tracker actually installed by ZooKeeperServer.createSessionTracker. */
    public static void serverTrackerCreated(Object server) {
        Object owner = bindServer(server);
        Object tracker = field(server, "sessionTracker");
        if (owner == null || tracker == null) {
            gap("SESSION_TRACKER_UNRESOLVED", "server has no installed tracker");
            return;
        }
        bindTracker(tracker, owner);
        bindTracker(field(tracker, "localSessionTracker"), owner);
        bindTracker(field(tracker, "globalSessionTracker"), owner);
    }

    /** Exact installed-owner lookup for a selected tracker/server target. */
    public static Object ownerForTarget(Object actor) {
        synchronized (LOCK) {
            return SERVER_OWNER.get(actor);
        }
    }

    private static void bindTracker(Object tracker, Object owner) {
        if (tracker == null) return;
        synchronized (LOCK) { SERVER_OWNER.put(tracker, owner); }
        MessageDoors.registerSourceAlias(tracker, owner);
    }

    private static Object bindServer(Object server) {
        if (server == null) return null;
        Object peer = field(server, "self");
        Object owner = peer == null ? server : peer;
        if (peer != null) {
            if (RuntimeTraceContext.sourceFor(peer) == null) {
                Long id = peerId(peer);
                if (id == null) {
                    gap("SERVER_PEER_ID_UNRESOLVED", peer.getClass().getName());
                    return null;
                }
                MessageDoors.registerSource(peer, "ZOOKEEPER_PEER", "SERVER",
                        "zk-peer-" + id, 0);
            }
            MessageDoors.registerSourceAlias(server, peer);
        } else {
            long ordinal;
            synchronized (LOCK) {
                if (SERVER_OWNER.containsKey(server)) return SERVER_OWNER.get(server);
                ordinal = nextServer++;
                SERVER_OWNER.put(server, server);
            }
            MessageDoors.registerSource(server, "ZOOKEEPER_SERVER", "SERVER",
                    "zk-standalone-" + ordinal, 0);
        }
        synchronized (LOCK) { SERVER_OWNER.put(server, owner); }
        return owner;
    }

    private static Long peerId(Object peer) {
        try {
            Object id = peer.getClass().getMethod("getMyId").invoke(peer);
            return id instanceof Number ? ((Number) id).longValue() : null;
        } catch (ReflectiveOperationException unavailable) {
            return null;
        }
    }

    private static SocketChannel clientChannel(Object socket) {
        SelectionKey key = (SelectionKey) field(socket, "sockKey");
        return key == null ? null : (SocketChannel) key.channel();
    }

    private static String direction(SocketChannel channel, boolean outgoing) {
        try {
            SocketAddress local = channel.getLocalAddress();
            SocketAddress remote = channel.getRemoteAddress();
            if (local == null || remote == null) return null;
            String source = socketAddress(outgoing ? local : remote);
            String destination = socketAddress(outgoing ? remote : local);
            return source == null || destination == null ? null
                    : source + "->" + destination;
        } catch (java.io.IOException | RuntimeException failed) {
            gap("CLIENT_SOCKET_UNRESOLVED", failed.toString());
            return null;
        }
    }

    private static String socketAddress(SocketAddress address) {
        if (!(address instanceof InetSocketAddress)) return null;
        InetSocketAddress inet = (InetSocketAddress) address;
        if (inet.getAddress() == null) return null;
        // SocketAddress.toString() preserves the caller's hostname on one
        // side, e.g. localhost/127.0.0.1 versus /127.0.0.1. The actual
        // connected IP and port are the same wire endpoint on both sides.
        return inet.getAddress().getHostAddress() + ":" + inet.getPort();
    }

    private static String digest(ByteBuffer bytes, boolean framed) {
        if (bytes == null) return null;
        ByteBuffer copy = bytes.asReadOnlyBuffer();
        if (framed) {
            if (copy.limit() < 4) return null;
            int length = copy.getInt(0);
            if (length != copy.limit() - 4) return null;
            copy.position(4);
        } else {
            copy.position(0);
        }
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            md.update(copy);
            byte[] digest = md.digest();
            StringBuilder result = new StringBuilder(digest.length * 2);
            for (byte b : digest) result.append(String.format("%02x", b & 0xff));
            return result.toString();
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
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
                // Continue through superclass; no inferred owner on absence.
            } catch (ReflectiveOperationException | RuntimeException failed) {
                gap("REFLECTION_UNRESOLVED", name + ":" + failed);
                return null;
            }
        }
        return null;
    }

    private static void gap(String kind, String detail) {
        RowRuntime.gap(GapKind.LINEAGE_LOST, GapClass.DIAGNOSTIC,
                TRANSPORT + ":" + kind, detail);
    }

    private static final class Pending {
        final String connection;
        final String fingerprint;
        final String correlation;
        final Object owner;
        volatile MessageDoors.Outbound outbound;
        final CountDownLatch done = new CountDownLatch(1);

        Pending(String connection, String fingerprint,
                String correlation, Object owner) {
            this.connection = connection;
            this.fingerprint = fingerprint;
            this.correlation = correlation;
            this.owner = owner;
        }
    }
}
