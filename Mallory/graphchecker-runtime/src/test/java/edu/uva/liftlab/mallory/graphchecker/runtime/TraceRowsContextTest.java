package edu.uva.liftlab.mallory.graphchecker.runtime;

import edu.uva.liftlab.mallory.graphchecker.contract.Frame;
import org.junit.Test;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;

public class TraceRowsContextTest {
    @Test public void repeatedNestedCallsKeepOnlyLiveParentCounters() {
        Object node = new Object();
        MessageDoors.registerSource(node, "test", "server", "scoped-counts", 0);
        long request = MessageDoors.beginRequest(node, "many-calls");
        try {
            for (int index = 0; index < 20000; index++) {
                Object outer = MessageDoors.openCall("outer", 0);
                Object inner = MessageDoors.openCall("inner", 0);
                MessageDoors.closeCall(inner, "inner");
                MessageDoors.closeCall(outer, "outer");
            }
            TraceRows.Context snapshot = TraceRows.snapshot();
            assertEquals(1, snapshot.frameCounts.size());
            assertEquals(1, snapshot.frameCounts.get(0).size());
            assertEquals(Integer.valueOf(20000), snapshot.frameCounts.get(0)
                    .get("CALL\nouter"));
        } finally {
            MessageDoors.endRequest(request, "many-calls");
        }
    }

    @Test public void childCountersSurviveScopeCopyAndDiscardReturnedFrames() {
        TraceRows.Context context = new TraceRows.Context();
        List<Frame> prior = new ArrayList<>();
        for (int depth = 0; depth < 32; depth++) {
            context.pushFrame(Frame.of("call#" + depth, depth));
            context.frameCounts.get(depth + 1).put("CALL\nchild", depth + 1);
            assertEquals(context.frames.size() + 1, context.frameCounts.size());
        }
        prior.addAll(context.frames);
        List<Map<String, Integer>> priorCounts = new ArrayList<>();
        for (Map<String, Integer> level : context.frameCounts) {
            priorCounts.add(new HashMap<>(level));
        }
        TraceRows.Context copied = context.copy();
        for (int depth = 0; depth < 16; depth++) context.popFrame();
        assertEquals(17, context.frameCounts.size());
        assertEquals(priorCounts, copied.frameCounts);
        context.restoreFrames(prior, priorCounts);
        assertEquals(priorCounts, context.frameCounts);
        context.frameCounts.get(32).put("CALL\nchild", 99);
        assertEquals(Integer.valueOf(32), copied.frameCounts.get(32)
                .get("CALL\nchild"));
        context.resetFrames();
        assertEquals(1, context.frameCounts.size());
        context.pushFrame(Frame.of("fresh", 0));
        assertEquals(2, context.frameCounts.size());
        assertEquals(0, context.frameCounts.get(1).size());
    }
}
