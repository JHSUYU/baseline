package edu.uva.liftlab.mallory.nativefault;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import edu.uva.liftlab.graphchecker.contract.SessionReader;
import org.junit.Test;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.LineNumberNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.Opcodes;

import java.io.File;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.util.Collections;
import java.util.List;

import static org.junit.Assert.*;

/** Exercises two fresh JVMs and the original GraphChecker SessionReader. */
public final class NativeFaultWeaverTest {
    private static final String FIXTURE = NativeFaultFixture.class.getName();
    private static final String CLASS_FILE = FIXTURE.replace('.', '/') + ".class";

    @Test public void injectedIoHasExactFreshReceiptsAndTargetThrow() throws Exception {
        Path root = Files.createTempDirectory("native-fault-fixture-");
        Path classes = root.resolve("woven");
        Path classFile = classes.resolve(CLASS_FILE);
        Files.createDirectories(classFile.getParent());
        try (InputStream input = getClass().getClassLoader().getResourceAsStream(CLASS_FILE)) {
            assertNotNull(input);
            Files.copy(input, classFile);
        }
        JsonObject manifest = manifest(classFile);
        Path manifestFile = root.resolve("weave_manifest.json");
        Files.write(manifestFile, manifest.toString().getBytes(StandardCharsets.UTF_8));
        NativeFaultWeaver.weave(classes, manifestFile);
        assertTrue(Files.isRegularFile(classes.resolve(
                "edu/uva/liftlab/graphchecker/runtime/NativeFaultHooks.class")));

        Path healthy = root.resolve("healthy");
        int healthyExit = junit(classes, healthy, "{\"faults\":[]}");
        assertEquals(0, healthyExit);
        List<JsonObject> seed = receipts(healthy.resolve("fault-events.jsonl"));
        assertEquals(1, seed.size());
        assertEquals("FAULT_DOOR", seed.get(0).get("kind").getAsString());
        JsonObject fault = new JsonObject();
        for (String field : new String[] {"siteId", "node", "actorEpochOrdinal",
                "ordinal", "exceptionClass"}) fault.add(field, seed.get(0).get(field));
        assertEquals("fixture-node", fault.get("node").getAsString());
        assertEquals(0, fault.get("actorEpochOrdinal").getAsInt());
        assertEquals(1, fault.get("ordinal").getAsInt());

        JsonObject plan = new JsonObject();
        JsonArray faults = new JsonArray();
        faults.add(fault);
        plan.add("faults", faults);
        Path trial = root.resolve("trial");
        assertNotEquals(0, junit(classes, trial, plan.toString()));
        List<JsonObject> events = receipts(trial.resolve("fault-events.jsonl"));
        assertEquals(3, events.size());
        assertEquals("FAULT_DOOR", events.get(0).get("kind").getAsString());
        assertEquals("FAULT_APPLIED", events.get(1).get("kind").getAsString());
        assertEquals("TARGET_THROW", events.get(2).get("kind").getAsString());
        String occurrence = events.get(0).get("occurrenceId").getAsString();
        assertEquals(occurrence, events.get(1).get("occurrenceId").getAsString());
        assertEquals(occurrence, events.get(2).get("occurrenceId").getAsString());
        assertEquals("java.io.IOException", events.get(2).get("exceptionClass").getAsString());
        assertEquals("fixture-target-throw", events.get(2).get("siteId").getAsString());
        assertTrue(events.get(0).get("seq").getAsInt() < events.get(1).get("seq").getAsInt());
        assertTrue(events.get(1).get("seq").getAsInt() < events.get(2).get("seq").getAsInt());

        List<SessionReader> sessions = SessionReader.readAll(trial, Collections.emptyList());
        assertEquals(1, sessions.size());
        assertEquals(1, sessions.get(0).targets().size());
        assertEquals(occurrence, sessions.get(0).targets().get(0).occurrence().id());
        assertTrue(sessions.get(0).targets().get(0).reachedAnchor());
    }

    @Test public void ambiguousStaticSiteRefusesWithoutWritingAnyClass() throws Exception {
        Path root = Files.createTempDirectory("native-fault-ambiguous-");
        Path classes = root.resolve("classes");
        Path classFile = classes.resolve(CLASS_FILE);
        Files.createDirectories(classFile.getParent());
        try (InputStream input = getClass().getClassLoader().getResourceAsStream(CLASS_FILE)) {
            Files.copy(input, classFile);
        }
        byte[] original = Files.readAllBytes(classFile);
        JsonObject manifest = manifest(classFile);
        JsonObject duplicate = manifest.getAsJsonArray("doors").get(0).getAsJsonObject().deepCopy();
        duplicate.addProperty("siteId", "ambiguous-other-site");
        manifest.getAsJsonArray("doors").add(duplicate);
        Path manifestFile = root.resolve("manifest.json");
        Files.write(manifestFile, manifest.toString().getBytes(StandardCharsets.UTF_8));
        try {
            NativeFaultWeaver.weave(classes, manifestFile);
            fail("must refuse cardinality mismatch");
        } catch (IllegalArgumentException expected) {
            assertTrue(expected.getMessage().contains("ambiguous"));
        }
        assertArrayEquals(original, Files.readAllBytes(classFile));
    }

