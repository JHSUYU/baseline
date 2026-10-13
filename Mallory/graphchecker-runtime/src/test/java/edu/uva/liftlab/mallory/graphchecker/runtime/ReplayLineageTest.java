package edu.uva.liftlab.mallory.graphchecker.runtime;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertTrue;

public final class ReplayLineageTest {
    private static final class Run {
        final List<String> ids;
        final Path trace;
        Run(List<String> ids, Path trace) { this.ids = ids; this.trace = trace; }
    }

    private static Run trial(String correlation) throws Exception {
        Path trace = Files.createTempFile("mallory-replay-", ".jsonl");
        String javaExecutable = Paths.get(System.getProperty("java.home"), "bin", "java").toString();
        Process process = new ProcessBuilder(javaExecutable, "-cp", System.getProperty("java.class.path"),
                ReplayLineageTrialMain.class.getName(), correlation, trace.toString())
                .redirectErrorStream(true).start();
        byte[] output = readAll(process.getInputStream());
        assertEquals(new String(output, StandardCharsets.UTF_8), 0, process.waitFor());
        List<String> lines = new ArrayList<>(Files.readAllLines(trace,
                StandardCharsets.UTF_8));
        String[] parts = new String(output, StandardCharsets.UTF_8).trim().split("\\R");
        assertEquals(4, parts.length);
        assertTrue(lines.stream().anyMatch(line -> line.contains("\"kind\":\"ATTACH\"")));
        assertTrue(TrialGraph.read(trace).feedback("target", null)
                .getAsJsonArray("closureEdgeFamilies").toString().contains("WIRE"));
        return new Run(java.util.Arrays.asList(parts), trace);
    }

    private static byte[] readAll(java.io.InputStream stream) throws Exception {
        java.io.ByteArrayOutputStream output = new java.io.ByteArrayOutputStream();
        byte[] buffer = new byte[4096];
        int count;
        while ((count = stream.read(buffer)) != -1) output.write(buffer, 0, count);
        return output.toByteArray();
    }

    @Test public void rpcCorrelationChangesExactIdsButNotRecursiveReplayLineage()
            throws Exception {
        Run first = trial("random-client-a:7");
        Run second = trial("random-client-b:7");
        assertNotEquals(first.ids.get(0), second.ids.get(0));
        assertNotEquals(first.ids.get(2), second.ids.get(2));
        assertEquals(first.ids.get(1), second.ids.get(1));
        assertEquals(first.ids.get(3), second.ids.get(3));
        assertNotEquals(first.ids.get(1), first.ids.get(3));
        for (Run run : new Run[] {first, second}) {
            int doors = 0;
            for (String line : Files.readAllLines(run.trace, StandardCharsets.UTF_8)) {
                JsonObject row = JsonParser.parseString(line).getAsJsonObject();
                if (!"FAULT_DOOR".equals(row.get("kind").getAsString())) continue;
                doors++;
                assertFalse(row.get("replayOccurrenceId").getAsString().isEmpty());
            }
            assertEquals(2, doors);
        }
    }
}
