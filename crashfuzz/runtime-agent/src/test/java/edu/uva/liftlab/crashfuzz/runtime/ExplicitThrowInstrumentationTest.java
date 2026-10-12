package edu.uva.liftlab.crashfuzz.runtime;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.apache.hadoop.hdfs.server.datanode.BPServiceActor;
import org.junit.Test;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.IllegalClassFormatException;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

public class ExplicitThrowInstrumentationTest {
    private static final String METHOD = "<" + Fixture.class.getName()
            + ": int run(boolean)>";
    private static final String OTHER_METHOD = "<" + Fixture.class.getName()
            + ": int runOther()>";
    private static final String SYNCHRONIZED_METHOD = "<" + Fixture.class.getName()
            + ": int runSynchronized()>";
    private static final String USER_RETHROW_METHOD = "<" + Fixture.class.getName()
            + ": void runUserRethrow()>";
    private static final String BP_METHOD = "<" + BPServiceActor.class.getName()
            + ": void selectedIo()>";
    private static final String BP_SITE = BP_METHOD + "#u-test";

    public static class Fixture {
        private static final Object LOCK = new Object();

        public static int run(boolean first) {
            try {
                if (first) {
                    throw new IllegalStateException("first throw is caught");
                }
                throw new IllegalArgumentException("second throw is caught");
            } catch (RuntimeException caught) {
                return first ? 1 : 2;
            }
        }

        public static int runOther() {
            try {
                throw null;
            } catch (NullPointerException caught) {
                return 3;
            }
        }

        public static int runSynchronized() {
            synchronized (LOCK) {
                throw new IllegalStateException("one source throw, two bytecode ATHROWs");
            }
        }

        public static void runUserRethrow() throws Throwable {
            try {
                throw new IllegalArgumentException("first explicit throw");
            } catch (Throwable caught) {
                throw caught;
            }
        }
    }

    public static class FakeClientSideTranslatorPB {
        static int calls;
        public String reference() { calls++; return "reply"; }
        public int integer() { calls++; return 17; }
        public long wide() { calls++; return 19L; }
        public void nothing() { calls++; }
        public String fail() throws IOException {
            calls++;
            throw new IOException("original RPC failure");
        }
    }

    public static class RpcFixture {
        private final FakeClientSideTranslatorPB rpc = new FakeClientSideTranslatorPB();
        public String reference() { return rpc.reference(); }
        public int integer() { return rpc.integer(); }
        public long wide() { return rpc.wide(); }
        public void nothing() { rpc.nothing(); }
        public String fail() throws IOException { return rpc.fail(); }
    }

