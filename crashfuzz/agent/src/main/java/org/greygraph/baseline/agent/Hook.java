package org.greygraph.baseline.agent;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.lang.ref.ReferenceQueue;
import java.lang.ref.WeakReference;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Properties;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/** Runtime event protocol, deliberately independent of system-specific code. */
public final class Hook {
    private static final Object TRACE_LOCK = new Object();
    private static final Object TASK_LOCK = new Object();
    private static final AtomicLong SEQUENCE = new AtomicLong();
    private static final AtomicLong SPANS = new AtomicLong();
    private static final AtomicLong TASKS = new AtomicLong();
    private static final String PROCESS = UUID.randomUUID().toString();
    private static final ThreadLocal<Deque<Frame>> STACK =
            new ThreadLocal<Deque<Frame>>() {
                @Override protected Deque<Frame> initialValue() {
                    return new ArrayDeque<Frame>();
                }
            };
    private static final Map<Object, Deque<Transfer>> SUBMISSIONS =
            new java.util.IdentityHashMap<Object, Deque<Transfer>>();
    private static final Map<String, Integer> ROOT_COUNTS =
            new HashMap<String, Integer>();
    private static final WeakIds OBJECT_IDS = new WeakIds();
    private static final Set<String> GLOBAL_BLOCKS = Collections.newSetFromMap(
            new ConcurrentHashMap<String, Boolean>());
    private static final Set<String> GLOBAL_BRANCHES = Collections.newSetFromMap(
            new ConcurrentHashMap<String, Boolean>());

    private static String node;
    private static String targetGuard;
    private static String targetEntry;
    private static String targetThrow;
    private static String targetException;
    private static final Set<String> POINT_ENTRIES = new HashSet<String>();
    private static boolean fatalBranchTaken;
    private static String controllerHost;
    private static int controllerPort;
    private static FileOutputStream traceStream;
    private static BufferedWriter traceWriter;

    private Hook() { }

    static void configure(Properties options) {
        node = required(options, "node.id", "ADHOCFUZZ_NODE_ID");
        String traceDirectory = required(options, "trace.dir",
                "ADHOCFUZZ_TRACE_DIR");
        targetGuard = options.getProperty("target.guard", "").trim();
        targetEntry = options.getProperty("target.entry", "").trim();
        targetThrow = options.getProperty("target.throw", "").trim();
        targetException = options.getProperty("target.exception", "").trim();
        POINT_ENTRIES.clear();
        for (String entry : options.getProperty("point.entries", "").split(",")) {
            if (!entry.trim().isEmpty()) POINT_ENTRIES.add(entry.trim());
        }
        if (!targetEntry.isEmpty() && targetThrow.isEmpty()) {
            throw new IllegalArgumentException("target.entry requires target.throw");
        }
        fatalBranchTaken = Boolean.parseBoolean(
                options.getProperty("target.fatal.taken", "true"));
        controllerHost = value(options, "controller.host",
                "ADHOCFUZZ_CONTROLLER_HOST", "");
        String port = value(options, "controller.port",
                "ADHOCFUZZ_CONTROLLER_PORT", "0");
        controllerPort = Integer.parseInt(port);
        if (controllerPort < 0 || controllerPort > 65535) {
            throw new IllegalArgumentException("controller.port is invalid");
        }
        try {
            Path directory = Paths.get(traceDirectory);
            Files.createDirectories(directory);
            Path file = directory.resolve("trace-" + safe(node)
                    + "-" + PROCESS + ".jsonl");
            traceStream = new FileOutputStream(file.toFile());
            traceWriter = new BufferedWriter(new OutputStreamWriter(
                    traceStream, StandardCharsets.UTF_8), 65536);
        } catch (IOException error) {
            throw new IllegalStateException("cannot create trace", error);
        }
        emit("BOOT", "agent", null, null, true);
        Runtime.getRuntime().addShutdownHook(new Thread(new Runnable() {
            @Override public void run() { flush(true); }
        }, "adhoc-crashfuzz-trace-close"));
    }

