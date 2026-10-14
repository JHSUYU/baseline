package edu.uva.liftlab.mallory.graphchecker.runtime;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.junit.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class TaskHandoffTest {
    @Test public void compactOneUseTaskHandoffsRemainExact() throws Exception {
        Path trace = Files.createTempFile("mallory-task-handoff-", ".jsonl");
        String java = Paths.get(System.getProperty("java.home"), "bin", "java").toString();
        Process process = new ProcessBuilder(java,
                "-Dmallory.graphchecker.trace.file=" + trace,
                "-cp", System.getProperty("java.class.path"),
                TaskHandoffTrialMain.class.getName()).redirectErrorStream(true).start();
        byte[] output = new byte[8192];
        int used = process.getInputStream().read(output);
        assertEquals(0, process.waitFor());
        assertTrue(used < 0 || new String(output, 0, used,
                StandardCharsets.UTF_8).isEmpty());
        List<JsonObject> rows = new ArrayList<>();
        for (String line : Files.readAllLines(trace, StandardCharsets.UTF_8)) {
            rows.add(new JsonParser().parse(line).getAsJsonObject());
        }
        List<JsonObject> submits = new ArrayList<>();
        List<JsonObject> claims = new ArrayList<>();
        for (JsonObject row : rows) {
            if ("TASK_SUBMIT".equals(kind(row))) submits.add(row);
            if ("TASK_CLAIM".equals(kind(row))
                    && row.has("producerEndpointId")) claims.add(row);
            if ("TARGET_CHECK".equals(kind(row))) {
                // The submit path above has 100 frames. No worker target may
                // inherit that path: it starts at a compact causal anchor.
                assertTrue(row.get("occurrence").getAsString().length() < 500);
            }
        }
        assertEquals(4, submits.size());
        assertEquals(3, claims.size());
        assertTrue(submits.get(0).get("occurrence").getAsString().length() > 1000);
        assertFalse(submits.get(0).get("producerEndpointId").getAsString()
                .equals(submits.get(1).get("producerEndpointId").getAsString()));
        TrialGraph graph = TrialGraph.read(trace);
        assertTrue(graph.feedback("task-first", null).getAsJsonArray(
                "closureEdgeFamilies").toString().contains("HANDOFF"));
        assertTrue(graph.feedback("task-nested", null).getAsJsonArray(
                "closureEdgeFamilies").toString().contains("HANDOFF"));
        assertTrue(graph.feedback("task-second", null).getAsJsonArray(
                "closureEdgeFamilies").toString().contains("HANDOFF"));
        assertFalse(graph.feedback("task-ambient", null).getAsJsonArray(
                "closureEdgeFamilies").toString().contains("HANDOFF"));
        assertTrue(rows.stream().anyMatch(row -> "TASK_TICKET_REUSED".equals(
                row.has("gapKind") ? row.get("gapKind").getAsString() : "")));

        // Even a corrupt duplicate claim row cannot manufacture two causal
        // successors from one submit ticket.
        Path ambiguous = Files.createTempFile("mallory-task-ambiguous-", ".jsonl");
        List<String> duplicate = new ArrayList<>(
                Files.readAllLines(trace, StandardCharsets.UTF_8));
        duplicate.add(claims.get(0).toString());
        Files.write(ambiguous, duplicate, StandardCharsets.UTF_8);
        TrialGraph rejected = TrialGraph.read(ambiguous);
        assertFalse(rejected.feedback("task-first", null).getAsJsonArray(
                "closureEdgeFamilies").toString().contains("HANDOFF"));
    }

    private static String kind(JsonObject row) {
        return row.has("kind") ? row.get("kind").getAsString() : "";
    }
}
