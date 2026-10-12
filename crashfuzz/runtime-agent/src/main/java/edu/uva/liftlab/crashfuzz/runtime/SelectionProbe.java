package edu.uva.liftlab.crashfuzz.runtime;

import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.objectweb.asm.Opcodes;

import java.io.BufferedWriter;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicLong;

/** Small per-JVM runtime for selected coverage and exact I/O fault identity. */
public final class SelectionProbe {
    private static final Gson GSON = new Gson();
    private static final AtomicLong CALL_IDS = new AtomicLong();
    private static final ThreadLocal<Deque<Long>> CALLS = ThreadLocal.withInitial(ArrayDeque::new);
    private static final ThreadLocal<Map<String, Integer>> HITS =
            ThreadLocal.withInitial(HashMap::new);
    private static final String NODE = System.getProperty("crashfuzz.node", "local");
    private static final String MARKER = "FAULT:STATIC:IO";
    private static BufferedWriter output;
    private static boolean closed;
    private static long sequence;
    private static JsonArray planned = new JsonArray();
    private static int nextFault;
    private static int applied;
    private static String targetMethod;
    private static final Set<String> seenMethods = new HashSet<>();
    private static final Set<String> seenBranches = new HashSet<>();
    private static final Map<String, Integer> occurrenceHits = new HashMap<>();

    static {
        try {
            String trace = System.getenv("CRASHFUZZ_TRACE_PATH");
            if (trace == null || trace.isEmpty()) {
                trace = System.getProperty("crashfuzz.trace.path");
            }
            if (trace == null || trace.isEmpty()) {
                String directory = System.getenv("CAUSYNTH_TRACE_OUTPUT_DIR");
                if (directory == null || directory.isEmpty()) {
                    throw new IllegalStateException("trace output directory is required");
                }
                trace = Paths.get(directory, "runtime_trace.jsonl").toString();
            }
            Path file = Paths.get(trace);
            Files.createDirectories(file.getParent());
            output = new BufferedWriter(new OutputStreamWriter(
                    new FileOutputStream(file.toFile(), false), StandardCharsets.UTF_8));
            String trial = System.getenv("CAUSYNTH_FAULT_TRIAL");
            if (trial == null || trial.isEmpty()) {
                trial = System.getProperty("causynth.fault.trial");
            }
            if (trial != null && !trial.isEmpty()) {
                JsonObject value = JsonParser.parseString(new String(Files.readAllBytes(
                        Paths.get(trial)), StandardCharsets.UTF_8)).getAsJsonObject();
                planned = value.getAsJsonArray("faults");
                if (planned == null) throw new IllegalArgumentException("trial has no faults");
            }
            Runtime.getRuntime().addShutdownHook(new Thread(() -> {
                synchronized (SelectionProbe.class) {
                    try {
                        JsonObject summary = event("FAULT_TRIAL_SUMMARY");
                        summary.addProperty("appliedCount", applied);
                        summary.addProperty("requestedCount", planned.size());
                        write(summary, true);
                        closed = true;
                        output.close();
                    } catch (IOException ignored) {
                        // The JUnit process is ending; the existing trace remains reviewable.
                    }
                }
            }, "crashfuzz-trace-close"));
        } catch (IOException error) {
            throw new ExceptionInInitializerError(error);
        }
    }

    private SelectionProbe() {}

    private static JsonObject event(String kind) {
        JsonObject row = new JsonObject();
        row.addProperty("schemaVersion", 3);
        row.addProperty("event", kind);
        row.addProperty("seq", ++sequence);
        row.addProperty("thread", Thread.currentThread().getName());
        row.addProperty("node", NODE);
        return row;
    }

    private static void write(JsonObject row, boolean flush) throws IOException {
        if (closed) return;
        output.write(GSON.toJson(row));
        output.newLine();
        if (flush || sequence % 256 == 0) output.flush();
    }

    public static synchronized void selectionApplied(String digest) {
        try {
            JsonObject row = event("STATIC_SELECTION_APPLIED");
            row.addProperty("digest", digest);
            write(row, true);
        } catch (IOException error) {
            throw new IllegalStateException("cannot record static selection", error);
        }
    }

    public static synchronized void weaveClass(String className,
            int selectedMethods, int wovenMethods, int selectedIo, int wovenIo,
            int selectedBranches, int wovenBranches) {
        try {
            JsonObject row = event("STATIC_WEAVE_CLASS");
            row.addProperty("className", className);
            row.addProperty("selectedMethods", selectedMethods);
            row.addProperty("wovenMethods", wovenMethods);
            row.addProperty("selectedIo", selectedIo);
            row.addProperty("wovenIo", wovenIo);
            row.addProperty("selectedBranches", selectedBranches);
            row.addProperty("wovenBranches", wovenBranches);
            write(row, true);
        } catch (IOException error) {
            throw new IllegalStateException("cannot record static weave", error);
        }
    }