    private static String required(Properties options, String property,
                                   String environment) {
        String result = value(options, property, environment, "");
        if (result.isEmpty()) throw new IllegalArgumentException(
                property + " or " + environment + " is required");
        return result;
    }

    private static String value(Properties options, String property,
                                String environment, String fallback) {
        String configured = options.getProperty(property);
        if (configured != null && !configured.trim().isEmpty())
            return configured.trim();
        configured = System.getenv(environment);
        return configured == null || configured.trim().isEmpty()
                ? fallback : configured.trim();
    }

    private static String safe(String value) {
        return value.replaceAll("[^A-Za-z0-9_.-]", "_");
    }

    private static final class Frame {
        final long span;
        final long parent;
        final String site;
        final String context;
        final Map<String, Integer> counts = new HashMap<String, Integer>();
        final Set<String> coveredBlocks = new HashSet<String>();

        Frame(long span, long parent, String site, String context) {
            this.span = span;
            this.parent = parent;
            this.site = site;
            this.context = context;
        }

        int next(String key) {
            Integer before = counts.get(key);
            int after = before == null ? 1 : before + 1;
            counts.put(key, after);
            return after;
        }
    }

    private static final class Transfer {
        final String correlation;
        final String context;
        Transfer(String correlation, String context) {
            this.correlation = correlation;
            this.context = context;
        }
    }

    public static long enter(String site, Object receiver) {
        return enter0(site, receiver, false);
    }

    /** Enter a worker operation using the submitted task as its handoff key. */
    public static long enterTask(String site, Object task) {
        return enter0(site, task, true);
    }

    private static long enter0(String site, Object receiver,
                               boolean consumeSubmitted) {
        Deque<Frame> stack = STACK.get();
        Frame parent = stack.peek();
        Transfer transfer = null;
        if (receiver != null && (consumeSubmitted || site.contains("#run(")
                || site.contains("#call("))) {
            synchronized (TASK_LOCK) {
                Deque<Transfer> pending = SUBMISSIONS.get(receiver);
                if (pending != null) {
                    transfer = pending.pollFirst();
                    if (pending.isEmpty()) SUBMISSIONS.remove(receiver);
                }
            }
        }
        String base;
        if (transfer != null) {
            // The correlation includes a fresh process UUID for exact graph
            // pairing. Replay identity must use the stable submission path.
            base = transfer.context;
        } else if (parent != null) {
            base = parent.context;
        } else {
            base = "root";
        }
        int count;
        if (parent != null) count = parent.next("child:" + site);
        else if (transfer != null) count = 1;
        else {
            synchronized (ROOT_COUNTS) {
                Integer before = ROOT_COUNTS.get(site);
                count = before == null ? 1 : before + 1;
                ROOT_COUNTS.put(site, count);
            }
        }
        // Bound the context sent on each fault point. The exact span and
        // process identity remain in the local trace.
        String context = base + "/" + site + "#" + count;
        if (context.length() > 1024) context = context.substring(
                context.length() - 1024);
        Frame frame = new Frame(SPANS.incrementAndGet(),
                parent == null ? 0L : parent.span, site, context);
        stack.push(frame);
        emit("METHOD_ENTER", site, frame, null, false);
        if (POINT_ENTRIES.contains(site)) point(site + "#ENTRY", "BEFORE");
        if (site.equals(targetEntry)) {
            // Candidate discovery can anchor on entry when a Jimple guard
            // cannot be mapped unambiguously to an ASM branch. Fatality is
            // still reported only by the exact throw location below.
            target(targetThrow, false);
        }
        if (transfer != null) {
            Map<String, Object> fields = new LinkedHashMap<String, Object>();
            fields.put("correlation", transfer.correlation);
            emit("ASYNC_RECV", site, frame, fields, false);
        }
        return frame.span;
    }