    @Test
    public void caughtThrowsHaveDistinctExactSitesAndNormalMethodExit() throws Exception {
        Path trace = Files.createTempFile("crashfuzz-explicit-throw-", ".jsonl");
        System.setProperty("crashfuzz.trace.path", trace.toString());
        try {
            Class<?> instrumented = instrumentFixture();
            SelectionProbe.setTargetMethod(METHOD);
            assertEquals(1, instrumented.getMethod("run", boolean.class).invoke(null, true));
            assertEquals(2, instrumented.getMethod("run", boolean.class).invoke(null, false));
            assertEquals(3, instrumented.getMethod("runOther").invoke(null));
            try {
                instrumented.getMethod("runSynchronized").invoke(null);
                throw new AssertionError("expected fixture exception");
            } catch (InvocationTargetException error) {
                assertTrue(error.getCause() instanceof IllegalStateException);
            }
            try {
                instrumented.getMethod("runUserRethrow").invoke(null);
                throw new AssertionError("expected user rethrow");
            } catch (InvocationTargetException error) {
                assertTrue(error.getCause() instanceof IllegalArgumentException);
            }
            verifyLaterOccurrenceCanBeMatched();
            Class<?> bpActor = instrumentBpActor();
            bpActor.getMethod("selectedIo").invoke(bpActor.getConstructor(String.class)
                    .newInstance("[DISK]file:/tmp/run1/data/dfs/data/data1"));
            bpActor.getMethod("selectedIo").invoke(bpActor.getConstructor(String.class)
                    .newInstance("[DISK]file:/tmp/run2/data/dfs/data/data3"));
            bpActor.getMethod("selectedIo").invoke(bpActor.getConstructor(String.class)
                    .newInstance("file:/var/lib/hdfs/dn"));
            SelectionProbe.selectionApplied("test-flush");

            List<JsonObject> throwsSeen = new ArrayList<>();
            List<JsonObject> weaveRows = new ArrayList<>();
            int normalExits = 0;
            int uncaughtExits = 0;
            List<JsonObject> observed = new ArrayList<>();
            List<JsonObject> applied = new ArrayList<>();
            int identityGaps = 0;
            for (String line : Files.readAllLines(trace, StandardCharsets.UTF_8)) {
                JsonObject event = JsonParser.parseString(line).getAsJsonObject();
                if ("EXPLICIT_THROW".equals(event.get("event").getAsString())) {
                    throwsSeen.add(event);
                } else if ("STATIC_WEAVE_CLASS".equals(event.get("event").getAsString())) {
                    weaveRows.add(event);
                } else if ("METHOD_EXIT_NORMAL".equals(event.get("event").getAsString())) {
                    normalExits++;
                } else if ("METHOD_EXIT_THROW".equals(event.get("event").getAsString())) {
                    String method = event.get("method").getAsString();
                    assertTrue(method.equals(SYNCHRONIZED_METHOD)
                            || method.equals(USER_RETHROW_METHOD));
                    uncaughtExits++;
                } else if ("FAULT_POINT_OBSERVED".equals(event.get("event").getAsString())) {
                    observed.add(event);
                } else if ("FAULT_APPLIED".equals(event.get("event").getAsString())) {
                    applied.add(event);
                } else if ("ACTOR_IDENTITY_GAP".equals(event.get("event").getAsString())) {
                    identityGaps++;
                }
            }
            assertEquals(2, normalExits);
            assertEquals(2, weaveRows.size());
            assertEquals(4, weaveRows.get(0).get("selectedMethods").getAsInt());
            assertEquals(4, weaveRows.get(0).get("wovenMethods").getAsInt());
            assertEquals(1, weaveRows.get(0).get("selectedIo").getAsInt());
            assertEquals(0, weaveRows.get(0).get("wovenIo").getAsInt());
            assertEquals(1, weaveRows.get(1).get("selectedIo").getAsInt());
            assertEquals(1, weaveRows.get(1).get("wovenIo").getAsInt());
            assertEquals(2, uncaughtExits);
            assertEquals(6, throwsSeen.size());
            assertEquals("java.lang.IllegalStateException",
                    throwsSeen.get(0).get("runtimeType").getAsString());
            assertEquals("java.lang.IllegalArgumentException",
                    throwsSeen.get(1).get("runtimeType").getAsString());
            assertEquals(METHOD, throwsSeen.get(0).get("method").getAsString());
            assertTrue(throwsSeen.get(0).get("callId").getAsLong() > 0);
            assertTrue(throwsSeen.get(0).get("sourceLine").getAsInt() > 0);
            assertEquals(0, throwsSeen.get(0).get("throwOrdinal").getAsInt());
            String firstSite = throwsSeen.get(0).get("siteId").getAsString();
            String secondSite = throwsSeen.get(1).get("siteId").getAsString();
            assertTrue(firstSite.startsWith(METHOD + "#bytecode:throw:"));
            assertTrue(secondSite.startsWith(METHOD + "#bytecode:throw:"));
            assertNotEquals(firstSite, secondSite);
            assertEquals(OTHER_METHOD, throwsSeen.get(2).get("method").getAsString());
            assertEquals("java.lang.NullPointerException",
                    throwsSeen.get(2).get("runtimeType").getAsString());
            assertTrue(throwsSeen.get(2).get("nullThrowable").getAsBoolean());
            assertEquals(SYNCHRONIZED_METHOD,
                    throwsSeen.get(3).get("method").getAsString());
            assertEquals("java.lang.IllegalStateException",
                    throwsSeen.get(3).get("runtimeType").getAsString());
            assertEquals(USER_RETHROW_METHOD,
                    throwsSeen.get(4).get("method").getAsString());
            assertEquals(USER_RETHROW_METHOD,
                    throwsSeen.get(5).get("method").getAsString());
            assertEquals("java.lang.IllegalArgumentException",
                    throwsSeen.get(4).get("runtimeType").getAsString());
            assertEquals("java.lang.IllegalArgumentException",
                    throwsSeen.get(5).get("runtimeType").getAsString());
            assertNotEquals(throwsSeen.get(4).get("siteId").getAsString(),
                    throwsSeen.get(5).get("siteId").getAsString());
            assertEquals(6, observed.size());
            assertEquals(observed.get(0).get("occurrenceAddress").getAsString(),
                    observed.get(1).get("occurrenceAddress").getAsString());
            assertEquals(1, observed.get(0).get("hitOrdinal").getAsInt());
            assertEquals(1, observed.get(1).get("hitOrdinal").getAsInt());
            assertEquals(1, observed.get(0).get("occurrenceOrdinal").getAsInt());
            assertEquals(2, observed.get(1).get("occurrenceOrdinal").getAsInt());
            assertEquals(2, applied.size());
            assertEquals(2, applied.get(0).get("occurrenceOrdinal").getAsInt());
            assertEquals(1, applied.get(1).get("occurrenceOrdinal").getAsInt());
            assertEquals("hdfs:dn:data1", observed.get(3).get("logicalNodeId").getAsString());
            assertEquals("hdfs:dn:data3", observed.get(4).get("logicalNodeId").getAsString());
            assertNotEquals(observed.get(3).get("occurrenceAddress").getAsString(),
                    observed.get(4).get("occurrenceAddress").getAsString());
            assertTrue(observed.get(5).get("identityGap").getAsBoolean());
            assertEquals(1, identityGaps);
            verifyPostCallRpcFaults(trace);
        } finally {
            System.clearProperty("crashfuzz.trace.path");
        }
    }

