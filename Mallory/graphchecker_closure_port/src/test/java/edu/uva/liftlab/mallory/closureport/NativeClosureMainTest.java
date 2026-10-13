package edu.uva.liftlab.mallory.closureport;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import edu.uva.liftlab.graphchecker.contract.CausalContext;
import edu.uva.liftlab.graphchecker.contract.Endpoint;
import edu.uva.liftlab.graphchecker.contract.ExecutionIndex;
import edu.uva.liftlab.graphchecker.contract.NodeId;
import edu.uva.liftlab.graphchecker.contract.OccurrenceAddress;
import edu.uva.liftlab.graphchecker.contract.Role;
import edu.uva.liftlab.graphchecker.explore.Corpus;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class NativeClosureMainTest {
    @Rule public TemporaryFolder folder = new TemporaryFolder();

    private static JsonObject event(String kind, OccurrenceAddress occurrence,
                                    long sequence) {
        JsonObject row = new JsonObject();
        row.addProperty("kind", kind);
        row.addProperty("occurrence", occurrence.render());
        row.addProperty("occurrenceId", occurrence.id());
        row.addProperty("node", occurrence.node().render());
        row.addProperty("regionId", occurrence.regionId());
        row.addProperty("threadKey", "junit-1");
        row.addProperty("seq", sequence);
        return row;
    }

    @Test public void compactRowsPreserveOriginalPlannerAndObservedFaultPredecessor()
            throws Exception {
        Path root = folder.newFolder().toPath();
        OccurrenceAddress first = OccurrenceAddress.of(NodeId.of("zk-peer-1", 1),
                "R.register", CausalContext.of(Role.of("SERVER"), "REGISTER", 1),
                ExecutionIndex.empty());
        OccurrenceAddress second = OccurrenceAddress.of(NodeId.of("zk-peer-1", 1),
                "R.register", CausalContext.of(Role.of("SERVER"), "REGISTER", 2),
                ExecutionIndex.empty());
        JsonObject activation = event("ACTIVATION", first, 1);
        JsonObject fault = event("FAULT_APPLIED", first, 2);
        fault.addProperty("siteId", "Register#io");
        JsonObject coverage = event("COVERAGE", first, 3);
        coverage.addProperty("siteId", "Register#block");
        JsonObject door = event("FAULT_DOOR", first, 4);
        door.addProperty("siteId", "Register#io");
        JsonObject completion = event("REGION_COMPLETE", first, 5);
        JsonObject target = event("TARGET_CHECK", second, 7);
        target.addProperty("siteId", "Register#check");
        target.addProperty("outcome", "FALSE");
        Path legacy = root.resolve("legacy.jsonl");
        Files.write(legacy, Arrays.asList(activation.toString(), fault.toString(),
                coverage.toString(), door.toString(), completion.toString(),
                event("ACTIVATION", second, 6).toString(), target.toString()),
                StandardCharsets.UTF_8);
        JsonObject compactCoverage = coverage.deepCopy();
        JsonObject compactDoor = door.deepCopy();
        JsonObject compactCompletion = completion.deepCopy();
        for (JsonObject compact : Arrays.asList(compactCoverage, compactDoor,
                compactCompletion)) {
            compact.remove("occurrence");
            compact.addProperty("occurrenceRef", "ACTIVATION");
        }
        Path compact = root.resolve("compact.jsonl");
        Files.write(compact, Arrays.asList(activation.toString(), fault.toString(),
                compactCoverage.toString(), compactDoor.toString(),
                compactCompletion.toString(), event("ACTIVATION", second, 6).toString(),
                target.toString()), StandardCharsets.UTF_8);
        Path scope = root.resolve("scope.jsonl");
        JsonObject site = new JsonObject();
        site.addProperty("kind", "STATIC_SCOPE_SITE");
        site.addProperty("role", "TARGET_SITE");
        site.addProperty("regionId", "R.register");
        site.addProperty("siteId", "Register#check");
        Files.write(scope, Arrays.asList(site.toString()), StandardCharsets.UTF_8);
        JsonObject oldResult = NativeClosureMain.run(legacy, scope,
                "Register#check", root.resolve("old-iteration"), null);
        JsonObject newResult = NativeClosureMain.run(compact, scope,
                "Register#check", root.resolve("compact-iteration"), null);
        oldResult.remove("traceSha256");
        oldResult.remove("adaptedSession");
        newResult.remove("traceSha256");
        newResult.remove("adaptedSession");
        assertEquals(oldResult, newResult);
        assertEquals(1, newResult.getAsJsonArray("programOrderFaultEdges").size());
        assertEquals(first.id(), newResult.getAsJsonArray(
                "programOrderFaultEdges").get(0).getAsJsonObject()
                .get("fromOccurrenceId").getAsString());
    }

    @Test public void compactNativeRowsWithoutExactActivationFailClosed() {
        OccurrenceAddress occurrence = OccurrenceAddress.of(NodeId.of("n", 0),
                "R.target", CausalContext.of(Role.of("SERVER"), "X", 1),
                ExecutionIndex.empty());
        JsonObject compact = event("REGION_COMPLETE", occurrence, 2);
        compact.remove("occurrence");
        compact.addProperty("occurrenceRef", "ACTIVATION");
        try {
            new NativeClosureMain.Adapted().take(compact, "R.target#check");
            org.junit.Assert.fail("missing activation must not invent a path");
        } catch (IllegalArgumentException expected) { }
    }

    @Test public void copiedPlannerRunsAndExcludesUndemandedMalloryAncestor()
            throws Exception {
        Path root = folder.newFolder().toPath();
        Path trace = root.resolve("trace.jsonl");
        Path scope = root.resolve("scope.jsonl");
        Path feedback = root.resolve("feedback.json");
        OccurrenceAddress target = OccurrenceAddress.of(NodeId.of("zk-peer-1", 1),
                "R.target", CausalContext.of(Role.of("SERVER"), "REGISTER", 1),
                ExecutionIndex.empty());
        OccurrenceAddress unrelated = OccurrenceAddress.of(NodeId.of("zk-peer-1", 1),
                "R.parent", CausalContext.of(Role.of("SERVER"), "REGISTER", 1),
                ExecutionIndex.empty());
        JsonObject check = event("TARGET_CHECK", target, 3);
        check.addProperty("siteId", "Learner#u51");
        check.addProperty("outcome", "FALSE");
        Files.write(trace, Arrays.asList(event("ACTIVATION", unrelated, 1).toString(),
                event("ACTIVATION", target, 2).toString(), check.toString()),
                StandardCharsets.UTF_8);
        JsonObject targetSite = new JsonObject();
        targetSite.addProperty("kind", "STATIC_SCOPE_SITE");
        targetSite.addProperty("role", "TARGET_SITE");
        targetSite.addProperty("regionId", "R.target");
        targetSite.addProperty("siteId", "Learner#u51");
        JsonArray guards = new JsonArray();
        guards.add("Learner#u40");
        targetSite.add("guards", guards);
        Files.write(scope, Arrays.asList(targetSite.toString()), StandardCharsets.UTF_8);
        JsonObject old = new JsonObject();
        JsonArray oldClosure = new JsonArray();
        oldClosure.add(target.id());
        oldClosure.add(unrelated.id());
        old.add("closureOccurrenceIds", oldClosure);
        Files.write(feedback, Arrays.asList(old.toString()), StandardCharsets.UTF_8);

        JsonObject result = NativeClosureMain.run(trace, scope, "Learner#u51",
                root.resolve("iteration"), feedback);
        assertEquals(1, result.getAsJsonArray("nativeClosureOccurrenceIds").size());
        assertEquals(target.id(), result.getAsJsonArray("nativeClosureOccurrenceIds")
                .get(0).getAsString());
        assertEquals(unrelated.id(), result.getAsJsonArray("onlyMalloryOccurrenceIds")
                .get(0).getAsString());
        JsonObject planned = result.getAsJsonArray("nativeTargets").get(0)
                .getAsJsonObject();
        assertEquals(1, planned.get("concreteDecidedPaths").getAsInt());
        assertTrue(planned.get("flipSites").toString().contains("Learner#u40"));
        assertFalse(result.get("nativeClosureCodeSource").getAsString().contains(
                "GraphChecker-1.0-SNAPSHOT.jar"));
    }

    @Test(expected = IllegalArgumentException.class)
    public void refusesOccurrenceWhoseRecordedIdDisagrees() {
        OccurrenceAddress occurrence = OccurrenceAddress.of(NodeId.of("n", 0),
                "R.target", CausalContext.of(Role.of("SERVER"), "X", 1),
                ExecutionIndex.empty());
        JsonObject row = event("TARGET_CHECK", occurrence, 1);
        row.addProperty("occurrenceId", "wrong");
        NativeClosureMain.exactOccurrence(row);
    }

    @Test public void exactResourceIdentityBecomesAnOrderedNativeVersion()
            throws Exception {
        Path root = folder.newFolder().toPath();
        OccurrenceAddress writer = OccurrenceAddress.of(NodeId.of("zk-peer-1", 0),
                "R.writer", CausalContext.of(Role.of("SERVER"), "START", 1),
                ExecutionIndex.empty());
        OccurrenceAddress reader = OccurrenceAddress.of(NodeId.of("zk-peer-1", 1),
                "R.reader", CausalContext.of(Role.of("SERVER"), "RESTART", 1),
                ExecutionIndex.empty());
        Endpoint out = Endpoint.of(writer, "PERSISTED_FILE_V1.WRITE",
                ExecutionIndex.empty(), 0);
        Endpoint in = Endpoint.of(reader, "PERSISTED_FILE_V1.READ",
                ExecutionIndex.empty(), 0);
        String version = "PERSISTED_FILE_V1\n/tmp/epoch|1|mtime|inode|checksum";
        JsonObject write = event("WRITE", writer, 2);
        write.addProperty("writer", out.render());
        write.addProperty("writerEndpointId", out.id());
        write.addProperty("locationVersion", version);
        JsonObject read = event("READ", reader, 4);
        read.addProperty("reader", in.render());
        read.addProperty("readerEndpointId", in.id());
        read.addProperty("writerEndpointId", out.id());
        read.addProperty("locationVersion", version);
        JsonObject unpaired = event("READ", reader, 5);
        unpaired.addProperty("reader", in.render());
        unpaired.addProperty("readerEndpointId", in.id());
        unpaired.addProperty("writerEndpointId", "not-an-observed-writer");
        unpaired.addProperty("locationVersion", version);
        JsonObject check = event("TARGET_CHECK", reader, 6);
        check.addProperty("siteId", "Reader#u6");
        check.addProperty("outcome", "FALSE");
        Path trace = root.resolve("trace.jsonl");
        Files.write(trace, Arrays.asList(event("ACTIVATION", writer, 1).toString(),
                write.toString(), event("ACTIVATION", reader, 3).toString(),
                read.toString(), unpaired.toString(), check.toString()),
                StandardCharsets.UTF_8);
        NativeClosureMain.Adapted adapted = NativeClosureMain.adapt(trace,
                "Reader#u6");
        assertEquals(Integer.valueOf(1), adapted.mappedCounts.get("WRITE"));
        assertEquals(Integer.valueOf(1), adapted.mappedCounts.get("READ"));
        assertEquals(Integer.valueOf(1), adapted.refusedStateRows.get(
                "READ_WRITER_NOT_UNIQUE_OR_LATE"));
        Path iteration = root.resolve("iteration");
        adapted.write(iteration);
        Corpus corpus = Corpus.read(iteration, null);
        assertEquals(1, corpus.writesOn(writer).size());
        assertEquals(1, corpus.readsOn(reader).size());
        assertEquals(corpus.writesOn(writer).get(0).version(),
                corpus.readsOn(reader).get(0).observedVersion());
        assertEquals(1L, corpus.readsOn(reader).get(0).observedVersion());
    }

    @Test public void faultPredecessorRequiresSameThreadAndCompletedRegion() {
        OccurrenceAddress first = OccurrenceAddress.of(NodeId.of("zk-peer-1", 1),
                "R.register", CausalContext.of(Role.of("SERVER"), "REGISTER", 1),
                ExecutionIndex.empty());
        OccurrenceAddress second = OccurrenceAddress.of(NodeId.of("zk-peer-1", 1),
                "R.register", CausalContext.of(Role.of("SERVER"), "REGISTER", 2),
                ExecutionIndex.empty());
        NativeClosureMain.Adapted adapted = new NativeClosureMain.Adapted();
        adapted.take(event("ACTIVATION", first, 1), "Register#check");
        JsonObject fault = event("FAULT_APPLIED", first, 2);
        fault.addProperty("siteId", "Register#io");
        adapted.take(fault, "Register#check");
        adapted.take(event("REGION_COMPLETE", first, 3), "Register#check");
        adapted.take(event("ACTIVATION", second, 4), "Register#check");
        JsonObject check = event("TARGET_CHECK", second, 5);
        check.addProperty("siteId", "Register#check");
        check.addProperty("outcome", "FALSE");
        adapted.take(check, "Register#check");
        assertEquals(1, adapted.observedFaultPredecessors().size());
        assertEquals(first.id(), adapted.observedFaultPredecessors().get(0)
                .getAsJsonObject().get("fromOccurrenceId").getAsString());
        check.addProperty("threadKey", "different-thread");
        NativeClosureMain.Adapted differentThread = new NativeClosureMain.Adapted();
        differentThread.take(event("ACTIVATION", first, 1), "Register#check");
        differentThread.take(fault, "Register#check");
        differentThread.take(event("REGION_COMPLETE", first, 3), "Register#check");
        JsonObject entered = event("ACTIVATION", second, 4);
        entered.addProperty("threadKey", "different-thread");
        differentThread.take(entered, "Register#check");
        differentThread.take(check, "Register#check");
        assertEquals(0, differentThread.observedFaultPredecessors().size());
    }

    @Test public void wirePairRequiresExactTransportTupleAndConsumerEndpoint() {
        OccurrenceAddress sender = OccurrenceAddress.of(NodeId.of("zk-peer-3", 0),
                "ROLE.SERVER", CausalContext.of(Role.of("SERVER"), "SEND", 1),
                ExecutionIndex.empty());
        OccurrenceAddress receiver = OccurrenceAddress.of(NodeId.of("zk-peer-1", 1),
                "R.receive", CausalContext.of(Role.of("SERVER"), "RECEIVE", 1),
                ExecutionIndex.empty());
        Endpoint outbound = Endpoint.of(sender, "ZK.REQUEST",
                ExecutionIndex.empty(), 0);
        Endpoint inbound = Endpoint.of(receiver, "ZK.REQUEST",
                ExecutionIndex.empty(), 0);
        NativeClosureMain.Adapted adapted = new NativeClosureMain.Adapted();
        JsonObject send = event("EXPORT", sender, 10);
        send.addProperty("producerEndpointId", outbound.id());
        send.addProperty("transport", "ZK");
        send.addProperty("correlationId", "packet-1");
        send.addProperty("attemptId", "1");
        send.addProperty("half", "REQUEST");
        adapted.take(send, "unused");
        JsonObject receive = event("ATTACH", receiver, 11);
        receive.addProperty("producerEndpointId", outbound.id());
        receive.addProperty("producerOccurrenceId", sender.id());
        receive.addProperty("consumer", inbound.render());
        receive.addProperty("consumerEndpointId", inbound.id());
        receive.addProperty("transport", "ZK");
        receive.addProperty("correlationId", "packet-1");
        receive.addProperty("attemptId", "1");
        receive.addProperty("half", "REQUEST");
        adapted.take(receive, "unused");
        assertEquals(1, adapted.observedWirePairs().size());
        receive.addProperty("correlationId", "packet-2");
        assertEquals(0, adapted.observedWirePairs().size());
    }
}
