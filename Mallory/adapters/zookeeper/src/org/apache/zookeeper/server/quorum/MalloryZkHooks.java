package org.apache.zookeeper.server.quorum;

import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.net.Socket;
import java.util.ArrayDeque;
import java.util.Map;
import java.util.WeakHashMap;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import org.apache.jute.BinaryInputArchive;
import org.apache.jute.BinaryOutputArchive;
import org.apache.jute.Record;
import org.apache.zookeeper.server.Request;

/** Minimal quorum adapter. Installed only in an isolated test source tree. */
public final class MalloryZkHooks {
    private static final String PROBE = "edu.uva.liftlab.mallory.instrumentation.Probe";
    private static final String TRANSPORT = "zookeeper-quorum-tcp";
    private static final String READ_DOOR = "zookeeper.quorum.archive.readRecord";
    private static final String WRITE_DOOR = "zookeeper.quorum.archive.writeRecord";
    private static final Map<Long, AtomicInteger> EPOCHS = new ConcurrentHashMap<>();
    private static final Map<Socket, Counts> COUNTS = new WeakHashMap<>();
    private static final Map<Request, ArrayDeque<String>> TASK_TOKENS = new WeakHashMap<>();
    private static final AtomicLong NEXT_TASK = new AtomicLong();

    private MalloryZkHooks() { }

    static void startPeer(QuorumPeer peer) {
        EPOCHS.computeIfAbsent(peer.getMyId(), ignored -> new AtomicInteger(-1)).incrementAndGet();
        node(peer.getMyId());
    }

    public static void node(long sid) {
        // A failed owner lookup must remain unknown, never become a named zk-1.
        if (sid < 0) return;
        AtomicInteger epoch = EPOCHS.get(sid);
        call("setNode", new Class<?>[] {String.class, int.class}, "zk" + sid,
             epoch == null ? 0 : epoch.get());
    }

    static long masterId(LearnerMaster master) {
        if (master instanceof Leader) return ((Leader) master).self.getMyId();
        try {
            Field field = master.getClass().getDeclaredField("self");
            field.setAccessible(true);
            return ((QuorumPeer) field.get(master)).getMyId();
        } catch (ReflectiveOperationException | SecurityException unavailable) {
            return -1;
        }
    }

    static BinaryInputArchive input(InputStream stream, Socket socket, long sid) {
        return new Input(new DataInputStream(stream), socket, sid);
    }

    static BinaryOutputArchive output(OutputStream stream, Socket socket, long sid) {
        return new Output(new DataOutputStream(stream), socket, sid);
    }

    public static void submit(Request request, long sid, String site) {
        if (request == null || request == Request.requestOfDeath) return;
        node(sid);
        String token = "zk-request:" + sid + ":" + NEXT_TASK.incrementAndGet();
        synchronized (TASK_TOKENS) {
            ArrayDeque<String> queue = TASK_TOKENS.get(request);
            if (queue == null) { queue = new ArrayDeque<>(); TASK_TOKENS.put(request, queue); }
            queue.addLast(token);
        }
        call("taskSubmit", new Class<?>[] {String.class, String.class}, token, site);
    }

    public static Scope claim(Request request, long sid, String site) {
        node(sid);
        String token = null;
        synchronized (TASK_TOKENS) {
            ArrayDeque<String> queue = TASK_TOKENS.get(request);
            if (queue != null) {
                token = queue.pollFirst();
                if (queue.isEmpty()) TASK_TOKENS.remove(request);
            }
        }
        Object context = invoke("taskClaim", new Class<?>[] {String.class, String.class}, token, site);
        return new Scope(context instanceof AutoCloseable ? (AutoCloseable) context : null);
    }

    public static final class Scope implements AutoCloseable {
        private final AutoCloseable context;
        private Scope(AutoCloseable context) { this.context = context; }
        @Override public void close() {
            if (context == null) return;
            try { context.close(); }
            catch (Exception failure) { throw new IllegalStateException("Mallory task scope", failure); }
        }
    }

    private static final class Counts {
        long sent;
        long received;
    }

    private static String correlation(Socket socket, QuorumPacket packet, boolean sending) {
        if (socket == null || !socket.isConnected()) return null;
        String local = socket.getLocalAddress().getHostAddress() + ":" + socket.getLocalPort();
        String remote = socket.getInetAddress().getHostAddress() + ":" + socket.getPort();
        String direction = sending ? local + ">" + remote : remote + ">" + local;
        long ordinal;
        synchronized (COUNTS) {
            Counts counts = COUNTS.get(socket);
            if (counts == null) { counts = new Counts(); COUNTS.put(socket, counts); }
            ordinal = sending ? ++counts.sent : ++counts.received;
        }
        return direction + "#" + ordinal + ":" + packet.getType() + ":" + packet.getZxid();
    }

    private static void packet(Socket socket, long sid, Record record, boolean sending) {
        if (!(record instanceof QuorumPacket)) return;
        node(sid);
        QuorumPacket packet = (QuorumPacket) record;
        String correlation = correlation(socket, packet, sending);
        if (correlation == null) return;
        String port = packet.getType() + ":" + packet.getZxid();
        call(sending ? "send" : "receive",
             new Class<?>[] {String.class, String.class, String.class, String.class},
             TRANSPORT, correlation, port, sending ? WRITE_DOOR : READ_DOOR);
    }

    private static void beforeDoor(String site) throws IOException {
        try {
            Class<?> probe = Class.forName(PROBE);
            probe.getMethod("beforeDoor", String.class).invoke(null, site);
        } catch (ClassNotFoundException absent) {
            // A plain ZooKeeper build remains runnable without the Mallory agent.
        } catch (InvocationTargetException injected) {
            Throwable cause = injected.getCause();
            if (cause instanceof IOException) throw (IOException) cause;
            if (cause instanceof RuntimeException) throw (RuntimeException) cause;
            if (cause instanceof Error) throw (Error) cause;
            throw new IOException(cause);
        } catch (ReflectiveOperationException unavailable) {
            throw new IllegalStateException("Mallory probe API mismatch", unavailable);
        }
    }

    private static void call(String method, Class<?>[] parameters, Object... args) {
        invoke(method, parameters, args);
    }

    private static Object invoke(String method, Class<?>[] parameters, Object... args) {
        try {
            Class<?> probe = Class.forName(PROBE);
            Method hook = probe.getMethod(method, parameters);
            return hook.invoke(null, args);
        } catch (ClassNotFoundException absent) {
            // Keep uninstrumented tests usable.
            return null;
        } catch (ReflectiveOperationException unavailable) {
            throw new IllegalStateException("Mallory probe API mismatch: " + method, unavailable);
        }
    }

    private static final class Input extends BinaryInputArchive {
        private final Socket socket;
        private final long sid;

        Input(DataInputStream stream, Socket socket, long sid) {
            super(stream);
            this.socket = socket;
            this.sid = sid;
        }

        @Override public void readRecord(Record record, String tag) throws IOException {
            node(sid);
            if (record instanceof QuorumPacket) beforeDoor(READ_DOOR);
            super.readRecord(record, tag);
            packet(socket, sid, record, false);
        }
    }

    private static final class Output extends BinaryOutputArchive {
        private final Socket socket;
        private final long sid;

        Output(DataOutputStream stream, Socket socket, long sid) {
            super(stream);
            this.socket = socket;
            this.sid = sid;
        }

        @Override public void writeRecord(Record record, String tag) throws IOException {
            node(sid);
            if (record instanceof QuorumPacket) beforeDoor(WRITE_DOOR);
            super.writeRecord(record, tag);
            packet(socket, sid, record, true);
        }
    }
}