    public static synchronized void setTargetMethod(String method) {
        targetMethod = method;
    }

    public static void enter(String method) {
        Deque<Long> calls = CALLS.get();
        long parent = calls.isEmpty() ? 0 : calls.peek();
        long id = CALL_IDS.incrementAndGet();
        calls.push(id);
        synchronized (SelectionProbe.class) {
            if (!method.equals(targetMethod) && !seenMethods.add(method)) return;
            try {
                JsonObject row = event("METHOD_ENTER");
                row.addProperty("method", method);
                row.addProperty("callId", id);
                row.addProperty("parentCallId", parent);
                write(row, false);
            } catch (IOException error) {
                throw new IllegalStateException("cannot record method entry", error);
            }
        }
    }

    private static long end(String method, String kind, Throwable thrown) {
        Deque<Long> calls = CALLS.get();
        long id = calls.isEmpty() ? 0 : calls.pop();
        synchronized (SelectionProbe.class) {
            if (thrown == null && !method.equals(targetMethod)) return id;
            try {
                JsonObject row = event(kind);
                row.addProperty("method", method);
                row.addProperty("callId", id);
                if (thrown != null) row.addProperty("runtimeType",
                        thrown.getClass().getName());
                write(row, thrown != null);
            } catch (IOException error) {
                throw new IllegalStateException("cannot record method exit", error);
            }
        }
        return id;
    }

    public static void exitNormal(String method) { end(method, "METHOD_EXIT_NORMAL", null); }
    public static void exitThrow(String method, Throwable thrown) {
        end(method, "METHOD_EXIT_THROW", thrown);
    }

    /** Record an actual ATHROW, including one caught later within the same method. */
    public static void explicitThrow(Throwable thrown, String method, String siteId,
                                     int sourceLine, int throwOrdinal) {
        Deque<Long> calls = CALLS.get();
        synchronized (SelectionProbe.class) {
            try {
                JsonObject row = event("EXPLICIT_THROW");
                row.addProperty("method", method);
                row.addProperty("siteId", siteId);
                row.addProperty("sourceLine", sourceLine);
                row.addProperty("throwOrdinal", throwOrdinal);
                row.addProperty("callId", calls.isEmpty() ? 0 : calls.peek());
                // ATHROW with a null operand raises NullPointerException itself.
                row.addProperty("runtimeType", thrown == null
                        ? NullPointerException.class.getName() : thrown.getClass().getName());
                if (thrown == null) row.addProperty("nullThrowable", true);
                write(row, true);
            } catch (IOException error) {
                throw new IllegalStateException("cannot record explicit throw", error);
            }
        }
    }

    public static void check(String siteId) {
        Deque<Long> calls = CALLS.get();
        synchronized (SelectionProbe.class) {
            try {
                JsonObject row = event("CHECK_REACHED");
                row.addProperty("siteId", siteId);
                row.addProperty("method", siteId.split("#", 2)[0]);
                row.addProperty("callId", calls.isEmpty() ? 0 : calls.peek());
                write(row, false);
            } catch (IOException error) {
                throw new IllegalStateException("cannot record target check", error);
            }
        }
    }

    private static void branch(String siteId, boolean outcome) {
        Deque<Long> calls = CALLS.get();
        synchronized (SelectionProbe.class) {
            if (!siteId.startsWith(targetMethod + "#")
                    && !seenBranches.add(siteId + ":" + outcome)) return;
            try {
                JsonObject row = event("BRANCH");
                row.addProperty("siteId", siteId);
                row.addProperty("method", siteId.split("#", 2)[0]);
                row.addProperty("callId", calls.isEmpty() ? 0 : calls.peek());
                row.addProperty("outcome", outcome);
                write(row, false);
            } catch (IOException error) {
                throw new IllegalStateException("cannot record branch", error);
            }
        }
    }

    public static void branchInt1(int value, String site, int opcode) {
        boolean outcome;
        switch (opcode) {
            case Opcodes.IFEQ: outcome = value == 0; break;
            case Opcodes.IFNE: outcome = value != 0; break;
            case Opcodes.IFLT: outcome = value < 0; break;
            case Opcodes.IFGE: outcome = value >= 0; break;
            case Opcodes.IFGT: outcome = value > 0; break;
            case Opcodes.IFLE: outcome = value <= 0; break;
            default: throw new IllegalArgumentException("unsupported branch " + opcode);
        }
        branch(site, outcome);
    }

    public static void branchInt2(int left, int right, String site, int opcode) {
        boolean outcome;
        switch (opcode) {
            case Opcodes.IF_ICMPEQ: outcome = left == right; break;
            case Opcodes.IF_ICMPNE: outcome = left != right; break;
            case Opcodes.IF_ICMPLT: outcome = left < right; break;
            case Opcodes.IF_ICMPGE: outcome = left >= right; break;
            case Opcodes.IF_ICMPGT: outcome = left > right; break;
            case Opcodes.IF_ICMPLE: outcome = left <= right; break;
            default: throw new IllegalArgumentException("unsupported branch " + opcode);
        }
        branch(site, outcome);
    }