    private static void verifyLaterOccurrenceCanBeMatched() throws Exception {
        String site = METHOD + "#u-test";
        String callee = "example.TestIo#write()V";
        JsonObject wanted = new JsonObject();
        wanted.addProperty("marker", "FAULT:STATIC:IO");
        wanted.addProperty("siteId", site);
        wanted.addProperty("sourceKey", callee);
        wanted.addProperty("occurrence", "local/same-actor/" + site);
        wanted.addProperty("hitOrdinal", 1);
        wanted.addProperty("occurrenceOrdinal", 2);
        wanted.addProperty("faultId", "second-actor-only");
        JsonArray faults = new JsonArray();
        faults.add(wanted);
        Field planned = SelectionProbe.class.getDeclaredField("planned");
        planned.setAccessible(true);
        JsonArray previous = (JsonArray) planned.get(null);
        Field next = SelectionProbe.class.getDeclaredField("nextFault");
        next.setAccessible(true);
        int previousNext = next.getInt(null);
        planned.set(null, faults);
        next.setInt(null, 0);
        try {
            AtomicReference<Throwable> first = new AtomicReference<>();
            AtomicReference<Throwable> second = new AtomicReference<>();
            Thread firstActor = new Thread(() -> {
                try { SelectionProbe.io(site, callee); }
                catch (Throwable error) { first.set(error); }
            }, "same-actor");
            Thread secondActor = new Thread(() -> {
                try { SelectionProbe.io(site, callee); }
                catch (Throwable error) { second.set(error); }
            }, "same-actor");
            firstActor.start();
            firstActor.join();
            secondActor.start();
            secondActor.join();
            assertNull(first.get());
            assertTrue(second.get() instanceof IOException);

            // A checkpoint created before occurrenceOrdinal was introduced
            // still matches the first occurrence by its old exact fields.
            String legacySite = site + "-legacy";
            JsonObject legacy = wanted.deepCopy();
            legacy.remove("occurrenceOrdinal");
            legacy.addProperty("siteId", legacySite);
            legacy.addProperty("occurrence", "local/legacy-actor/" + legacySite);
            JsonArray legacyFaults = new JsonArray();
            legacyFaults.add(legacy);
            planned.set(null, legacyFaults);
            next.setInt(null, 0);
            AtomicReference<Throwable> legacyError = new AtomicReference<>();
            Thread legacyActor = new Thread(() -> {
                try { SelectionProbe.io(legacySite, callee); }
                catch (Throwable error) { legacyError.set(error); }
            }, "legacy-actor");
            legacyActor.start();
            legacyActor.join();
            assertTrue(legacyError.get() instanceof IOException);
        } finally {
            planned.set(null, previous);
            next.setInt(null, previousNext);
        }
    }

