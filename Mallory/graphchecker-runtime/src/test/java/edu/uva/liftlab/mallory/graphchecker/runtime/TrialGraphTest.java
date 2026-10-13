package edu.uva.liftlab.mallory.graphchecker.runtime;

import com.google.gson.JsonObject;
import org.junit.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.zip.GZIPOutputStream;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class TrialGraphTest {
    @Test public void compressedAndPlainStreamingTracesAgree() throws Exception {
        String lines = row("kind", "ACTIVATION", "occurrenceId", "o1",
                "occurrence", "o1-render", "node", "server0", "regionId", "R",
                "seq", 1) + "\n"
                + row("kind", "COVERAGE", "occurrenceId", "o1",
                "siteId", "block1", "seq", 2) + "\n"
                + "invalid-json\n"
                + row("kind", "TARGET_CHECK", "occurrenceId", "o1",
                "siteId", "T", "outcome", "FALSE", "seq", 3) + "\n";
        Path plain = Files.createTempFile("mallory-graph-stream-", ".jsonl");
        Path compressed = Files.createTempFile("mallory-graph-stream-", ".jsonl.gz");
        Files.write(plain, lines.getBytes(StandardCharsets.UTF_8));
        try (GZIPOutputStream output = new GZIPOutputStream(
                Files.newOutputStream(compressed))) {
            output.write(lines.getBytes(StandardCharsets.UTF_8));
        }
        String expected = TrialGraph.read(plain).feedback("T", null).toString();
        assertEquals(expected, TrialGraph.read(compressed).feedback("T", null).toString());
        assertEquals(1, TrialGraph.read(compressed).feedback("T", null)
                .getAsJsonObject("gaps").get("TRACE_ROW_INVALID").getAsInt());
    }

    private static JsonObject row(Object... fields) {
        JsonObject result = new JsonObject();
        for (int i = 0; i < fields.length; i += 2) {
            Object value = fields[i + 1];
            if (value instanceof Number) result.addProperty((String) fields[i], (Number) value);
            else result.addProperty((String) fields[i], String.valueOf(value));
        }
        return result;
    }

    private static TrialGraph graph(JsonObject... rows) throws Exception {
        Path trace = Files.createTempFile("mallory-gc-graph-", ".jsonl");
        StringBuilder content = new StringBuilder();
        for (JsonObject row : rows) content.append(row).append('\n');
        Files.write(trace, content.toString().getBytes(StandardCharsets.UTF_8));
        return TrialGraph.read(trace);
    }

    @Test public void joinsOnlyConfirmedTransportAndExactVersion() throws Exception {
        JsonObject prepared = row("kind", "WIRE_PREPARED", "occurrenceId", "a",
                "producerEndpointId", "pa");
        JsonObject export = row("kind", "EXPORT", "occurrenceId", "a",
                "producerEndpointId", "pa", "producer", "sender", "transport", "RPC",
                "correlationId", "7", "attemptId", "0", "half", "REQUEST");
        JsonObject attach = row("kind", "ATTACH", "occurrenceId", "b",
                "producerEndpointId", "pa", "producerOccurrenceId", "a",
                "producer", "sender", "consumerEndpointId", "cb",
                "transport", "RPC", "correlationId", "7", "attemptId", "0",
                "half", "REQUEST");
        JsonObject write = row("kind", "WRITE", "occurrenceId", "b",
                "writerEndpointId", "wb", "locationVersion", "file@v3", "seq", 4);
        JsonObject read = row("kind", "READ", "occurrenceId", "c",
                "readerEndpointId", "rc", "writerEndpointId", "wb",
                "writerOccurrenceId", "b", "locationVersion", "file@v3", "seq", 5);
        JsonObject target = row("kind", "TARGET_CHECK", "occurrenceId", "c",
                "siteId", "target");
        TrialGraph unconfirmed = graph(prepared, attach, write, read, target);
        assertEquals(2, unconfirmed.closure("target").size());
        assertFalse(unconfirmed.closure("target").contains("a"));
        TrialGraph confirmed = graph(prepared, export, attach, write, read, target);
        assertEquals(3, confirmed.closure("target").size());
        assertTrue(confirmed.closure("target").containsAll(Arrays.asList("a", "b", "c")));
        assertEquals(1, confirmed.feedback("target", unconfirmed)
                .get("newClosureEdges").getAsInt());
    }

    @Test public void rejectsAmbiguousWritesAndMismatchedMessages() throws Exception {
        JsonObject export = row("kind", "EXPORT", "occurrenceId", "a",
                "producerEndpointId", "pa", "producer", "sender", "transport", "RPC",
                "correlationId", "7", "attemptId", "0", "half", "REQUEST");
        JsonObject attach = row("kind", "ATTACH", "occurrenceId", "b",
                "producerEndpointId", "pa", "producerOccurrenceId", "a",
                "producer", "sender", "consumerEndpointId", "cb",
                "transport", "RPC", "correlationId", "7", "attemptId", "1",
                "half", "REQUEST");
        JsonObject write = row("kind", "WRITE", "occurrenceId", "b",
                "writerEndpointId", "wb", "locationVersion", "file@v3", "seq", 4);
        JsonObject secondWrite = row("kind", "WRITE", "occurrenceId", "x",
                "writerEndpointId", "wx", "locationVersion", "file@v3", "seq", 5);
        JsonObject read = row("kind", "READ", "occurrenceId", "c",
                "readerEndpointId", "rc", "writerEndpointId", "wb",
                "writerOccurrenceId", "b", "locationVersion", "file@v3", "seq", 6);
        JsonObject target = row("kind", "TARGET_CHECK", "occurrenceId", "c",
                "siteId", "target");
        TrialGraph trial = graph(export, attach, write, secondWrite, read, target);
        assertEquals(1, trial.closure("target").size());
        assertEquals(1, trial.feedback("target", null).getAsJsonObject("gaps")
                .get("WIRE_EXPORT_MISMATCH").getAsInt());
        assertEquals(1, trial.feedback("target", null).getAsJsonObject("gaps")
                .get("STATE_WRITE_AMBIGUOUS").getAsInt());
    }

    @Test public void reportsOnlyAttributedExactTargetOutcomes() throws Exception {
        TrialGraph trial = graph(
                row("kind", "TARGET_CHECK", "occurrenceId", "a",
                        "siteId", "target", "outcome", "FALSE"),
                row("kind", "TARGET_THROW", "occurrenceId", "a",
                        "siteId", "target", "exceptionClass", "java.io.IOException"),
                row("kind", "TARGET_THROW", "occurrenceId", "",
                        "siteId", "target", "exceptionClass", "java.io.IOException"),
                row("kind", "TARGET_THROW", "occurrenceId", "b",
                        "siteId", "other", "exceptionClass", "java.lang.IllegalStateException"));
        JsonObject feedback = trial.feedback("target", null);
        assertEquals(1, feedback.get("targetChecks").getAsInt());
        assertEquals(1, feedback.get("targetThrows").getAsInt());
        assertEquals("java.io.IOException",
                feedback.getAsJsonArray("targetThrowClasses").get(0).getAsString());
        assertEquals("FALSE",
                feedback.getAsJsonArray("targetCheckOutcomes").get(0).getAsString());
    }

    @Test public void eachThrowKeepsItsOwnCausalClosure() throws Exception {
        TrialGraph trial = graph(
                row("kind", "ACTIVATION", "occurrenceId", "request-a",
                        "regionId", "R", "node", "server", "seq", 1),
                row("kind", "ACTIVATION", "occurrenceId", "request-b",
                        "regionId", "R", "node", "server", "seq", 2),
                row("kind", "TARGET_CHECK", "occurrenceId", "request-a",
                        "siteId", "check", "node", "server", "seq", 4),
                row("kind", "TARGET_THROW", "occurrenceId", "request-b",
                        "siteId", "throw", "node", "server",
                        "exceptionClass", "java.io.IOException", "seq", 6));
        JsonObject feedback = trial.feedback("check", null);
        assertEquals(1, feedback.getAsJsonObject("closureOccurrenceCutoffs").size());
        JsonObject throwClosure = feedback.getAsJsonArray("targetThrowClosures")
                .get(0).getAsJsonObject();
        assertEquals(1, throwClosure.getAsJsonObject("closureOccurrenceCutoffs").size());
        assertEquals(6, throwClosure.getAsJsonObject("closureOccurrenceCutoffs")
                .get("request-b").getAsInt());
        assertFalse(throwClosure.getAsJsonObject("closureOccurrenceCutoffs")
                .has("request-a"));
    }

    @Test public void staticMayDoorDoesNotBecomeObservedClosure() throws Exception {
        TrialGraph trial = graph(
                row("kind", "ACTIVATION", "occurrenceId", "target-occ",
                        "regionId", "R.target", "node", "server#epoch0"),
                row("kind", "ACTIVATION", "occurrenceId", "writer-occ",
                        "regionId", "R.writer", "node", "server#epoch0"),
                row("kind", "TARGET_CHECK", "occurrenceId", "target-occ",
                        "siteId", "target"),
                row("kind", "FAULT_DOOR", "occurrenceId", "writer-occ",
                        "siteId", "door"));
        Path scopeFile = Files.createTempFile("mallory-gc-static-", ".jsonl");
        String scope = row("kind", "STATIC_SCOPE_SITE", "role", "TARGET_SITE",
                "regionId", "R.target", "siteId", "target") + "\n"
                + row("kind", "STATIC_SCOPE_SITE", "role", "READ_SITE",
                "regionId", "R.target", "siteId", "read", "cell", "C") + "\n"
                + row("kind", "STATIC_SCOPE_SITE", "role", "WRITE_SITE",
                "regionId", "R.writer", "siteId", "write", "cell", "C") + "\n"
                + row("kind", "STATIC_SCOPE_SITE", "role", "DOOR_SITE",
                "regionId", "R.writer", "siteId", "door") + "\n";
        Files.write(scopeFile, scope.getBytes(StandardCharsets.UTF_8));
        JsonObject feedback = trial.feedback("target", null, StaticScope.read(scopeFile));
        assertEquals(0, feedback.getAsJsonArray("closureDoorSiteIds").size());
        assertEquals("door", feedback.getAsJsonArray("staticMayObservedDoorSiteIds")
                .get(0).getAsString());
        assertEquals(1, feedback.getAsJsonArray("staticMayRelations").size());
        assertEquals(0, feedback.get("closureEdges").getAsInt());
    }

    @Test public void aMessageReceivedAfterTheTargetCannotCauseThatTarget() throws Exception {
        JsonObject export = row("kind", "EXPORT", "occurrenceId", "sender",
                "producerEndpointId", "p", "producer", "sender-endpoint",
                "transport", "RPC", "correlationId", "8", "attemptId", "0",
                "half", "REQUEST", "seq", 2);
        JsonObject attach = row("kind", "ATTACH", "occurrenceId", "receiver",
                "producerEndpointId", "p", "producerOccurrenceId", "sender",
                "producer", "sender-endpoint", "consumerEndpointId", "c",
                "transport", "RPC", "correlationId", "8", "attemptId", "0",
                "half", "REQUEST", "seq", 7);
        TrialGraph before = graph(export, attach,
                row("kind", "TARGET_CHECK", "occurrenceId", "receiver",
                        "siteId", "target", "seq", 5));
        assertFalse(before.closure("target").contains("sender"));
        assertEquals(0, before.feedback("target", null).get("closureEdges").getAsInt());
        TrialGraph after = graph(export, attach,
                row("kind", "TARGET_CHECK", "occurrenceId", "receiver",
                        "siteId", "target", "seq", 8));
        assertTrue(after.closure("target").contains("sender"));
        assertEquals(1, after.feedback("target", null).get("closureEdges").getAsInt());
    }

    @Test public void laterEventsInTargetOccurrenceAreNotClosureFeedback() throws Exception {
        TrialGraph trial = graph(
                row("kind", "ACTIVATION", "occurrenceId", "target-occ",
                        "regionId", "target-region", "node", "server", "seq", 1),
                row("kind", "FAULT_DOOR", "occurrenceId", "target-occ",
                        "siteId", "before-door", "seq", 2),
                row("kind", "COVERAGE", "occurrenceId", "target-occ",
                        "siteId", "before-branch", "seq", 3),
                row("kind", "TARGET_CHECK", "occurrenceId", "target-occ",
                        "siteId", "target", "seq", 4),
                row("kind", "FAULT_DOOR", "occurrenceId", "target-occ",
                        "siteId", "after-door", "seq", 5),
                row("kind", "COVERAGE", "occurrenceId", "target-occ",
                        "siteId", "after-branch", "seq", 6));
        JsonObject feedback = trial.feedback("target", null);
        assertEquals(4, feedback.getAsJsonObject("closureOccurrenceCutoffs")
                .get("target-occ").getAsInt());
        assertEquals(1, feedback.get("closureCoverageSites").getAsInt());
        assertEquals("before-branch", feedback.getAsJsonArray("closureCoverageSiteIds")
                .get(0).getAsString());
        assertEquals("before-door", feedback.getAsJsonArray("closureDoorSiteIds")
                .get(0).getAsString());
    }

    @Test public void rejectsRetrocausalWireAttachment() throws Exception {
        TrialGraph trial = graph(
                row("kind", "ATTACH", "occurrenceId", "receiver",
                        "producerEndpointId", "p", "producerOccurrenceId", "sender",
                        "producer", "sender-endpoint", "consumerEndpointId", "c",
                        "transport", "RPC", "correlationId", "8", "attemptId", "0",
                        "half", "REQUEST", "seq", 2),
                row("kind", "EXPORT", "occurrenceId", "sender",
                        "producerEndpointId", "p", "producer", "sender-endpoint",
                        "transport", "RPC", "correlationId", "8", "attemptId", "0",
                        "half", "REQUEST", "seq", 3),
                row("kind", "TARGET_CHECK", "occurrenceId", "receiver",
                        "siteId", "target", "seq", 4));
        assertEquals(0, trial.feedback("target", null).get("closureEdges").getAsInt());
        assertEquals(1, trial.feedback("target", null).getAsJsonObject("gaps")
                .get("WIRE_ORDER_INVALID").getAsInt());
    }

    @Test public void countsAnExistingEdgeWhenItNewlyEntersTargetClosure() throws Exception {
        JsonObject export = row("kind", "EXPORT", "occurrenceId", "sender",
                "node", "sender-node", "regionId", "R.send",
                "producerEndpointId", "p", "producer", "sender-endpoint",
                "transport", "RPC", "correlationId", "8", "attemptId", "0",
                "half", "REQUEST", "seq", 1);
        JsonObject attach = row("kind", "ATTACH", "occurrenceId", "receiver",
                "node", "receiver-node", "regionId", "R.recv",
                "producerEndpointId", "p", "producerOccurrenceId", "sender",
                "producer", "sender-endpoint", "consumerEndpointId", "c",
                "transport", "RPC", "correlationId", "8", "attemptId", "0",
                "half", "REQUEST", "seq", 2);
        JsonObject target = row("kind", "TARGET_CHECK", "occurrenceId", "target-occ",
                "node", "target-node", "regionId", "R.target",
                "siteId", "target", "seq", 8);
        TrialGraph before = graph(export, attach, target);
        TrialGraph after = graph(export, attach,
                row("kind", "WRITE", "occurrenceId", "receiver",
                        "writerEndpointId", "w", "locationVersion", "cell@v1",
                        "seq", 3),
                row("kind", "READ", "occurrenceId", "target-occ",
                        "readerEndpointId", "r", "writerEndpointId", "w",
                        "writerOccurrenceId", "receiver",
                        "locationVersion", "cell@v1", "seq", 4), target);
        JsonObject feedback = after.feedback("target", before);
        assertEquals(2, feedback.get("newClosureNodes").getAsInt());
        assertEquals(2, feedback.get("newClosureEdges").getAsInt());
    }

    @Test public void throwOnlyTargetHasStaticScopeAnchor() throws Exception {
        TrialGraph trial = graph(row("kind", "TARGET_THROW",
                "occurrenceId", "target-occ", "regionId", "R.target",
                "siteId", "throw-site", "exceptionClass", "java.io.IOException",
                "seq", 3));
        Path scopeFile = Files.createTempFile("mallory-gc-throw-scope-", ".jsonl");
        Files.write(scopeFile, (row("kind", "STATIC_SCOPE_SITE", "role", "THROW_SITE",
                "regionId", "R.target", "siteId", "throw-site") + "\n")
                .getBytes(StandardCharsets.UTF_8));
        JsonObject feedback = trial.feedback("throw-site", null,
                StaticScope.read(scopeFile));
        assertTrue(feedback.get("staticScopeTargetFound").getAsBoolean());
        assertTrue(feedback.get("targetReached").getAsBoolean());
    }

    @Test public void parentFirstSeenAsLaterExportKeepsEarlierAttachTime() throws Exception {
        TrialGraph trial = graph(
                row("kind", "ATTACH", "occurrenceId", "parent",
                        "occurrence", "parent-render", "node", "node0",
                        "regionId", "R.handler", "seq", 2),
                row("kind", "ACTIVATION", "occurrenceId", "child",
                        "occurrence", "child-render", "node", "node0",
                        "regionId", "R.target", "parentOccurrenceId", "parent",
                        "parentOccurrence", "parent-render", "seq", 3),
                row("kind", "EXPORT", "occurrenceId", "parent",
                        "occurrence", "parent-render", "node", "node0",
                        "regionId", "R.handler", "seq", 4),
                row("kind", "TARGET_CHECK", "occurrenceId", "child",
                        "siteId", "target", "seq", 5));
        JsonObject feedback = trial.feedback("target", null);
        assertEquals(2, feedback.get("closureNodes").getAsInt());
        assertEquals(1, feedback.get("closureEdges").getAsInt());
        assertFalse(feedback.getAsJsonObject("gaps").has("SCOPE_PARENT_UNPROVEN"));
    }
}