    public static void branchRef1(Object value, String site, int opcode) {
        branch(site, opcode == Opcodes.IFNULL ? value == null : value != null);
    }

    public static void branchRef2(Object left, Object right, String site, int opcode) {
        branch(site, opcode == Opcodes.IF_ACMPEQ ? left == right : left != right);
    }

    public static void io(String siteId, String callee) throws IOException {
        String occurrence = OccurrenceIdentity.stable(NODE + "/"
                + Thread.currentThread().getName() + "/" + siteId);
        Map<String, Integer> hits = HITS.get();
        int hit = hits.getOrDefault(siteId, 0) + 1;
        hits.put(siteId, hit);
        Throwable selectedFault;
        synchronized (SelectionProbe.class) {
            // Several short-lived actors can normalize to the same address,
            // each with a thread-local hit of one. Keep their observed order
            // so a fault can address a later occurrence of that actor/site.
            int occurrenceOrdinal = occurrenceHits.getOrDefault(occurrence, 0) + 1;
            occurrenceHits.put(occurrence, occurrenceOrdinal);
            JsonObject observed = faultEvent("FAULT_POINT_OBSERVED", siteId,
                    callee, occurrence, hit, occurrenceOrdinal);
            write(observed, true);
            if (nextFault >= planned.size()) return;
            JsonObject wanted = planned.get(nextFault).getAsJsonObject();
            if (!MARKER.equals(string(wanted, "marker"))
                    || !siteId.equals(string(wanted, "siteId"))
                    || !callee.equals(string(wanted, "sourceKey"))
                    || !occurrence.equals(OccurrenceIdentity.stable(string(wanted, "occurrence")))
                    || hit != wanted.get("hitOrdinal").getAsInt()
                    || (wanted.has("occurrenceOrdinal")
                    && occurrenceOrdinal != wanted.get("occurrenceOrdinal").getAsInt())) return;
            String exceptionClass = string(wanted, "exceptionClass");
            selectedFault = makeFault(exceptionClass, siteId);
            JsonObject matched = faultEvent("FAULT_MATCHED", siteId, callee,
                    occurrence, hit, occurrenceOrdinal);
            matched.addProperty("faultId", string(wanted, "faultId"));
            if (!exceptionClass.isEmpty()) matched.addProperty("exceptionClass", exceptionClass);
            write(matched, true);
            JsonObject appliedRow = faultEvent("FAULT_APPLIED", siteId, callee,
                    occurrence, hit, occurrenceOrdinal);
            appliedRow.addProperty("faultId", string(wanted, "faultId"));
            if (!exceptionClass.isEmpty()) appliedRow.addProperty("exceptionClass", exceptionClass);
            write(appliedRow, true);
            nextFault++;
            applied++;
        }
        SelectionProbe.<RuntimeException>throwUnchecked(selectedFault);
    }

    private static Throwable makeFault(String name, String siteId) throws IOException {
        if (name.isEmpty() || "java.io.IOException".equals(name)) {
            return new IOException("CrashFuzz injected at " + siteId);
        }
        try {
            ClassLoader loader = Thread.currentThread().getContextClassLoader();
            if (loader == null) loader = SelectionProbe.class.getClassLoader();
            Class<?> type = Class.forName(name, true, loader);
            if (!IOException.class.isAssignableFrom(type)
                    && !"org.apache.zookeeper.KeeperException$ConnectionLossException".equals(name)) {
                throw new IllegalArgumentException("unsupported fault exception: " + name);
            }
            try {
                return (Throwable) type.getDeclaredConstructor(String.class)
                        .newInstance("CrashFuzz injected at " + siteId);
            } catch (NoSuchMethodException ignored) {
                return (Throwable) type.getDeclaredConstructor().newInstance();
            }
        } catch (ReflectiveOperationException error) {
            throw new IllegalStateException("cannot instantiate fault exception " + name, error);
        }
    }

    @SuppressWarnings("unchecked")
    private static <E extends Throwable> void throwUnchecked(Throwable error) throws E {
        throw (E) error;
    }

    private static String string(JsonObject object, String key) {
        JsonElement value = object.get(key);
        return value == null || value.isJsonNull() ? "" : value.getAsString();
    }

    private static JsonObject faultEvent(String kind, String siteId, String callee,
                                         String occurrence, int hit, int occurrenceOrdinal) {
        JsonObject row = event(kind);
        row.addProperty("marker", MARKER);
        row.addProperty("siteId", siteId);
        row.addProperty("sourceKey", callee);
        row.addProperty("occurrenceAddress", occurrence);
        row.addProperty("hitOrdinal", hit);
        row.addProperty("occurrenceOrdinal", occurrenceOrdinal);
        return row;
    }
}