    private static void verifyPostCallRpcFaults(Path trace) throws Exception {
        String rpcOwner = FakeClientSideTranslatorPB.class.getName().replace('.', '/');
        assertTrue(SelectionAgent.supportsPostCallFault(rpcOwner, "reference",
                "()Ljava/lang/String;"));
        assertTrue(!SelectionAgent.supportsPostCallFault(rpcOwner, "<init>", "()V"));
        assertTrue(!SelectionAgent.supportsPostCallFault(rpcOwner, "<clinit>", "()V"));
        assertTrue(!SelectionAgent.supportsPostCallFault("java/io/FileInputStream", "read",
                "()I"));
        assertTrue(!SelectionAgent.supportsPostCallFault(rpcOwner, "getProxy",
                "()Ljava/lang/Object;"));
        assertTrue(!SelectionAgent.supportsPostCallFault(rpcOwner,
                "getUnderlyingProxyObject", "()Ljava/lang/Object;"));
        assertTrue(!SelectionAgent.supportsPostCallFault(rpcOwner, "reference",
                "()Ljava/util/concurrent/Future;"));
        assertTrue(SelectionAgent.supportsPostCallFault(
                "org/apache/hadoop/hdfs/protocolPB/DatanodeProtocolClientSideTranslatorPB",
                "sendHeartbeat", "()Ljava/lang/Object;"));
        assertTrue(SelectionAgent.supportsPostCallFault(
                "org/apache/zookeeper/ZooKeeper", "create", "()Ljava/lang/String;"));
        assertTrue(!SelectionAgent.supportsPostCallFault(
                "org/apache/zookeeper/ZooKeeper", "create",
                "(Lorg/apache/zookeeper/AsyncCallback$StringCallback;)V"));
        assertTrue(!SelectionAgent.supportsPostCallFault(
                "org/apache/hadoop/hbase/ipc/BlockingRpcConnection", "sendRequest",
                "(Lorg/apache/hadoop/hbase/ipc/Call;)V"));
        assertTrue(!SelectionAgent.supportsPostCallFault(
                "org/apache/hadoop/hbase/ipc/NettyRpcConnection", "sendRequest",
                "(Lorg/apache/hadoop/hbase/ipc/Call;)V"));
        assertTrue(!SelectionAgent.supportsPostCallFault(
                "org/apache/hbase/thirdparty/com/google/protobuf/RpcChannel", "callMethod",
                "(Lorg/apache/hbase/thirdparty/com/google/protobuf/RpcCallback;)V"));

        String[] names = {"reference", "integer", "wide", "nothing", "fail"};
        String[] types = {"java.lang.String", "int", "long", "void", "java.lang.String"};
        String[] descriptors = {"()Ljava/lang/String;", "()I", "()J", "()V",
                "()Ljava/lang/String;"};
        JsonArray specs = new JsonArray();
        JsonArray ioCalls = new JsonArray();
        for (int index = 0; index < names.length; index++) {
            String signature = "<" + RpcFixture.class.getName() + ": " + types[index]
                    + " " + names[index] + "()>";
            JsonObject spec = new JsonObject();
            spec.addProperty("signature", signature);
            spec.addProperty("owner", RpcFixture.class.getName().replace('.', '/'));
            spec.addProperty("name", names[index]);
            spec.addProperty("descriptor", descriptors[index]);
            specs.add(spec);
            JsonObject io = new JsonObject();
            io.addProperty("method", signature);
            io.addProperty("site_id", signature + "#u1");
            io.addProperty("callee", "<" + FakeClientSideTranslatorPB.class.getName()
                    + ": " + types[index] + " " + names[index] + "()>");
            io.addProperty("line", invocationLine(names[index], rpcOwner));
            io.addProperty("call_owner", rpcOwner);
            io.addProperty("call_name", names[index]);
            io.addProperty("call_descriptor", descriptors[index]);
            io.addProperty("line_ordinal", 0);
            ioCalls.add(io);
        }
        JsonObject selection = new JsonObject();
        selection.addProperty("target_method", specs.get(0).getAsJsonObject()
                .get("signature").getAsString());
        selection.addProperty("post_call_rpc_enabled", true);
        selection.add("method_specs", specs);
        selection.add("io_calls", ioCalls);
        selection.add("branches", new JsonArray());
        Class<?> instrumented = instrumentClass(RpcFixture.class, selection);
        Object fixture = instrumented.getConstructor().newInstance();

        Field planned = SelectionProbe.class.getDeclaredField("planned");
        planned.setAccessible(true);
        JsonArray previous = (JsonArray) planned.get(null);
        Field next = SelectionProbe.class.getDeclaredField("nextFault");
        next.setAccessible(true);
        int previousNext = next.getInt(null);
        try {
            assertEquals("reply", instrumented.getMethod("reference").invoke(fixture));
            assertEquals(17, instrumented.getMethod("integer").invoke(fixture));
            assertEquals(19L, instrumented.getMethod("wide").invoke(fixture));
            assertNull(instrumented.getMethod("nothing").invoke(fixture));
            for (String name : new String[]{"reference", "integer", "wide", "nothing"}) {
                String site = siteFor(ioCalls, name);
                JsonObject prior = latest(trace, "FAULT_POINT_OBSERVED", site, "after");
                assertTrue("missing after observation for " + name, prior != null);
                JsonObject wanted = nextOccurrence(prior, "after");
                JsonArray plan = new JsonArray();
                plan.add(wanted);
                planned.set(null, plan);
                next.setInt(null, 0);
                int callsBefore = FakeClientSideTranslatorPB.calls;
                try {
                    instrumented.getMethod(name).invoke(fixture);
                    throw new AssertionError("expected post-call IOException for " + name);
                } catch (InvocationTargetException error) {
                    assertTrue(error.getCause() instanceof IOException);
                    assertTrue(error.getCause().getMessage().startsWith("CrashFuzz injected"));
                }
                assertEquals(callsBefore + 1, FakeClientSideTranslatorPB.calls);
                assertEquals(1, next.getInt(null));
                assertTrue(latest(trace, "FAULT_APPLIED", site, "after") != null);
            }

            planned.set(null, new JsonArray());
            next.setInt(null, 0);
            String failSite = siteFor(ioCalls, "fail");
            try {
                instrumented.getMethod("fail").invoke(fixture);
                throw new AssertionError("expected original RPC failure");
            } catch (InvocationTargetException error) {
                assertEquals("original RPC failure", error.getCause().getMessage());
            }
            assertNull(latest(trace, "FAULT_POINT_OBSERVED", failSite, "after"));

            // A plan without a phase remains a pre-call fault and prevents the call.
            String voidSite = siteFor(ioCalls, "nothing");
            JsonObject before = latest(trace, "FAULT_POINT_OBSERVED", voidSite, "before");
            JsonObject legacy = nextOccurrence(before, "before");
            legacy.remove("phase");
            JsonArray oldPlan = new JsonArray();
            oldPlan.add(legacy);
            planned.set(null, oldPlan);
            next.setInt(null, 0);
            int callsBefore = FakeClientSideTranslatorPB.calls;
            try {
                instrumented.getMethod("nothing").invoke(fixture);
                throw new AssertionError("expected legacy pre-call IOException");
            } catch (InvocationTargetException error) {
                assertTrue(error.getCause() instanceof IOException);
            }
            assertEquals(callsBefore, FakeClientSideTranslatorPB.calls);
            assertEquals(1, next.getInt(null));

            JsonObject oldSelection = selection.deepCopy();
            oldSelection.remove("post_call_rpc_enabled");
            String oldSite = siteFor(ioCalls, "reference") + "-legacy";
            oldSelection.getAsJsonArray("io_calls").get(0).getAsJsonObject()
                    .addProperty("site_id", oldSite);
            planned.set(null, new JsonArray());
            Class<?> oldInstrumented = instrumentClass(RpcFixture.class, oldSelection);
            assertEquals("reply", oldInstrumented.getMethod("reference").invoke(
                    oldInstrumented.getConstructor().newInstance()));
            assertTrue(latest(trace, "FAULT_POINT_OBSERVED", oldSite, "before") != null);
            assertNull(latest(trace, "FAULT_POINT_OBSERVED", oldSite, "after"));
        } finally {
            planned.set(null, previous);
            next.setInt(null, previousNext);
        }
    }