    public static void exit(long span) {
        Deque<Frame> stack = STACK.get();
        Frame frame = stack.peek();
        if (frame == null || frame.span != span) {
            throw new IllegalStateException("method scope mismatch at span " + span);
        }
        emit("METHOD_EXIT", frame.site, frame, null, false);
        stack.pop();
    }

    public static void fieldRead(String site, Object receiver) {
        field("FIELD_READ", site, receiver);
    }

    public static void fieldWrite(String site, Object receiver) {
        field("FIELD_WRITE", site, receiver);
    }

    private static void field(String kind, String site, Object receiver) {
        Map<String, Object> fields = new LinkedHashMap<String, Object>();
        fields.put("location", site + "@" + OBJECT_IDS.id(receiver));
        emit(kind, site, STACK.get().peek(), fields, false);
    }

    public static void branch(String site, boolean taken) {
        Map<String, Object> fields = new LinkedHashMap<String, Object>();
        fields.put("outcome", Boolean.toString(taken));
        Frame frame = STACK.get().peek();
        emit("BRANCH", site, frame, fields, false);
        if (site.equals(targetGuard)) {
            // With an exact target.throw, only observing the actual throw
            // declares a fatal target; this row roots the healthy seed too.
            target(targetGuard, targetThrow.isEmpty()
                    && taken == fatalBranchTaken);
        }
    }

    /** One event per basic block and invocation; repeated loop hits are cheap. */
    public static void block(String site) {
        Frame frame = STACK.get().peek();
        if (frame == null) {
            // Constructors can execute instructions before their first
            // super() call, before AdviceAdapter creates a method span.
            emit("BLOCK", site, null, null, false);
        } else if (frame.coveredBlocks.add(site)) {
            emit("BLOCK", site, frame, null, false);
        }
    }

    /** Coverage-only classes do not create causal regions or per-hit traces. */
    public static void globalBlock(String site) {
        if (!GLOBAL_BLOCKS.add(site)) return;
        emit("GLOBAL_BLOCK", site, null, null, false);
        flush(false);
    }

    public static void globalBranch(String site, boolean taken) {
        if (!GLOBAL_BRANCHES.add(site + "|" + taken)) return;
        Map<String, Object> fields = new LinkedHashMap<String, Object>();
        fields.put("outcome", Boolean.toString(taken));
        emit("GLOBAL_BRANCH", site, null, fields, false);
        flush(false);
    }

    public static void throwing(String site, Throwable throwable) {
        Map<String, Object> fields = new LinkedHashMap<String, Object>();
        fields.put("exception_type", throwable.getClass().getName());
        emit("THROW", site, STACK.get().peek(), fields, false);
        if (!targetThrow.isEmpty() && site.equals(targetThrow)) {
            target(targetGuard.isEmpty() ? targetThrow : targetGuard, true);
        }
    }

    /** Record an exception escaping a selected call site in the target method. */
    public static void callThrown(String site, Throwable throwable) {
        Map<String, Object> fields = new LinkedHashMap<String, Object>();
        fields.put("exception_type", throwable.getClass().getName());
        emit("THROW", site, STACK.get().peek(), fields, false);
        target(site, targetException.isEmpty()
                || throwable.getClass().getName().equals(targetException));
    }

    /** An adapter can report a healthy or fatal target without branch weaving. */
    public static void target(String site, boolean fatal) {
        Map<String, Object> fields = new LinkedHashMap<String, Object>();
        fields.put("fatal", fatal);
        emit("TARGET", site, STACK.get().peek(), fields, fatal);
        if (!fatal) flush(false);
    }

    /** A transport adapter names a request/response correlation at both ends. */
    public static void messageSend(String correlation) {
        message("MESSAGE_SEND", correlation);
    }

    public static void messageReceive(String correlation) {
        message("MESSAGE_RECV", correlation);
    }

