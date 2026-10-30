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

    private JsonObject watch(String actor) {
        JsonObject value = new JsonObject();
        value.addProperty("marker", "FAULT:STATIC:IO");
        value.addProperty("siteId", "<example.Watcher: void process()>#u13");
        value.addProperty("sourceKey", "<example.Store: byte[] getData()>");
        value.addProperty("exceptionClass", "example.ConnectionLoss");
        value.addProperty("occurrence", "local/" + actor + "/<example.Watcher: void process()>#u13");
        return value;
    }

    @Test
    public void oneCallOnDistinctNodesHasNoOrder() {
        JsonArray faults = new JsonArray();
        faults.add(watch("solr:watch:node4"));
        faults.add(watch("solr:watch:node2"));
        assertTrue(IndependentReplyFanout.enabled(faults));
        JsonArray same = new JsonArray();
        same.add(watch("solr:watch:node4"));
        same.add(watch("solr:watch:node4"));
        assertFalse(IndependentReplyFanout.enabled(same));          // one node: its own order
        JsonArray other = new JsonArray();
        other.add(watch("solr:watch:node4"));
        JsonObject elsewhere = watch("solr:watch:node2");
        elsewhere.addProperty("siteId", "<example.Watcher: void refresh()>#u2");
        other.add(elsewhere);
        assertFalse(IndependentReplyFanout.enabled(other));         // two calls: ordered
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
