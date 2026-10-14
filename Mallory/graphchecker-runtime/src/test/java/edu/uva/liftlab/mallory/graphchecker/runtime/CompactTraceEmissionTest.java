package edu.uva.liftlab.mallory.graphchecker.runtime;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.junit.Test;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
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
            MessageDoors.enterRegion("R.inner", "inner#entry", 0, owner);
            MessageDoors.coverage("inner#block", owner);
            MessageDoors.exitRegion("R.inner");
            MessageDoors.exitRegion("R.get");
            if (args.length > 2 && "deep".equals(args[2])) {
                for (int i = 0; i < 50; i++) {
                    MessageDoors.enterRegion("R.deep" + i, "deep#" + i, 0, owner);
                }
                MessageDoors.coverage("deep#block", owner);
                for (int i = 49; i >= 0; i--) {
                    MessageDoors.exitRegion("R.deep" + i);
                }
            }
            MessageDoors.enterRegion("R.check", "check#entry", 0, owner);
            MessageDoors.targetCheck("get#target", owner, "FALSE");
            MessageDoors.exitRegion("R.check");
            MessageDoors.endRequest(request, "get");
        }
    }

    private static Path emit(String mode) throws Exception {
        return emit(mode, false);
    }

    private static Path emit(String mode, boolean deep) throws Exception {
        Path trace = Files.createTempFile("mallory-" + mode + "-", ".jsonl");
        String java = Paths.get(System.getProperty("java.home"), "bin", "java")
                .toString();
        String classpath = System.getProperty("surefire.test.class.path",
                System.getProperty("java.class.path"));
        Process process = new ProcessBuilder(java, "-cp", classpath,
                Harness.class.getName(), trace.toString(), mode,
                deep ? "deep" : "shallow")
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
        int parentRefs = 0;
        int activationDeltas = 0;
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
            if ("ACTIVATION".equals(kind) || "REGION_COMPLETE".equals(kind)) {
                if (row.has("parentOccurrenceRef")) {
                    parentRefs++;
                    assertFalse(row.has("parentOccurrence"));
                    assertEquals("ACTIVATION",
                            row.get("parentOccurrenceRef").getAsString());
                }
            }
            if ("ACTIVATION".equals(kind) && row.has("indexSuffix")) {
                activationDeltas++;
                assertFalse(row.has("occurrence"));
                assertTrue(row.has("parentIndexHash"));
            }
        }
        assertEquals(6, compactKinds);
        assertEquals(2, parentRefs);
        assertEquals(1, activationDeltas);
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

    @Test public void deepActivationDeltaIsSmallerAndReconstructsExactGraph()
            throws Exception {
        Path legacy = emit("legacy", true);
        Path compact = emit("compact", true);
        assertTrue("exact delta should remove repeated deep prefixes",
                Files.size(compact) * 2 < Files.size(legacy));
        TrialGraph oldGraph = TrialGraph.read(legacy);
        TrialGraph newGraph = TrialGraph.read(compact);
        assertEquals(oldGraph.feedback("get#target", null),
                newGraph.feedback("get#target", null));
        Path oldRows = Files.createTempFile("mallory-old-deep-graph-", ".jsonl");
        Path newRows = Files.createTempFile("mallory-new-deep-graph-", ".jsonl");
        oldGraph.write(oldRows);
        newGraph.write(newRows);
        assertEquals(Files.readAllLines(oldRows), Files.readAllLines(newRows));
    }

    @Test public void corruptedActivationDeltaFailsClosed() throws Exception {
        Path compact = emit("compact", true);
        List<String> lines = new ArrayList<>(Files.readAllLines(compact,
                StandardCharsets.UTF_8));
        boolean changed = false;
        for (int i = 0; i < lines.size(); i++) {
            JsonObject row = new JsonParser().parse(lines.get(i)).getAsJsonObject();
            if (!row.has("indexSuffix")) continue;
            row.addProperty("indexSuffix", row.get("indexSuffix").getAsString()
                    + "/bogus#frame@0");
            lines.set(i, row.toString());
            changed = true;
            break;
        }
        assertTrue(changed);
        Path corrupted = Files.createTempFile("mallory-corrupt-delta-", ".jsonl");
        Files.write(corrupted, lines, StandardCharsets.UTF_8);
        try {
            TrialGraph.read(corrupted);
            org.junit.Assert.fail("corrupted child identity must be rejected");
        } catch (IllegalArgumentException expected) {
            assertTrue(expected.getMessage().contains(
                    "compact activation does not reconstruct exact identity"));
        }
    }
}
