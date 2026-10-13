package edu.uva.liftlab.mallory.graphchecker.runtime;

import org.junit.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Base64;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class MessageDoorsTest {
    @Test public void transportCompletionAndReceiptAreRequiredForWireEvidence()
            throws Exception {
        Path trace = Files.createTempFile("mallory-gc-door-", ".jsonl");
        System.setProperty("mallory.graphchecker.trace.file", trace.toString());
        Object sender = new Object();
        Object receiver = new Object();
        MessageDoors.registerSource(sender, "test", "client", "client0", 0);
        MessageDoors.registerSource(receiver, "test", "server", "server0", 0);
        long request = MessageDoors.beginRequest(sender, "put");
        assertEquals("client0#epoch0", MessageDoors.currentSourceKey());
        assertTrue(Files.readAllLines(trace, StandardCharsets.UTF_8).stream()
                .anyMatch(line -> line.contains("\"kind\":\"SCOPE_ENTER\"")
                        && line.contains("\"occurrenceId\":")));
        MessageDoors.coverage("poll-block", sender);
        MessageDoors.coverage("poll-block", sender);
        MessageDoors.branch("poll-branch", sender, true);
        MessageDoors.branch("poll-branch", sender, true);
        MessageDoors.branch("poll-branch", sender, false);
        for (int index = 0; index < 1000; index++) {
            assertTrue(MessageDoors.tryEnterRegion("R.hotGetter", "getter#entry",
                    index, sender));
            MessageDoors.exitRegion("R.hotGetter");
        }
        assertFalse(Files.readAllLines(trace, StandardCharsets.UTF_8).stream()
                .anyMatch(line -> line.contains("\"regionId\":\"R.hotGetter\"")));
        assertTrue(MessageDoors.tryEnterRegion("R.put", "put#entry", 0, sender));
        assertFalse(MessageDoors.tryEnterRegion("R.unregistered", "missing#entry",
                0, new Object()));
        MessageDoors.FaultDoorHit hit = MessageDoors.faultDoorHit("send-door", sender);
        assertTrue(hit != null);
        assertEquals(1L, hit.ordinal);
        MessageDoors.faultApplied(hit, "java.io.IOException");
        MessageDoors.Outbound outbound = MessageDoors.prepareOutbound(
                "RPC", "client0:call7", "0", MessageDoors.REQUEST, sender, null);
        assertTrue(outbound.active());
        assertFalse(Files.readAllLines(trace, StandardCharsets.UTF_8).stream()
                .anyMatch(line -> line.contains("\"kind\":\"EXPORT\"")));
        MessageDoors.sent(outbound);
        MessageDoors.exitRegion("R.put");
        MessageDoors.endRequest(request, "put");
        MessageDoors.Inbound inbound = MessageDoors.inbound(outbound.trace, "",
                "RPC", "client0:call7", "0", MessageDoors.REQUEST,
                receiver, false);
        MessageDoors.enterRegion("R.handle", "handle#entry", 0);
        MessageDoors.targetCheck("target", receiver, "healthy");
        MessageDoors.exitRegion("R.handle");
        MessageDoors.endInbound(inbound);
        long enclosing = MessageDoors.beginRequest(receiver, "inside-inbound");
        MessageDoors.enterRegion("R.enclosing", "enclosing#entry", 0);
        MessageDoors.Inbound nested = MessageDoors.inbound(outbound.trace, "",
                "RPC", "client0:call7", "0", MessageDoors.REQUEST,
                receiver, false);
        MessageDoors.targetCheck("inside-inbound", receiver, "healthy");
        MessageDoors.exitRegion("R.enclosing");
        MessageDoors.endInbound(nested);
        MessageDoors.endRequest(enclosing, "inside-inbound");
        List<String> lines = Files.readAllLines(trace, StandardCharsets.UTF_8);
        assertEquals(1, lines.stream().filter(line -> line.contains(
                "\"siteId\":\"poll-block\"")).count());
        assertEquals(1, lines.stream().filter(line -> line.contains(
                "\"siteId\":\"branch:poll-branch:true\"")).count());
        assertEquals(1, lines.stream().filter(line -> line.contains(
                "\"siteId\":\"branch:poll-branch:false\"")).count());
        assertEquals(1, lines.stream().filter(line -> line.contains("\"kind\":\"EXPORT\"")).count());
        assertEquals(2, lines.stream().filter(line -> line.contains("\"kind\":\"ATTACH\"")).count());
        assertEquals(1, lines.stream().filter(line -> line.contains("\"kind\":\"FAULT_APPLIED\"")
                && line.contains("\"siteId\":\"send-door\"")).count());
        assertFalse(lines.stream().anyMatch(line -> line.contains("SCOPE_UNBALANCED")));
        assertFalse(lines.stream().anyMatch(line -> line.contains("REGION_UNBALANCED")));
        assertTrue(lines.stream().anyMatch(line -> line.contains("\"siteId\":\"inside-inbound\"")
                && line.contains("\"regionId\":\"R.enclosing\"")));
        TrialGraph graph = TrialGraph.read(trace);
        assertEquals(4, graph.closure("target").size());
        long direct = MessageDoors.beginRequest(sender, "admin");
        MessageDoors.enterRegion("R.serverDirect", "server#direct", 0, receiver);
        MessageDoors.targetCheck("owner-switch", receiver, "healthy");
        MessageDoors.exitRegion("R.serverDirect");
        MessageDoors.endRequest(direct, "admin");
        assertTrue(Files.readAllLines(trace, StandardCharsets.UTF_8).stream()
                .anyMatch(line -> line.contains("\"siteId\":\"owner-switch\"")
                        && line.contains("\"node\":\"server0#epoch0\"")));
        Object alias = new Object();
        MessageDoors.registerSourceAlias(alias, sender);
        MessageDoors.restartSource(sender, "test", "client", "client0", 1);
        assertEquals(1L, TraceRows.source(alias).epoch());

        long queueWrite = MessageDoors.beginRequest(sender, "queue-write");
        MessageDoors.stored("ZOOKEEPER", "/queue/item-1", sender);
        MessageDoors.endRequest(queueWrite, "queue-write");
        long queueRead = MessageDoors.beginRequest(receiver, "queue-process");
        MessageDoors.notified("QUEUE_TAKE", () ->
                MessageDoors.fetched("ZOOKEEPER", "/queue/item-1", receiver));
        MessageDoors.consumed("ZOOKEEPER", "/queue/item-1");
        MessageDoors.enterRegion("R.queueTarget", "queue-target#entry", 0);
        MessageDoors.targetCheck("queue-target", receiver, "healthy");
        MessageDoors.exitRegion("R.queueTarget");
        MessageDoors.endRequest(queueRead, "queue-process");
        TrialGraph queueGraph = TrialGraph.read(trace);
        assertTrue(queueGraph.feedback("queue-target", null).getAsJsonArray(
                "closureEdgeFamilies").toString().contains("HANDOFF"));

        long bridgeScope = MessageDoors.beginRequest(sender, "bridge-scope");
        Object endedCall = MessageDoors.openCall("bridge-end", 0);
        MessageDoors.endRequest(bridgeScope, "bridge-scope");
        long nextScope = MessageDoors.beginRequest(sender, "next-scope");
        Object liveCall = MessageDoors.openCall("bridge-end", 0);
        long balanceGaps = Files.readAllLines(trace, StandardCharsets.UTF_8)
                .stream().filter(line -> line.contains("CALL_UNBALANCED")).count();
        MessageDoors.closeCall(endedCall, "bridge-end");
        MessageDoors.closeCall(liveCall, "bridge-end");
        MessageDoors.endRequest(nextScope, "next-scope");
        assertEquals(balanceGaps, Files.readAllLines(trace, StandardCharsets.UTF_8)
                .stream().filter(line -> line.contains("CALL_UNBALANCED")).count());

        long outerScope = MessageDoors.beginRequest(sender, "outer-scope");
        assertTrue(MessageDoors.tryEnterRegion("R.outer", "outer#entry", 0, sender));
        Object bridgeBegin = MessageDoors.openCall("begin-inner", 0);
        long innerScope = MessageDoors.beginRequest(sender, "inner-scope");
        MessageDoors.closeCall(bridgeBegin, "begin-inner");
        MessageDoors.endRequest(innerScope, "inner-scope");
        MessageDoors.exitRegion("R.outer");
        MessageDoors.endRequest(outerScope, "outer-scope");
        assertEquals(balanceGaps, Files.readAllLines(trace, StandardCharsets.UTF_8)
                .stream().filter(line -> line.contains("CALL_UNBALANCED")
                        || line.contains("REGION_UNBALANCED")).count());

        long nestedScope = MessageDoors.beginRequest(sender, "nested-cause");
        assertTrue(MessageDoors.tryEnterRegion("R.parent", "parent#entry", 0, sender));
        assertTrue(MessageDoors.tryEnterRegion("R.child", "child#entry", 0, sender));
        MessageDoors.targetCheck("nested-target", sender, "healthy");
        MessageDoors.exitRegion("R.child");
        MessageDoors.exitRegion("R.parent");
        MessageDoors.endRequest(nestedScope, "nested-cause");
        String nestedFamilies = TrialGraph.read(trace).feedback("nested-target", null)
                .getAsJsonArray("closureNodeFamilies").toString();
        assertTrue(nestedFamilies.contains("R.parent"));
        assertTrue(nestedFamilies.contains("R.child"));

        long copiedOuter = MessageDoors.beginRequest(sender, "copied-outer");
        Object copiedCall = MessageDoors.openCall("copied-call", 0);
        long copiedInner = MessageDoors.beginRequest(sender, "copied-inner");
        TraceRows.Context carried = TraceRows.snapshot();
        MessageDoors.closeCall(copiedCall, "copied-call");
        MessageDoors.endRequest(copiedInner, "copied-inner");
        MessageDoors.endRequest(copiedOuter, "copied-outer");
        TraceRows.Context priorContext = TraceRows.install(carried);
        try {
            MessageDoors.endRequest(copiedInner, "copied-inner");
            assertTrue(MessageDoors.tryEnterRegion("R.carried", "carried#entry",
                    0, sender));
            assertTrue(TraceRows.occurrence(sender).index().render()
                    .contains("copied-call"));
            MessageDoors.exitRegion("R.carried");
            MessageDoors.closeCall(copiedCall, "copied-call");
            MessageDoors.endRequest(copiedOuter, "copied-outer");
        } finally {
            TraceRows.restore(priorContext);
        }

        StringBuilder longSite = new StringBuilder("deep-call-");
        for (int index = 0; index < 96; index++) longSite.append('x');
        long deepScope = MessageDoors.beginRequest(sender, "deep-wire");
        Object[] deepCalls = new Object[180];
        for (int index = 0; index < deepCalls.length; index++) {
            deepCalls[index] = MessageDoors.openCall(longSite + String.valueOf(index), 0);
        }
        assertTrue(MessageDoors.tryEnterRegion("R.deepWire", "deep-wire#entry", 0,
                sender));
        MessageDoors.Outbound deepOutbound = MessageDoors.prepareOutbound(
                "RPC", "deep:call1", "0", MessageDoors.REQUEST, sender, null);
        assertTrue(deepOutbound.active());
        assertTrue(Base64.getUrlDecoder().decode(deepOutbound.trace).length < 16384);
        MessageDoors.sent(deepOutbound);
        MessageDoors.exitRegion("R.deepWire");
        for (int index = deepCalls.length - 1; index >= 0; index--) {
            MessageDoors.closeCall(deepCalls[index], longSite + String.valueOf(index));
        }
        MessageDoors.endRequest(deepScope, "deep-wire");
        MessageDoors.Inbound deepInbound = MessageDoors.inbound(deepOutbound.trace,
                "", "RPC", "deep:call1", "0", MessageDoors.REQUEST,
                receiver, false);
        assertTrue(MessageDoors.tryEnterRegion("R.deepReceiver",
                "deep-receiver#entry", 0, receiver));
        MessageDoors.targetCheck("deep-wire-target", receiver, "healthy");
        MessageDoors.exitRegion("R.deepReceiver");
        MessageDoors.endInbound(deepInbound);
        assertTrue(TrialGraph.read(trace).feedback("deep-wire-target", null)
                .getAsJsonArray("closureEdgeFamilies").toString().contains("WIRE"));

        long returnScope = MessageDoors.beginRequest(sender, "returned-io");
        assertTrue(MessageDoors.tryEnterRegion("R.caller", "caller#entry", 0, sender));
        assertTrue(MessageDoors.tryEnterRegion("R.callee", "callee#entry", 0, sender));
        assertTrue(MessageDoors.faultDoorHit("callee-io", sender) != null);
        MessageDoors.exitRegion("R.callee");
        MessageDoors.targetCheck("caller-after-return", sender, "healthy");
        MessageDoors.exitRegion("R.caller");
        MessageDoors.endRequest(returnScope, "returned-io");
        com.google.gson.JsonObject returnedFeedback = TrialGraph.read(trace)
                .feedback("caller-after-return", null);
        assertTrue(returnedFeedback.getAsJsonArray("closureEdgeFamilies")
                .toString().contains("COMPLETION"));
        assertTrue(returnedFeedback.getAsJsonArray("closureDoorSiteIds")
                .toString().contains("callee-io"));
    }
}