    private static String siteFor(JsonArray calls, String name) {
        for (int i = 0; i < calls.size(); i++) {
            JsonObject call = calls.get(i).getAsJsonObject();
            if (name.equals(call.get("call_name").getAsString())) {
                return call.get("site_id").getAsString();
            }
        }
        throw new IllegalArgumentException(name);
    }

    private static JsonObject nextOccurrence(JsonObject observed, String phase) {
        JsonObject wanted = new JsonObject();
        wanted.addProperty("marker", observed.get("marker").getAsString());
        wanted.addProperty("siteId", observed.get("siteId").getAsString());
        wanted.addProperty("sourceKey", observed.get("sourceKey").getAsString());
        wanted.addProperty("occurrence", observed.get("occurrenceAddress").getAsString());
        wanted.addProperty("hitOrdinal", observed.get("hitOrdinal").getAsInt() + 1);
        wanted.addProperty("occurrenceOrdinal",
                observed.get("occurrenceOrdinal").getAsInt() + 1);
        wanted.addProperty("phase", phase);
        wanted.addProperty("faultId", "test-" + phase);
        return wanted;
    }

    private static JsonObject latest(Path trace, String eventName, String site, String phase)
            throws IOException {
        JsonObject found = null;
        for (String line : Files.readAllLines(trace, StandardCharsets.UTF_8)) {
            JsonObject event = JsonParser.parseString(line).getAsJsonObject();
            if (eventName.equals(event.get("event").getAsString())
                    && event.has("siteId") && site.equals(event.get("siteId").getAsString())
                    && event.has("phase") && phase.equals(event.get("phase").getAsString())) {
                found = event;
            }
        }
        return found;
    }

