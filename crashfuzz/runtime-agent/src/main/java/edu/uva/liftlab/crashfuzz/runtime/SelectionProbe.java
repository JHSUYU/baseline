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
import java.lang.reflect.Array;
import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.ArrayDeque;
import java.util.Arrays;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
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
    private static final String BEFORE = "before";
    private static final String AFTER = "after";
    private static BufferedWriter output;
    private static boolean closed;
    private static long sequence;
    private static JsonArray planned = new JsonArray();
    private static int nextFault;
    private static boolean independentReplyFanout;
    private static final Set<Integer> completedFanoutFaults = new HashSet<>();
    private static int applied;
    private static String targetMethod;
    private static final Set<String> seenMethods = new HashSet<>();
    private static final Set<String> seenBranches = new HashSet<>();
    private static final Set<String> seenIdentityGaps = new HashSet<>();
    private static final Map<String, Integer> occurrenceHits = new HashMap<>();
    // A lost reply's ordinal among this actor's replies of the same shape at the site:
    // the k-th DisableTableResponse, whatever polls the same call site served between.
    private static final Map<String, Integer> shapeHits = new HashMap<>();

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
                independentReplyFanout = IndependentReplyFanout.enabled(planned);
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

    /** Associate Solr's watch owner with its embedded cluster node. */
    public static void registerSolrController(Object controller) {
        SolrActorIdentity.registerController(controller);
    }

    /** Propagate an embedded node's identity into I/O helpers on its actor thread. */
    public static void bindActor(Object actor) { ActorIdentity.bindCurrentThread(actor); }

    public static void unbindActor() { ActorIdentity.clearCurrentThread(); }

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
                ActorIdentity.Resolution node = ActorIdentity.currentThread();
                if (node.applies() && !node.gap) {
                    row.addProperty("logicalNodeId", node.logicalNodeId);
                }
                if (thrown == null) row.addProperty("nullThrowable", true);
                write(row, true);
            } catch (IOException error) {
                throw new IllegalStateException("cannot record explicit throw", error);
            }
        }
    }

    public static void check(String siteId) {
        check(siteId, null);
    }

    public static void check(String siteId, Object context) {
        Deque<Long> calls = CALLS.get();
        synchronized (SelectionProbe.class) {
            try {
                JsonObject row = event("CHECK_REACHED");
                row.addProperty("siteId", siteId);
                row.addProperty("method", siteId.split("#", 2)[0]);
                row.addProperty("callId", calls.isEmpty() ? 0 : calls.peek());
                ActorIdentity.Resolution node = SolrActorIdentity.targetCheckNode(
                        siteId, context);
                if (!node.applies()) node = ActorIdentity.currentThread();
                if (node.applies() && !node.gap) {
                    row.addProperty("logicalNodeId", node.logicalNodeId);
                }
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
        io(siteId, callee, null);
    }

    public static void io(String siteId, String callee, Object owner) throws IOException {
        ioAtPhase(siteId, callee, owner, BEFORE, null);
    }

    /** Called only after a selected RPC invocation has returned normally. */
    public static void ioAfter(String siteId, String callee, Object owner) throws IOException {
        ioAtPhase(siteId, callee, owner, AFTER, null);
    }

    /** Distinguish successful RPC responses with different object contents. */
    public static void ioAfter(String siteId, String callee, Object owner,
                               Object result) throws IOException {
        ioAtPhase(siteId, callee, owner, AFTER, responseShape(result));
    }

    static String responseShape(Object result) {
        if (result == null) return "null";
        Class<?> type = result.getClass();
        StringBuilder shape = new StringBuilder(type.getName());
        if (type.isArray()) {
            appendArrayShape(shape, result);
            return shape.toString();
        }
        // Inspect only immediate object-array fields. Their element classes
        // expose control messages without serializing data or invoking getters.
        Field[] fields = type.getDeclaredFields();
        Arrays.sort(fields, (left, right) -> left.getName().compareTo(right.getName()));
        int inspected = 0;
        for (Field field : fields) {
            if (inspected >= 8) break;
            Class<?> fieldType = field.getType();
            if (Modifier.isStatic(field.getModifiers()) || !fieldType.isArray()
                    || fieldType.getComponentType().isPrimitive()) continue;
            inspected++;
            try {
                field.setAccessible(true);
                Object array = field.get(result);
                shape.append('|').append(field.getName()).append('=');
                appendArrayShape(shape, array);
            } catch (ReflectiveOperationException | RuntimeException ignored) {
                // A strongly encapsulated response still has its class name.
            }
        }
        return shape.toString();
    }

    private static void appendArrayShape(StringBuilder shape, Object array) {
        if (array == null) {
            shape.append("null");
            return;
        }
        int length = Array.getLength(array);
        TreeSet<String> elements = new TreeSet<>();
        for (int index = 0; index < Math.min(length, 16); index++) {
            Object element = Array.get(array, index);
            if (element != null) elements.add(element.getClass().getName());
        }
        shape.append('[');
        boolean first = true;
        for (String element : elements) {
            if (!first) shape.append(',');
            shape.append(element);
            first = false;
        }
        if (length > 16) shape.append(first ? "+" : ",+");
        shape.append(']');
    }

    private static void ioAtPhase(String siteId, String callee, Object owner,
                                  String phase, String responseShape) throws IOException {
        String thread = Thread.currentThread().getName();
        ActorIdentity.Resolution identity = ActorIdentity.resolve(owner, siteId, thread);
        String actor = identity.logicalNodeId != null
                && identity.logicalNodeId.startsWith("solr:")
                ? identity.logicalNodeId : thread;
        String occurrence = OccurrenceIdentity.stable(NODE + "/" + actor + "/" + siteId);
        if (identity.applies() && !identity.logicalNodeId.startsWith("solr:")) {
            int siteStart = occurrence.lastIndexOf("/<");
            if (siteStart >= 0) {
                occurrence = occurrence.substring(0, siteStart) + "|"
                        + identity.logicalNodeId + occurrence.substring(siteStart);
            }
        }
        Map<String, Integer> hits = HITS.get();
        String phaseSite = phase + "|" + siteId;
        int hit = hits.getOrDefault(phaseSite, 0) + 1;
        hits.put(phaseSite, hit);
        Throwable selectedFault;
        synchronized (SelectionProbe.class) {
            if (identity.gap && seenIdentityGaps.add(identity.logicalNodeId)) {
                JsonObject gap = event("ACTOR_IDENTITY_GAP");
                gap.addProperty("siteId", siteId);
                gap.addProperty("actorClass", owner == null ? "" : owner.getClass().getName());
                gap.addProperty("logicalNodeId", identity.logicalNodeId);
                gap.addProperty("reason", identity.reason);
                write(gap, true);
            }
            // Several short-lived actors can normalize to the same address,
            // each with a thread-local hit of one. Keep their observed order
            // so a fault can address a later occurrence of that actor/site.
            String phaseOccurrence = phase + "|" + occurrence;
            int occurrenceOrdinal = occurrenceHits.getOrDefault(phaseOccurrence, 0) + 1;
            occurrenceHits.put(phaseOccurrence, occurrenceOrdinal);
            int shapeOrdinal = 0;
            if (AFTER.equals(phase) && responseShape != null) {
                String shaped = phaseOccurrence + "|" + responseShape;
                shapeOrdinal = shapeHits.getOrDefault(shaped, 0) + 1;
                shapeHits.put(shaped, shapeOrdinal);
            }
            if (identity.logicalNodeId != null
                    && identity.logicalNodeId.startsWith("solr:")) {
                // Jetty and executor thread numbers change between cluster runs.
                // Count by stable logical actor instead of the thread-local counter.
                hit = occurrenceOrdinal;
            }
            JsonObject observed = faultEvent("FAULT_POINT_OBSERVED", siteId,
                    callee, occurrence, hit, occurrenceOrdinal, identity, phase,
                    responseShape, shapeOrdinal);
            write(observed, true);
            // A missing HDFS actor slot must never match a different DN
            // merely because both thread names normalize to the same actor.
            if (identity.gap) return;
            if (nextFault >= planned.size()) return;
            int selectedIndex = -1;
            if (independentReplyFanout) {
                for (int index = 0; index < planned.size(); index++) {
                    if (!completedFanoutFaults.contains(index)
                            && matchesFault(planned.get(index).getAsJsonObject(), siteId,
                            callee, occurrence, hit, occurrenceOrdinal, phase, responseShape,
                            shapeOrdinal)) {
                        selectedIndex = index;
                        break;
                    }
                }
            } else if (matchesFault(planned.get(nextFault).getAsJsonObject(), siteId,
                    callee, occurrence, hit, occurrenceOrdinal, phase, responseShape,
                    shapeOrdinal)) {
                selectedIndex = nextFault;
            }
            if (selectedIndex < 0) return;
            JsonObject wanted = planned.get(selectedIndex).getAsJsonObject();
            String exceptionClass = string(wanted, "exceptionClass");
            selectedFault = makeFault(exceptionClass, siteId);
            JsonObject matched = faultEvent("FAULT_MATCHED", siteId, callee,
                    occurrence, hit, occurrenceOrdinal, identity, phase,
                    responseShape, shapeOrdinal);
            matched.addProperty("faultId", string(wanted, "faultId"));
            if (!exceptionClass.isEmpty()) matched.addProperty("exceptionClass", exceptionClass);
            write(matched, true);
            JsonObject appliedRow = faultEvent("FAULT_APPLIED", siteId, callee,
                    occurrence, hit, occurrenceOrdinal, identity, phase,
                    responseShape, shapeOrdinal);
            appliedRow.addProperty("faultId", string(wanted, "faultId"));
            if (!exceptionClass.isEmpty()) appliedRow.addProperty("exceptionClass", exceptionClass);
            write(appliedRow, true);
            if (independentReplyFanout) {
                completedFanoutFaults.add(selectedIndex);
                while (completedFanoutFaults.contains(nextFault)) nextFault++;
            } else {
                nextFault++;
            }
            applied++;
        }
        SelectionProbe.<RuntimeException>throwUnchecked(selectedFault);
    }

    private static boolean matchesFault(JsonObject wanted, String siteId,
                                        String callee, String occurrence, int hit,
                                        int occurrenceOrdinal, String phase,
                                        String responseShape, int shapeOrdinal) {
        if (wanted.has("shapeOrdinal")) {
            // A reply named by its shape and its ordinal among replies of that shape.
            return MARKER.equals(string(wanted, "marker"))
                    && phase.equals(wanted.has("phase") ? string(wanted, "phase") : BEFORE)
                    && siteId.equals(string(wanted, "siteId"))
                    && callee.equals(string(wanted, "sourceKey"))
                    && occurrence.equals(OccurrenceIdentity.stable(string(wanted, "occurrence")))
                    && responseShape != null
                    && responseShape.equals(string(wanted, "responseShape"))
                    && shapeOrdinal == wanted.get("shapeOrdinal").getAsInt();
        }
        return MARKER.equals(string(wanted, "marker"))
                && phase.equals(wanted.has("phase") ? string(wanted, "phase") : BEFORE)
                && siteId.equals(string(wanted, "siteId"))
                && callee.equals(string(wanted, "sourceKey"))
                && occurrence.equals(OccurrenceIdentity.stable(string(wanted, "occurrence")))
                && hit == wanted.get("hitOrdinal").getAsInt()
                && (!wanted.has("responseShape") || (responseShape != null
                && responseShape.equals(string(wanted, "responseShape"))))
                && (!wanted.has("occurrenceOrdinal")
                || occurrenceOrdinal == wanted.get("occurrenceOrdinal").getAsInt());
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
                                         String occurrence, int hit, int occurrenceOrdinal,
                                         ActorIdentity.Resolution identity, String phase,
                                         String responseShape, int shapeOrdinal) {
        JsonObject row = event(kind);
        row.addProperty("marker", MARKER);
        row.addProperty("siteId", siteId);
        row.addProperty("sourceKey", callee);
        row.addProperty("occurrenceAddress", occurrence);
        row.addProperty("hitOrdinal", hit);
        row.addProperty("occurrenceOrdinal", occurrenceOrdinal);
        row.addProperty("phase", phase);
        if (responseShape != null) row.addProperty("responseShape", responseShape);
        if (shapeOrdinal > 0) row.addProperty("shapeOrdinal", shapeOrdinal);
        if (identity.applies()) {
            row.addProperty("logicalNodeId", identity.logicalNodeId);
            if (identity.gap) row.addProperty("identityGap", true);
        }
        return row;
    }
}