    private static void message(String kind, String correlation) {
        if (correlation == null || correlation.isEmpty())
            throw new IllegalArgumentException("message correlation is empty");
        Frame frame = STACK.get().peek();
        Map<String, Object> fields = new LinkedHashMap<String, Object>();
        fields.put("correlation", correlation);
        emit(kind, frame == null ? "<ambient>" : frame.site,
                frame, fields, false);
        // The workload may finish while server JVMs remain alive. Publish
        // correlation events without paying for an fsync on every RPC.
        flush(false);
    }

    public static void asyncSubmit(Object task) {
        if (task == null) return;
        Frame frame = STACK.get().peek();
        String correlation = PROCESS + ":task:" + TASKS.incrementAndGet();
        String base = frame == null ? "root" : frame.context;
        String taskType = task.getClass().getName();
        int submitOrdinal;
        if (frame != null) submitOrdinal = frame.next("submit:" + taskType);
        else {
            synchronized (ROOT_COUNTS) {
                String key = "submit:" + taskType;
                Integer before = ROOT_COUNTS.get(key);
                submitOrdinal = before == null ? 1 : before + 1;
                ROOT_COUNTS.put(key, submitOrdinal);
            }
        }
        String context = base + "/async:" + taskType + "#" + submitOrdinal;
        synchronized (TASK_LOCK) {
            Deque<Transfer> pending = SUBMISSIONS.get(task);
            if (pending == null) {
                pending = new ArrayDeque<Transfer>();
                SUBMISSIONS.put(task, pending);
            }
            pending.addLast(new Transfer(correlation, context));
        }
        Map<String, Object> fields = new LinkedHashMap<String, Object>();
        fields.put("correlation", correlation);
        emit("ASYNC_SEND", frame == null ? "<ambient>" : frame.site,
                frame, fields, false);
    }

    /** Complete a handoff in a method that waits for an RPC response. */
    public static void asyncReceive(Object task) {
        if (task == null) return;
        Transfer transfer;
        synchronized (TASK_LOCK) {
            Deque<Transfer> pending = SUBMISSIONS.get(task);
            transfer = pending == null ? null : pending.pollFirst();
            if (pending != null && pending.isEmpty()) SUBMISSIONS.remove(task);
        }
        if (transfer == null) return;
        Frame frame = STACK.get().peek();
        Map<String, Object> fields = new LinkedHashMap<String, Object>();
        fields.put("correlation", transfer.correlation);
        emit("ASYNC_RECV", frame == null ? "<ambient>" : frame.site,
                frame, fields, false);
    }

    public static void point(String site, String phase) {
        Frame frame = STACK.get().peek();
        String context = frame == null ? "root" : frame.context;
        String countKey = site + "|" + phase;
        int ordinal;
        if (frame != null) ordinal = frame.next(countKey);
        else {
            synchronized (ROOT_COUNTS) {
                Integer before = ROOT_COUNTS.get(countKey);
                ordinal = before == null ? 1 : before + 1;
                ROOT_COUNTS.put(countKey, ordinal);
            }
        }
        Map<String, Object> fields = new LinkedHashMap<String, Object>();
        fields.put("ordinal", ordinal);
        fields.put("phase", phase);
        Map<String, Object> event = emit("FAULT_POINT", site, frame,
                fields, true);
        if (controllerPort == 0) return;
        try (Socket socket = new Socket()) {
            socket.connect(new InetSocketAddress(controllerHost, controllerPort),
                    10000);
            socket.setSoTimeout(300000);
            BufferedWriter out = new BufferedWriter(new OutputStreamWriter(
                    socket.getOutputStream(), StandardCharsets.UTF_8));
            out.write(json(event));
            out.write('\n');
            out.flush();
            BufferedReader in = new BufferedReader(new InputStreamReader(
                    socket.getInputStream(), StandardCharsets.UTF_8));
            String answer = in.readLine();
            if (!"CONTINUE".equals(answer)) {
                throw new IllegalStateException("fault controller: " + answer);
            }
        } catch (IOException error) {
            throw new IllegalStateException("fault controller unreachable at "
                    + controllerHost + ":" + controllerPort, error);
        }
    }