    private static int invocationLine(String name, String owner) throws IOException {
        String resource = RpcFixture.class.getName().replace('.', '/') + ".class";
        try (InputStream input = RpcFixture.class.getClassLoader()
                .getResourceAsStream(resource)) {
            final int[] found = {-1};
            new ClassReader(input).accept(new ClassVisitor(Opcodes.ASM9) {
                @Override public MethodVisitor visitMethod(int access, String method,
                        String descriptor, String signature, String[] exceptions) {
                    if (!name.equals(method)) return null;
                    return new MethodVisitor(Opcodes.ASM9) {
                        int line;
                        @Override public void visitLineNumber(int number, Label start) {
                            line = number;
                        }
                        @Override public void visitMethodInsn(int opcode, String callOwner,
                                String callName, String callDescriptor, boolean isInterface) {
                            if (owner.equals(callOwner) && name.equals(callName)) found[0] = line;
                        }
                    };
                }
            }, 0);
            assertTrue("missing RPC invocation line for " + name, found[0] > 0);
            return found[0];
        }
    }

    private static Class<?> instrumentFixture() throws Exception {
        JsonObject selection = new JsonObject();
        selection.addProperty("target_method", METHOD);
        JsonObject spec = new JsonObject();
        spec.addProperty("signature", METHOD);
        spec.addProperty("owner", Fixture.class.getName().replace('.', '/'));
        spec.addProperty("name", "run");
        spec.addProperty("descriptor", "(Z)I");
        JsonArray specs = new JsonArray();
        specs.add(spec);
        JsonObject other = new JsonObject();
        other.addProperty("signature", OTHER_METHOD);
        other.addProperty("owner", Fixture.class.getName().replace('.', '/'));
        other.addProperty("name", "runOther");
        other.addProperty("descriptor", "()I");
        specs.add(other);
        JsonObject synchronizedMethod = new JsonObject();
        synchronizedMethod.addProperty("signature", SYNCHRONIZED_METHOD);
        synchronizedMethod.addProperty("owner", Fixture.class.getName().replace('.', '/'));
        synchronizedMethod.addProperty("name", "runSynchronized");
        synchronizedMethod.addProperty("descriptor", "()I");
        specs.add(synchronizedMethod);
        JsonObject userRethrow = new JsonObject();
        userRethrow.addProperty("signature", USER_RETHROW_METHOD);
        userRethrow.addProperty("owner", Fixture.class.getName().replace('.', '/'));
        userRethrow.addProperty("name", "runUserRethrow");
        userRethrow.addProperty("descriptor", "()V");
        specs.add(userRethrow);
        selection.add("method_specs", specs);
        JsonObject absentIo = new JsonObject();
        absentIo.addProperty("method", METHOD);
        absentIo.addProperty("site_id", METHOD + "#u999");
        absentIo.addProperty("callee", "<example.Io: void absent()>");
        absentIo.addProperty("line", 999);
        absentIo.addProperty("call_owner", "example/Io");
        absentIo.addProperty("call_name", "absent");
        absentIo.addProperty("call_descriptor", "()V");
        absentIo.addProperty("line_ordinal", 0);
        JsonArray ioCalls = new JsonArray();
        ioCalls.add(absentIo);
        selection.add("io_calls", ioCalls);
        selection.add("branches", new JsonArray());

        return instrumentClass(Fixture.class, selection);
    }

