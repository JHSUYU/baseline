package edu.uva.liftlab.mallory.graphchecker.runtime;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.junit.Test;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/** Exercises the actual writer in separate JVMs so static recorder state cannot leak. */
public class CompactTraceEmissionTest {
    public static final class Harness {
        public static void main(String[] args) {
            System.setProperty("mallory.graphchecker.trace.file", args[0]);
            if ("compact".equals(args[1])) {
                System.setProperty("mallory.graphchecker.trace.compact", "true");
            }
            Object owner = new Object();
            MessageDoors.registerSource(owner, "test", "server", "server0", 0);
            long request = MessageDoors.beginRequest(owner, "get");
            MessageDoors.enterRegion("R.get", "get#entry", 0, owner);
            MessageDoors.coverage("get#block", owner);
            MessageDoors.faultDoorHit("get#io", owner);
            MessageDoors.exitRegion("R.get");
            MessageDoors.enterRegion("R.check", "check#entry", 0, owner);
            MessageDoors.targetCheck("get#target", owner, "FALSE");
            MessageDoors.exitRegion("R.check");
            MessageDoors.endRequest(request, "get");
        }
    }

    private static Path emit(String mode) throws Exception {
        Path trace = Files.createTempFile("mallory-" + mode + "-", ".jsonl");
        String java = Paths.get(System.getProperty("java.home"), "bin", "java")
                .toString();
        String classpath = System.getProperty("surefire.test.class.path",
                System.getProperty("java.class.path"));
        Process process = new ProcessBuilder(java, "-cp", classpath,
                Harness.class.getName(), trace.toString(), mode)
                .redirectErrorStream(true).start();
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        for (int size; (size = process.getInputStream().read(buffer)) != -1;) {
            output.write(buffer, 0, size);
        }
        assertEquals("writer JVM: " + new String(output.toByteArray(),
                StandardCharsets.UTF_8), 0, process.waitFor());
        return trace;
    }

    @Test public void defaultLegacyAndOptInCompactEmitEquivalentGraphFeedback()
            throws Exception {
        Path legacy = emit("legacy");
        Path compact = emit("compact");
        int compactKinds = 0;
        List<String> legacyLines = Files.readAllLines(legacy, StandardCharsets.UTF_8);
        List<String> compactLines = Files.readAllLines(compact, StandardCharsets.UTF_8);
        for (String line : legacyLines) {
            JsonObject row = new JsonParser().parse(line).getAsJsonObject();
            String kind = row.get("kind").getAsString();
            if ("COVERAGE".equals(kind) || "FAULT_DOOR".equals(kind)
                    || "REGION_COMPLETE".equals(kind)) {
                assertTrue(row.has("occurrence"));
                assertFalse(row.has("occurrenceRef"));
            }
        }
        for (String line : compactLines) {
            JsonObject row = new JsonParser().parse(line).getAsJsonObject();
            String kind = row.get("kind").getAsString();
            if ("COVERAGE".equals(kind) || "FAULT_DOOR".equals(kind)
                    || "REGION_COMPLETE".equals(kind)) {
                compactKinds++;
                assertFalse(row.has("occurrence"));
                assertEquals("ACTIVATION", row.get("occurrenceRef").getAsString());
            }
        }
        assertEquals(4, compactKinds);
        TrialGraph oldGraph = TrialGraph.read(legacy);
        TrialGraph newGraph = TrialGraph.read(compact);
        assertEquals(oldGraph.feedback("get#target", null),
                newGraph.feedback("get#target", null));
        Path oldRows = Files.createTempFile("mallory-old-graph-", ".jsonl");
        Path newRows = Files.createTempFile("mallory-new-graph-", ".jsonl");
        oldGraph.write(oldRows);
        newGraph.write(newRows);
        assertEquals(Files.readAllLines(oldRows), Files.readAllLines(newRows));
    }
}