    private static Map<String, Object> emit(String kind, String site,
                                            Frame frame,
                                            Map<String, Object> extras,
                                            boolean durable) {
        Map<String, Object> row = new LinkedHashMap<String, Object>();
        row.put("schema", 1);
        row.put("kind", kind);
        row.put("node", node);
        row.put("process", PROCESS);
        row.put("seq", SEQUENCE.incrementAndGet());
        row.put("wall_ms", System.currentTimeMillis());
        row.put("thread", Long.toString(Thread.currentThread().getId()));
        row.put("span", frame == null ? "" : Long.toString(frame.span));
        row.put("parent", frame == null ? "" : Long.toString(frame.parent));
        row.put("site", site);
        row.put("context", frame == null ? "root" : frame.context);
        if (extras != null) row.putAll(extras);
        synchronized (TRACE_LOCK) {
            try {
                traceWriter.write(json(row));
                traceWriter.write('\n');
                if (durable) {
                    traceWriter.flush();
                    traceStream.getFD().sync();
                }
            } catch (IOException error) {
                throw new IllegalStateException("trace write failed", error);
            }
        }
        return row;
    }

    private static void flush(boolean durable) {
        synchronized (TRACE_LOCK) {
            if (traceWriter == null) return;
            try {
                traceWriter.flush();
                if (durable) traceStream.getFD().sync();
            } catch (IOException error) {
                System.err.println("adhoc-crashfuzz: trace flush failed: " + error);
            }
        }
    }

    private static String json(Map<String, Object> row) {
        StringBuilder out = new StringBuilder("{");
        boolean first = true;
        for (Map.Entry<String, Object> entry : row.entrySet()) {
            if (!first) out.append(',');
            first = false;
            quote(out, entry.getKey());
            out.append(':');
            Object value = entry.getValue();
            if (value instanceof Number || value instanceof Boolean)
                out.append(value);
            else quote(out, String.valueOf(value));
        }
        return out.append('}').toString();
    }

    private static void quote(StringBuilder out, String text) {
        out.append('"');
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            if (c == '"' || c == '\\') out.append('\\').append(c);
            else if (c == '\n') out.append("\\n");
            else if (c == '\r') out.append("\\r");
            else if (c == '\t') out.append("\\t");
            else if (c < 0x20) {
                String hex = Integer.toHexString(c);
                out.append("\\u");
                for (int pad = hex.length(); pad < 4; pad++) out.append('0');
                out.append(hex);
            } else out.append(c);
        }
        out.append('"');
    }

    /** Identity-based, weak object IDs; no hash-code collision becomes a cell. */
    private static final class WeakIds {
        private final ReferenceQueue<Object> collected =
                new ReferenceQueue<Object>();
        private final Map<IdentityRef, Long> ids =
                new HashMap<IdentityRef, Long>();
        private long next = 1;

        synchronized long id(Object object) {
            if (object == null) return 0;
            IdentityRef stale;
            while ((stale = (IdentityRef) collected.poll()) != null)
                ids.remove(stale);
            IdentityRef lookup = new IdentityRef(object, null);
            Long held = ids.get(lookup);
            if (held != null) return held;
            long minted = next++;
            ids.put(new IdentityRef(object, collected), minted);
            return minted;
        }
    }

    private static final class IdentityRef extends WeakReference<Object> {
        private final int hash;
        IdentityRef(Object object, ReferenceQueue<Object> queue) {
            super(object, queue);
            hash = System.identityHashCode(object);
        }
        @Override public int hashCode() { return hash; }
        @Override public boolean equals(Object other) {
            if (this == other) return true;
            return other instanceof IdentityRef
                    && get() != null && get() == ((IdentityRef) other).get();
        }
    }
}
