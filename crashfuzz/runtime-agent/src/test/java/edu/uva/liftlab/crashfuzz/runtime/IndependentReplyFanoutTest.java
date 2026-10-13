package edu.uva.liftlab.crashfuzz.runtime;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import org.junit.Test;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class IndependentReplyFanoutTest {
    private JsonObject fault(String node, String shape) {
        JsonObject value = new JsonObject();
        value.addProperty("marker", "FAULT:STATIC:IO");
        value.addProperty("siteId", "<example.Actor: void heartbeat()>#u1");
        value.addProperty("sourceKey", "<example.Rpc: example.Reply send()>");
        value.addProperty("exceptionClass", "java.io.IOException");
        value.addProperty("phase", "after");
        value.addProperty("responseShape", shape);
        value.addProperty("occurrence", "local/heartbeat|" + node
                + "/<example.Actor: void heartbeat()>#u1");
        return value;
    }

    @Test
    public void recognizesEquivalentRepliesToDistinctNodes() {
        String shape = "example.Reply|commands=[example.Update]";
        JsonArray faults = new JsonArray();
        faults.add(fault("node1", shape));
        faults.add(fault("node2", shape));
        faults.add(fault("node3", shape));
        assertTrue(IndependentReplyFanout.enabled(faults));
    }

    @Test
    public void keepsSameNodeAndDifferentReplyPlansOrdered() {
        String shape = "example.Reply|commands=[example.Update]";
        JsonArray repeated = new JsonArray();
        repeated.add(fault("node1", shape));
        repeated.add(fault("node1", shape));
        assertFalse(IndependentReplyFanout.enabled(repeated));
        JsonArray different = new JsonArray();
        different.add(fault("node1", shape));
        different.add(fault("node2", "example.Reply|commands=[example.Other]"));
        assertFalse(IndependentReplyFanout.enabled(different));
        JsonArray empty = new JsonArray();
        empty.add(fault("node1", "example.Reply|commands=[]"));
        empty.add(fault("node2", "example.Reply|commands=[]"));
        assertFalse(IndependentReplyFanout.enabled(empty));
    }
}
