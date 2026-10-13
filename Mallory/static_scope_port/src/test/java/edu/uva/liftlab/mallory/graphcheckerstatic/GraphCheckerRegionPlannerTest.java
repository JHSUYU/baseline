package edu.uva.liftlab.mallory.graphcheckerstatic;

import org.junit.Test;

import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/** Regression fixtures adapted from GraphChecker SymbolicRegionPlannerTest. */
public class GraphCheckerRegionPlannerTest {
    private static final String RUN = "<p.Responder: void run()>";
    private static final String SEND = "<p.Door: void send()>";
    private static final String RECEIVE = "<p.Dispatcher: void receive()>";
    private static final String WRITE = "<p.Store: void write()>";

    @Test
    public void demandedDoorFoldsIntoExistingExceptionRegion() {
        GraphCheckerRegionPlanner.Input input = new GraphCheckerRegionPlanner.Input();
        input.selectedMethods.addAll(Arrays.asList(RUN, SEND, RECEIVE, WRITE));
        input.executionContextAuthorities.put(RUN, "TASK_ENTRY");
        input.targetMethod = RECEIVE;
        input.edges.add(edge("method", RUN, "toCell", RUN + "#exception:java.io.IOException"));
        input.edges.add(edge("method", SEND, "explicitSymbolicFault", true));
        input.edges.add(edge("method", RECEIVE, "toCell", RECEIVE + "#exception:java.io.IOException"));
        input.demandedDoorChains.add(Arrays.asList(RUN, WRITE));

        GraphCheckerRegionPlanner.Result result = GraphCheckerRegionPlanner.plan(input);
        assertEquals(3, result.regions.size());
        Map<String, Object> run = region(result, RUN);
        assertEquals("TASK_ENTRY", run.get("rootAuthority"));
        assertEquals("EXCEPTION_CONTEXT", run.get("selection"));
        assertEquals(Arrays.asList(RUN, WRITE), run.get("methods"));
        assertEquals("EXPLICIT_FAULT_CONTEXT", region(result, SEND).get("selection"));
        assertEquals("EXCEPTION_CONTEXT", region(result, RECEIVE).get("selection"));
        assertFalse(result.regionRoots().containsKey(WRITE));
        assertTrue(result.instrumentedMethods().contains(WRITE));
    }

    @Test
    public void exceptionValueClosureSelectsOnlyRelevantMutableFieldWriter() {
        GraphCheckerRegionPlanner.Input input = new GraphCheckerRegionPlanner.Input();
        String target = "<p.Check: void check()>";
        String writer = "<p.Store: void update()>";
        String constantWriter = "<p.Store: void initialize()>";
        String field = "<p.Store: int status>";
        String constant = "<p.Store: int FLAG>";
        input.selectedMethods.addAll(Arrays.asList(target, writer, constantWriter));
        input.targetMethod = target;
        input.constantFields.add(constant);
        input.edges.add(edge("method", target, "transferKind", "LOCAL",
                "fromCell", "check.local", "toCell", target + "#exception:java.io.IOException"));
        input.edges.add(edge("method", target, "transferKind", "HEAP_READ",
                "fromCell", field, "toCell", "check.local"));
        input.edges.add(edge("method", target, "transferKind", "HEAP_READ",
                "fromCell", constant, "toCell", "check.local"));
        input.edges.add(edge("method", writer, "transferKind", "HEAP_WRITE",
                "toCell", field));
        input.edges.add(edge("method", constantWriter, "transferKind", "HEAP_WRITE",
                "toCell", constant));

        GraphCheckerRegionPlanner.Result result = GraphCheckerRegionPlanner.plan(input);
        assertEquals("EXCEPTION_CONTEXT", region(result, target).get("selection"));
        assertEquals("STATE_CONTEXT", region(result, writer).get("selection"));
        assertFalse(result.regionRoots().containsKey(constantWriter));
        assertEquals(Collections.singleton(field),
                GraphCheckerRegionPlanner.failureRelevantState(input.edges, input.constantFields));
    }

    @Test
    public void dispatchClosureStopsAtOtherAuthorityAndPortsHaveDirections() {
        GraphCheckerRegionPlanner.Input input = new GraphCheckerRegionPlanner.Input();
        String sender = "<p.Sender: void send()>";
        String senderLeaf = "<p.Sender: void build()>";
        String receiver = "<p.Receiver: void receive()>";
        String receiverLeaf = "<p.Receiver: void decode()>";
        input.selectedMethods.addAll(Arrays.asList(sender, senderLeaf, receiver, receiverLeaf));
        input.executionContextAuthorities.put(sender, "TASK_ENTRY");
        input.executionContextAuthorities.put(receiver, "RPC_ENTRY");
        input.targetMethod = receiver;
        input.edges.add(edge("method", sender, "invoke", senderLeaf));
        input.edges.add(edge("method", senderLeaf, "transferKind", "DYNAMIC_DISPATCH",
                "kind", "dispatch_activation", "toCell", receiver + ".activation"));
        input.edges.add(edge("method", receiver, "invoke", receiverLeaf));
        input.edges.add(edge("method", receiverLeaf,
                "toCell", receiverLeaf + "#exception:java.io.IOException"));
        Map<String, Object> flow = edge("portId", "XCH.1.wire.status", "name", "status",
                "javaType", "int", "exchangeSiteKey", "XCH.1");
        flow.put("producers", Collections.singletonList(edge("definitionMethod", senderLeaf,
                "callSiteId", "send#u3", "outputCaptureKind", "CALL_ARGUMENT",
                "argumentIndex", 0)));
        flow.put("consumers", Collections.singletonList(edge("definitionMethod", receiverLeaf,
                "callSiteId", "receive#u4", "outputCaptureKind", "CALL_RETURN")));
        input.communicationCallSites.add(flow);

        GraphCheckerRegionPlanner.Result result = GraphCheckerRegionPlanner.plan(input);
        List<String> senderMethods = methods(region(result, sender));
        assertEquals(Arrays.asList(senderLeaf, sender), senderMethods);
        assertFalse(senderMethods.contains(receiver));
        assertEquals("OUT", ports(region(result, sender)).get(0).get("regionPortSide"));
        assertEquals("IN", ports(region(result, receiver)).get(0).get("regionPortSide"));
        assertTrue(result.gaps.isEmpty());
    }

    private static Map<String, Object> region(GraphCheckerRegionPlanner.Result result,
                                               String root) {
        for (Map<String, Object> row : result.regions)
            if (root.equals(row.get("rootMethod"))) return row;
        throw new AssertionError("missing region root " + root);
    }

    @SuppressWarnings("unchecked")
    private static List<String> methods(Map<String, Object> region) {
        return (List<String>) region.get("methods");
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> ports(Map<String, Object> region) {
        return (List<Map<String, Object>>) region.get("communicationPorts");
    }

    private static Map<String, Object> edge(Object... cells) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int i = 0; i < cells.length; i += 2)
            result.put((String) cells[i], cells[i + 1]);
        return result;
    }
}