    private static JsonObject manifest(Path classFile) throws Exception {
        ClassNode tree = new ClassNode();
        new ClassReader(Files.readAllBytes(classFile)).accept(tree, 0);
        int doorLine = -1, throwLine = -1, doorBci = -1, throwBci = -1;
        java.util.Map<String, java.util.List<Integer>> offsets =
                BytecodeOffsets.instructions(Files.readAllBytes(classFile));
        for (MethodNode method : tree.methods) {
            int line = -1;
            int index = 0;
            for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null;
                    insn = insn.getNext()) {
                if (insn instanceof LineNumberNode) line = ((LineNumberNode) insn).line;
                int bci = insn.getOpcode() < 0 ? -1
                        : offsets.get(method.name + '\n' + method.desc).get(index++);
                if (method.name.equals("io") && insn instanceof MethodInsnNode) {
                    MethodInsnNode call = (MethodInsnNode) insn;
                    if (call.owner.equals("java/io/FileOutputStream")
                            && call.name.equals("write")) {
                        doorLine = line;
                        doorBci = bci;
                    }
                }
                if (method.name.equals("target") && insn.getOpcode() == Opcodes.ATHROW) {
                    throwLine = line;
                    throwBci = bci;
                }
            }
        }
        assertTrue(doorLine > 0 && throwLine > 0 && doorBci >= 0 && throwBci >= 0);
        JsonObject door = new JsonObject();
        door.addProperty("clazz", FIXTURE);
        door.addProperty("method", "io");
        door.addProperty("descriptor", "()V");
        door.addProperty("line", doorLine);
        door.addProperty("unitIndex", 11);
        door.addProperty("bytecodeOffset", doorBci);
        door.addProperty("siteId", "fixture-io-door");
        door.addProperty("callee", "<java.io.FileOutputStream: void write(byte[])>");
        door.addProperty("exceptionClass", "java.io.IOException");
        JsonObject target = new JsonObject();
        target.addProperty("clazz", FIXTURE);
        target.addProperty("method", "target");
        target.addProperty("descriptor", "(Ljava/io/IOException;)V");
        target.addProperty("line", throwLine);
        target.addProperty("bytecodeOffset", throwBci);
        target.addProperty("siteId", "fixture-target-throw");
        target.addProperty("kind", "THROW");
        target.addProperty("exceptionClass", "java.io.IOException");
        JsonObject manifest = new JsonObject();
        JsonArray doors = new JsonArray(); doors.add(door); manifest.add("doors", doors);
        JsonArray targets = new JsonArray(); targets.add(target); manifest.add("targets", targets);
        return manifest;
    }

    private static int junit(Path classes, Path run, String plan) throws Exception {
        Files.createDirectories(run);
        Path planFile = run.resolve("fault-plan.json");
        Files.write(planFile, plan.getBytes(StandardCharsets.UTF_8));
        Path engine = Paths.get("../static_scope_port/original_engine/target/")
                .resolve("mallory-original-graphchecker-seed-1.0-SNAPSHOT.jar")
                .toAbsolutePath().normalize();
        Path dependencies = Paths.get("../static_scope_port/original_engine/target/native-original-dependencies.txt")
                .toAbsolutePath().normalize();
        String cp = classes + File.pathSeparator
                + Paths.get("target/test-classes").toAbsolutePath() + File.pathSeparator
                + engine + File.pathSeparator
                + new String(Files.readAllBytes(dependencies), StandardCharsets.UTF_8).trim();
        ProcessBuilder builder = new ProcessBuilder("java",
                "-Dfixture.result=" + run.resolve("vm-result.json"),
                "-Dfixture.file=" + run.resolve("io.bin"),
                "-cp", cp, "org.junit.runner.JUnitCore", FIXTURE);
        builder.directory(run.toFile());
        builder.environment().put("MALLORY_NATIVE_FAULT_PLAN", planFile.toString());
        builder.environment().put("MALLORY_NATIVE_FAULT_EVENTS",
                run.resolve("fault-events.jsonl").toString());
        builder.environment().put("CAUSYNTH_CONCOLIC_SESSIONS",
                run.resolve("sessions").toString());
        builder.redirectErrorStream(true);
        builder.redirectOutput(run.resolve("junit.log").toFile());
        Process process = builder.start();
        assertTrue("fixture JVM timed out", process.waitFor(30,
                java.util.concurrent.TimeUnit.SECONDS));
        return process.exitValue();
    }

    private static List<JsonObject> receipts(Path file) throws Exception {
        List<JsonObject> rows = new java.util.ArrayList<>();
        for (String line : Files.readAllLines(file, StandardCharsets.UTF_8)) {
            rows.add(new JsonParser().parse(line).getAsJsonObject());
        }
        return rows;
    }
}
