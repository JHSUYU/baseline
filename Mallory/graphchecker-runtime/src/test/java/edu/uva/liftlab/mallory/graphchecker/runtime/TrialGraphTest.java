package edu.uva.liftlab.mallory.graphchecker.runtime;

import com.google.gson.JsonObject;
import edu.uva.liftlab.mallory.graphchecker.contract.CausalContext;
import edu.uva.liftlab.mallory.graphchecker.contract.ExecutionIndex;
import edu.uva.liftlab.mallory.graphchecker.contract.NodeId;
import edu.uva.liftlab.mallory.graphchecker.contract.OccurrenceAddress;
import edu.uva.liftlab.mallory.graphchecker.contract.Role;
import org.junit.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.zip.GZIPInputStream;
import java.util.zip.GZIPOutputStream;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class TrialGraphTest {
    @Test public void compactEventPathsPreserveCompletionClosureAndFeedback()
            throws Exception {
        OccurrenceAddress parentAddress = OccurrenceAddress.of(NodeId.of("server0", 0),
                "R.parent", CausalContext.of(Role.of("SERVER"), "get", 1),
                ExecutionIndex.empty());
        OccurrenceAddress childAddress = OccurrenceAddress.of(NodeId.of("server0", 0),
                "R.child", CausalContext.of(Role.of("SERVER"), "get", 1),
                ExecutionIndex.empty());
        JsonObject parent = row("kind", "ACTIVATION", "occurrenceId", parentAddress.id(),
                "occurrence", parentAddress.render(), "node", parentAddress.node().render(),
                "regionId", "R.parent",
                "seq", 1);
        JsonObject child = row("kind", "ACTIVATION", "occurrenceId", childAddress.id(),
                "occurrence", childAddress.render(), "node", childAddress.node().render(),
                "regionId", "R.child",
                "parentOccurrenceId", parentAddress.id(),
                "parentOccurrence", parentAddress.render(),
                "seq", 2);
        JsonObject coverage = row("kind", "COVERAGE", "occurrenceId", childAddress.id(),
                "occurrence", childAddress.render(), "node", childAddress.node().render(),
                "regionId", "R.child",
                "siteId", "block-A", "seq", 3);
        JsonObject door = row("kind", "FAULT_DOOR", "occurrenceId", childAddress.id(),
                "occurrence", childAddress.render(), "node", childAddress.node().render(),
                "regionId", "R.child",
                "siteId", "rpc-A", "seq", 4);
        JsonObject complete = row("kind", "REGION_COMPLETE", "occurrenceId",
                childAddress.id(), "occurrence", childAddress.render(), "node",
                childAddress.node().render(), "regionId", "R.child",
                "parentOccurrenceId", parentAddress.id(),
                "parentOccurrence", parentAddress.render(),
                "seq", 5);
        JsonObject target = row("kind", "TARGET_CHECK", "occurrenceId",
                parentAddress.id(), "occurrence", parentAddress.render(), "node",
                parentAddress.node().render(), "regionId", "R.parent",
                "siteId", "T", "outcome", "FALSE", "seq", 6);
        TrialGraph legacy = graph(parent, child, coverage, door, complete, target);
        JsonObject compactCoverage = coverage.deepCopy();
        JsonObject compactDoor = door.deepCopy();
        JsonObject compactComplete = complete.deepCopy();
        for (JsonObject compact : Arrays.asList(compactCoverage, compactDoor,
                compactComplete)) {
            compact.remove("occurrence");
            compact.addProperty("occurrenceRef", "ACTIVATION");
        }
        TrialGraph compressed = graph(parent, child, compactCoverage, compactDoor,
                compactComplete, target);
        assertEquals(legacy.feedback("T", null), compressed.feedback("T", null));
        assertEquals(2, compressed.feedback("T", null).get("closureNodes").getAsInt());
        assertEquals("[\"block-A\"]", compressed.feedback("T", null)
                .getAsJsonArray("closureCoverageSiteIds").toString());
        assertEquals("[\"rpc-A\"]", compressed.feedback("T", null)
                .getAsJsonArray("closureDoorSiteIds").toString());
        Path oldGraph = Files.createTempFile("mallory-legacy-", ".jsonl");
        Path compactGraph = Files.createTempFile("mallory-compact-", ".jsonl");
        legacy.write(oldGraph);
        compressed.write(compactGraph);
        assertEquals(Files.readAllLines(oldGraph), Files.readAllLines(compactGraph));
        Path gzipGraph = Files.createTempFile("mallory-compact-", ".jsonl.gz");
        compressed.write(gzipGraph);
        try (GZIPInputStream input = new GZIPInputStream(
                Files.newInputStream(gzipGraph))) {
            java.io.ByteArrayOutputStream restored = new java.io.ByteArrayOutputStream();
            byte[] buffer = new byte[8192];
            int read;
            while ((read = input.read(buffer)) >= 0) restored.write(buffer, 0, read);
            assertEquals(new String(Files.readAllBytes(compactGraph), StandardCharsets.UTF_8),
                    new String(restored.toByteArray(), StandardCharsets.UTF_8));
        }
    }

    @Test public void compactPathWithoutPriorExactActivationFailsClosed()
            throws Exception {
        OccurrenceAddress child = OccurrenceAddress.of(NodeId.of("server0", 0),
                "R.child", CausalContext.of(Role.of("SERVER"), "get", 1),
                ExecutionIndex.empty());
        JsonObject compact = row("kind", "REGION_COMPLETE", "occurrenceId", child.id(),
                "occurrenceRef", "ACTIVATION", "node", child.node().render(),
                "regionId", "R.child", "seq", 2);
        try {
            graph(compact);
            org.junit.Assert.fail("missing activation must not invent a path");
        } catch (IllegalArgumentException expected) { }
        JsonObject activation = row("kind", "ACTIVATION", "occurrenceId", child.id(),
                "occurrence", child.render(), "node", child.node().render(),
                "regionId", "R.child", "seq", 1);
        compact.addProperty("node", "different-server");
        try {
            graph(activation, compact);
            org.junit.Assert.fail("mismatched node must not borrow a path");
        } catch (IllegalArgumentException expected) { }
    }

    @Test public void duplicateActivationCannotRemapCompactOccurrence()
            throws Exception {
        OccurrenceAddress original = OccurrenceAddress.of(NodeId.of("server0", 0),
                "R.child", CausalContext.of(Role.of("SERVER"), "get", 1),
                ExecutionIndex.empty());
        OccurrenceAddress other = OccurrenceAddress.of(NodeId.of("server0", 0),
                "R.other", CausalContext.of(Role.of("SERVER"), "get", 1),
                ExecutionIndex.empty());
        JsonObject first = row("kind", "ACTIVATION", "occurrenceId", original.id(),
                "occurrence", original.render(), "node", original.node().render(),
                "regionId", original.regionId(), "seq", 1);
        JsonObject compact = row("kind", "COVERAGE", "occurrenceId", original.id(),
                "occurrenceRef", "ACTIVATION", "node", original.node().render(),
                "regionId", original.regionId(), "siteId", "block", "seq", 3);
        for (String field : Arrays.asList("occurrence", "node", "regionId")) {
            JsonObject second = first.deepCopy();
            second.addProperty("seq", 2);
            second.addProperty(field, "occurrence".equals(field) ? other.render()
                    : "node".equals(field) ? "different#epoch0" : "R.other");
            try {
                graph(first, second, compact);
                org.junit.Assert.fail("conflicting " + field + " must fail closed");
            } catch (IllegalArgumentException expected) { }
        }
        JsonObject identical = first.deepCopy();
        identical.addProperty("seq", 2);
        assertEquals(1, graph(first, identical, compact).feedback("missing", null)
                .get("nodes").getAsInt());
    }

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
        assertEquals("[\"block1\"]", TrialGraph.read(compressed).feedback("T", null)
                .getAsJsonArray("globalCoverageSiteIds").toString());
        assertEquals(1, TrialGraph.read(compressed).feedback("T", null)
                .getAsJsonObject("gaps").get("TRACE_ROW_INVALID").getAsInt());
    }

    @Test public void targetAbsentGlobalCoverageIsSortedDistinctAndCompact()
            throws Exception {
        JsonObject small = repeatedTargetAbsentCoverage(20).feedback("missing", null);
        JsonObject large = repeatedTargetAbsentCoverage(2000).feedback("missing", null);
        assertFalse(large.get("targetReached").getAsBoolean());
        assertEquals("[]", large.getAsJsonArray("closureCoverageSiteIds").toString());
        assertEquals("[\"a\",\"m\",\"z\"]",
                large.getAsJsonArray("globalCoverageSiteIds").toString());
        assertEquals(small, large);
        assertTrue(large.toString().length() < 1200);
    }

    private static TrialGraph repeatedTargetAbsentCoverage(int repeats) throws Exception {
        JsonObject[] rows = new JsonObject[repeats + 2];
        rows[0] = row("kind", "ACTIVATION", "occurrenceId", "o1",
                "node", "server", "regionId", "R", "seq", 1);
        for (int index = 0; index < repeats; index++) {
            rows[index + 1] = row("kind", "COVERAGE", "occurrenceId", "o1",
                    "siteId", index % 2 == 0 ? "z" : "a", "seq", index + 2);
        }
        rows[repeats + 1] = row("kind", "COVERAGE", "siteId", "m",
                "seq", repeats + 2);
        return graph(rows);
    }

    @Test public void healthySummaryMatchesFullPriorForMultiTargetNovelty()
            throws Exception {
        TrialGraph prior = graph(
                row("kind", "ACTIVATION", "occurrenceId", "old", "node", "server",
                        "regionId", "R.old", "seq", 1),
                row("kind", "COVERAGE", "occurrenceId", "old", "siteId", "old-before",
                        "seq", 2),
                row("kind", "TARGET_CHECK", "occurrenceId", "old", "siteId", "guard-a",
                        "outcome", "FALSE", "seq", 3),
                row("kind", "COVERAGE", "occurrenceId", "old", "siteId", "old-later",
                        "seq", 4));
        TrialGraph trial = graph(
                row("kind", "ACTIVATION", "occurrenceId", "old", "node", "server",
                        "regionId", "R.old", "seq", 1),
                row("kind", "COVERAGE", "occurrenceId", "old", "siteId", "old-before",
                        "seq", 2),
                row("kind", "TARGET_CHECK", "occurrenceId", "old", "siteId", "guard-a",
                        "outcome", "FALSE", "seq", 3),
                row("kind", "COVERAGE", "occurrenceId", "old", "siteId", "old-later",
                        "seq", 4),
                row("kind", "WRITE", "occurrenceId", "old", "writerEndpointId", "writer",
                        "locationVersion", "cell@1", "seq", 5),
                row("kind", "ACTIVATION", "occurrenceId", "fresh", "node", "server",
                        "regionId", "R.fresh", "seq", 6),
                row("kind", "READ", "occurrenceId", "fresh", "readerEndpointId", "reader",
                        "writerEndpointId", "writer", "writerOccurrenceId", "old",
                        "locationVersion", "cell@1", "seq", 7),
                row("kind", "COVERAGE", "occurrenceId", "fresh", "siteId", "new-branch",
                        "seq", 8),
                row("kind", "TARGET_CHECK", "occurrenceId", "fresh", "siteId", "guard-b",
                        "outcome", "TRUE", "seq", 9));
        java.util.List<String> sites = Arrays.asList("guard-a", "guard-b");
        JsonObject full = trial.feedback(sites, prior, null);
        Path summary = Files.createTempFile("mallory-gc-healthy-", ".summary.json");
        Files.write(summary, prior.healthySummary(sites).toString()
                .getBytes(StandardCharsets.UTF_8));
        JsonObject cached = trial.feedback(sites,
                TrialGraph.readHealthySummary(summary, sites), null);
        assertEquals(full, cached);
        assertEquals(full.get("newClosureNodes"), cached.get("newClosureNodes"));
        assertEquals(full.get("newClosureEdges"), cached.get("newClosureEdges"));
        assertEquals(full.get("newClosureCoverageSites"),
                cached.get("newClosureCoverageSites"));
        try {
            TrialGraph.readHealthySummary(summary, Arrays.asList("guard-b", "guard-a"));
            org.junit.Assert.fail("reordered target set must fail closed");
        } catch (IllegalArgumentException expected) { }
    }

    @Test public void healthySummaryPreservesNewTargetReachAfterAbsentSeed()
            throws Exception {
        TrialGraph prior = graph(row("kind", "ACTIVATION", "occurrenceId", "seed",
                "node", "server", "regionId", "R.seed", "seq", 1));
        TrialGraph trial = graph(
                row("kind", "ACTIVATION", "occurrenceId", "reached",
                        "node", "server", "regionId", "R.target", "seq", 1),
                row("kind", "COVERAGE", "occurrenceId", "reached",
                        "siteId", "new-block", "seq", 2),
                row("kind", "TARGET_CHECK", "occurrenceId", "reached",
                        "siteId", "target", "outcome", "FALSE", "seq", 3));
        java.util.List<String> sites = Arrays.asList("target");
        Path summary = Files.createTempFile("mallory-gc-absent-", ".summary.json");
        Files.write(summary, prior.healthySummary(sites).toString()
                .getBytes(StandardCharsets.UTF_8));
        assertEquals(trial.feedback(sites, prior, null),
                trial.feedback(sites, TrialGraph.readHealthySummary(summary, sites), null));
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

    @Test public void rejectsStateEdgeWhenExactVersionCarriesDifferentBytes()
            throws Exception {
        JsonObject write = row("kind", "WRITE", "occurrenceId", "writer",
                "writerEndpointId", "w1", "locationVersion", "ZOOKEEPER\n/path@17",
                "payloadSha256", "aaaaaaaa", "seq", 1);
        JsonObject read = row("kind", "READ", "occurrenceId", "reader",
                "readerEndpointId", "r1", "writerEndpointId", "w1",
                "writerOccurrenceId", "writer",
                "locationVersion", "ZOOKEEPER\n/path@17",
                "payloadSha256", "bbbbbbbb", "seq", 2);
        JsonObject target = row("kind", "TARGET_CHECK", "occurrenceId", "reader",
                "siteId", "T", "seq", 3);
        TrialGraph mismatch = graph(write, read, target);
        assertEquals(1, mismatch.closure("T").size());
        assertEquals(1, mismatch.feedback("T", null).getAsJsonObject("gaps")
                .get("STATE_PAYLOAD_MISMATCH").getAsInt());

        read.addProperty("payloadSha256", "aaaaaaaa");
        TrialGraph match = graph(write, read, target);
        assertEquals(2, match.closure("T").size());
        assertEquals(0, match.feedback("T", null).getAsJsonObject("gaps")
                .entrySet().size());
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

    @Test public void unionsBothObservedGuardsWithoutAbsorbingAnUnrelatedThrow()
            throws Exception {
        JsonObject first = row("kind", "TARGET_CHECK", "occurrenceId", "request-a",
                "node", "server", "regionId", "region-a",
                "siteId", "guard-a", "outcome", "TRUE", "seq", 4);
        JsonObject second = row("kind", "TARGET_CHECK", "occurrenceId", "request-b",
                "node", "server", "regionId", "region-b",
                "siteId", "guard-b", "outcome", "FALSE", "seq", 8);
        JsonObject unrelatedThrow = row("kind", "TARGET_THROW", "occurrenceId", "request-c",
                "node", "server", "siteId", "fatal-throw",
                "exceptionClass", "java.io.IOException", "seq", 10);
        TrialGraph prior = graph(first);
        TrialGraph trial = graph(first, second, unrelatedThrow);
        JsonObject feedback = trial.feedback(Arrays.asList("guard-a", "guard-b"), prior, null);
        assertEquals(2, feedback.get("closureNodes").getAsInt());
        assertEquals(1, feedback.get("newClosureNodes").getAsInt());
        assertTrue(feedback.get("allTargetSitesReached").getAsBoolean());
        assertEquals(0, feedback.getAsJsonArray("missingTargetSites").size());
        assertEquals("TRUE", feedback.getAsJsonObject("targetCheckOutcomesBySite")
                .getAsJsonArray("guard-a").get(0).getAsString());
        assertEquals("FALSE", feedback.getAsJsonObject("targetCheckOutcomesBySite")
                .getAsJsonArray("guard-b").get(0).getAsString());
        assertEquals(4, feedback.getAsJsonObject("perTargetClosures")
                .getAsJsonObject("guard-a").getAsJsonObject("closureOccurrenceCutoffs")
                .get("request-a").getAsInt());
        assertEquals(8, feedback.getAsJsonObject("perTargetClosures")
                .getAsJsonObject("guard-b").getAsJsonObject("closureOccurrenceCutoffs")
                .get("request-b").getAsInt());
        assertFalse(feedback.getAsJsonObject("closureOccurrenceCutoffs")
                .has("request-c"));
        assertEquals("request-c", feedback.getAsJsonArray("targetThrowClosures")
                .get(0).getAsJsonObject().get("occurrenceId").getAsString());
    }

    @Test public void absentConfiguredGuardRemainsMissing() throws Exception {
        TrialGraph trial = graph(row("kind", "TARGET_CHECK", "occurrenceId", "request-a",
                "node", "server", "siteId", "guard-a", "outcome", "TRUE", "seq", 4));
        JsonObject feedback = trial.feedback(Arrays.asList("guard-a", "guard-b"), null, null);
        assertTrue(feedback.get("targetReached").getAsBoolean());
        assertFalse(feedback.get("allTargetSitesReached").getAsBoolean());
        assertEquals("guard-b", feedback.getAsJsonArray("missingTargetSites")
                .get(0).getAsString());
        assertEquals(0, feedback.getAsJsonObject("perTargetClosures")
                .getAsJsonObject("guard-b").getAsJsonObject("closureOccurrenceCutoffs").size());
    }

    @Test public void sharedOccurrenceKeepsSeparateGuardCutoffs() throws Exception {
        TrialGraph trial = graph(
                row("kind", "TARGET_CHECK", "occurrenceId", "request",
                        "siteId", "guard-a", "outcome", "FALSE", "seq", 4),
                row("kind", "FAULT_DOOR", "occurrenceId", "request",
                        "siteId", "between-guards", "seq", 6),
                row("kind", "TARGET_CHECK", "occurrenceId", "request",
                        "siteId", "guard-b", "outcome", "TRUE", "seq", 8));
        JsonObject feedback = trial.feedback(Arrays.asList("guard-a", "guard-b"), null, null);
        assertEquals(8, feedback.getAsJsonObject("closureOccurrenceCutoffs")
                .get("request").getAsInt());
        assertEquals(4, feedback.getAsJsonObject("perTargetClosures")
                .getAsJsonObject("guard-a").getAsJsonObject("closureOccurrenceCutoffs")
                .get("request").getAsInt());
        assertEquals(8, feedback.getAsJsonObject("perTargetClosures")
                .getAsJsonObject("guard-b").getAsJsonObject("closureOccurrenceCutoffs")
                .get("request").getAsInt());
        assertEquals("between-guards", feedback.getAsJsonArray("closureDoorSiteIds")
                .get(0).getAsString());
    }

    @Test public void commandTargetArrayParserRejectsAmbiguousValues() {
        assertEquals(Arrays.asList("guard-a", "guard-b"),
                TrialGraphMain.targetSites("[\"guard-a\",\"guard-b\"]"));
        assertEquals(Arrays.asList("guard-a"), TrialGraphMain.targetSites("guard-a"));
        try {
            TrialGraphMain.targetSites("[\"guard-a\",1]");
            org.junit.Assert.fail("numeric site ID must be rejected");
        } catch (IllegalArgumentException expected) { }
    }

    @Test public void completedSameThreadRootScopesHaveProgramOrder() throws Exception {
        JsonObject first = row("kind", "SCOPE_ENTER", "occurrenceId", "root-a",
                "regionId", "ROLE.SERVER", "node", "peer#epoch1", "threadKey", "88",
                "sourceKey", "peer-source", "api", "REGISTER", "token", 1,
                "newRoot", "true", "seq", 1);
        JsonObject exit = row("kind", "SCOPE_EXIT", "occurrenceId", "root-a",
                "node", "peer#epoch1", "threadKey", "88", "token", 1,
                "newRoot", "true", "seq", 4);
        JsonObject second = row("kind", "SCOPE_ENTER", "occurrenceId", "root-b",
                "regionId", "ROLE.SERVER", "node", "peer#epoch1", "threadKey", "88",
                "sourceKey", "peer-source", "api", "REGISTER", "token", 2,
                "newRoot", "true", "seq", 5);
        JsonObject target = row("kind", "TARGET_CHECK", "occurrenceId", "root-b",
                "siteId", "check", "node", "peer#epoch1", "seq", 6);
        TrialGraph ordered = graph(first, exit, second, target);
        assertTrue(ordered.closure("check").contains("root-a"));
        assertEquals(1, ordered.feedback("check", null).get("closureEdges").getAsInt());

        TrialGraph noExit = graph(first, second, target);
        assertFalse(noExit.closure("check").contains("root-a"));
        JsonObject otherThread = row("kind", "SCOPE_ENTER", "occurrenceId", "root-b",
                "regionId", "ROLE.SERVER", "node", "peer#epoch1", "threadKey", "89",
                "sourceKey", "peer-source", "api", "REGISTER", "token", 2,
                "newRoot", "true", "seq", 5);
        assertFalse(graph(first, exit, otherThread, target).closure("check")
                .contains("root-a"));
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