    private static Class<?> instrumentBpActor() throws Exception {
        JsonObject selection = new JsonObject();
        selection.addProperty("target_method", BP_METHOD);
        JsonObject spec = new JsonObject();
        spec.addProperty("signature", BP_METHOD);
        spec.addProperty("owner", BPServiceActor.class.getName().replace('.', '/'));
        spec.addProperty("name", "selectedIo");
        spec.addProperty("descriptor", "()V");
        JsonArray specs = new JsonArray();
        specs.add(spec);
        selection.add("method_specs", specs);
        JsonObject io = new JsonObject();
        io.addProperty("method", BP_METHOD);
        io.addProperty("site_id", BP_SITE);
        io.addProperty("callee", "<" + BPServiceActor.Sink.class.getName()
                + ": void write()>");
        io.addProperty("line", 12);
        io.addProperty("call_owner", BPServiceActor.Sink.class.getName().replace('.', '/'));
        io.addProperty("call_name", "write");
        io.addProperty("call_descriptor", "()V");
        io.addProperty("line_ordinal", 0);
        JsonArray ioCalls = new JsonArray();
        ioCalls.add(io);
        selection.add("io_calls", ioCalls);
        selection.add("branches", new JsonArray());
        return instrumentClass(BPServiceActor.class, selection);
    }

    private static Class<?> instrumentClass(Class<?> sourceClass, JsonObject selection)
            throws Exception {
        Method parse = SelectionAgent.class.getDeclaredMethod("parse", JsonObject.class);
        parse.setAccessible(true);
        Map<?, ?> plans = (Map<?, ?>) parse.invoke(null, selection);
        Class<?> transformerClass = Class.forName(SelectionAgent.class.getName() + "$Transformer");
        Constructor<?> constructor = transformerClass.getDeclaredConstructor(Map.class);
        constructor.setAccessible(true);
        ClassFileTransformer transformer = (ClassFileTransformer) constructor.newInstance(plans);
        String internalName = sourceClass.getName().replace('.', '/');
        byte[] original;
        try (InputStream input = sourceClass.getClassLoader().getResourceAsStream(
                internalName + ".class")) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            for (int size; (size = input.read(buffer)) != -1;) bytes.write(buffer, 0, size);
            original = bytes.toByteArray();
        }
        ClassLoader loader = new ClassLoader(sourceClass.getClassLoader()) {
            @Override protected Class<?> loadClass(String name, boolean resolve)
                    throws ClassNotFoundException {
                if (!name.equals(sourceClass.getName())) return super.loadClass(name, resolve);
                synchronized (getClassLoadingLock(name)) {
                    Class<?> existing = findLoadedClass(name);
                    if (existing == null) {
                        byte[] rewritten;
                        try {
                            rewritten = transformer.transform(this, internalName,
                                    null, null, original);
                        } catch (IllegalClassFormatException error) {
                            throw new ClassNotFoundException(name, error);
                        }
                        existing = defineClass(name, rewritten, 0, rewritten.length);
                    }
                    if (resolve) resolveClass(existing);
                    return existing;
                }
            }
        };
        return loader.loadClass(sourceClass.getName());
    }
}
