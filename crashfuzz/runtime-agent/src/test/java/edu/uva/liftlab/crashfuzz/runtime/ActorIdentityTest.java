package edu.uva.liftlab.crashfuzz.runtime;

import org.apache.hadoop.hdfs.server.datanode.BPServiceActor;
import org.apache.hadoop.hdfs.server.datanode.DataXceiver;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertTrue;

public class ActorIdentityTest {
    @Test
    public void miniDfsActorUsesFirstConfiguredDataSlot() {
        BPServiceActor first = new BPServiceActor("[DISK]file:/tmp/runA/data/dfs/data/data1,"
                + "[DISK]file:/tmp/runA/data/dfs/data/data2");
        BPServiceActor second = new BPServiceActor("[DISK]file:/tmp/runB/data/dfs/data/data3,"
                + "[DISK]file:/tmp/runB/data/dfs/data/data4");
        ActorIdentity.Resolution one = ActorIdentity.resolve(first);
        ActorIdentity.Resolution two = ActorIdentity.resolve(second);
        assertEquals("hdfs:dn:data1", one.logicalNodeId);
        assertEquals("hdfs:dn:data3", two.logicalNodeId);
        assertFalse(one.gap);
        assertFalse(two.gap);
        assertEquals(one.logicalNodeId, ActorIdentity.resolve(first).logicalNodeId);
    }

    @Test
    public void missingMiniDfsSlotIsAnExplicitPerActorGap() {
        ActorIdentity.Resolution one = ActorIdentity.resolve(
                new BPServiceActor("file:/var/lib/hdfs/dn"));
        ActorIdentity.Resolution two = ActorIdentity.resolve(
                new BPServiceActor("file:/var/lib/hdfs/dn"));
        assertTrue(one.gap);
        assertTrue(two.gap);
        assertNotEquals(one.logicalNodeId, two.logicalNodeId);
        assertEquals("dfs.datanode.data.dir has no MiniDFSCluster dataN slot", one.reason);
    }

    @Test
    public void dataXceiverUsesItsOwningDataNodeSlot() {
        DataXceiver first = new DataXceiver("[DISK]file:/tmp/runA/data/dfs/data/data1,"
                + "[DISK]file:/tmp/runA/data/dfs/data/data2");
        DataXceiver second = new DataXceiver("[DISK]file:/tmp/runA/data/dfs/data/data5,"
                + "[DISK]file:/tmp/runA/data/dfs/data/data6");
        ActorIdentity.Resolution one = ActorIdentity.resolve(first);
        ActorIdentity.Resolution two = ActorIdentity.resolve(second);
        assertEquals("hdfs:dn:data1", one.logicalNodeId);
        assertEquals("hdfs:dn:data5", two.logicalNodeId);
        assertFalse(one.gap);
        assertFalse(two.gap);
        assertEquals(one.logicalNodeId, ActorIdentity.resolve(first).logicalNodeId);
    }

    @Test
    public void dataXceiverWithoutMiniDfsSlotDoesNotCollapseActors() {
        ActorIdentity.Resolution one = ActorIdentity.resolve(
                new DataXceiver("file:/var/lib/hdfs/dn"));
        ActorIdentity.Resolution two = ActorIdentity.resolve(
                new DataXceiver("file:/var/lib/hdfs/dn"));
        assertTrue(one.gap);
        assertTrue(two.gap);
        assertNotEquals(one.logicalNodeId, two.logicalNodeId);
        assertEquals("dfs.datanode.data.dir has no MiniDFSCluster dataN slot", one.reason);
    }

    @Test
    public void dataTransferUsesItsEnclosingDataNodeSlot() {
        ActorIdentity.Resolution first = ActorIdentity.resolve(
                new DataNode("[DISK]file:/tmp/runA/data/dfs/data/data1").new DataTransfer());
        ActorIdentity.Resolution second = ActorIdentity.resolve(
                new DataNode("[DISK]file:/tmp/runA/data/dfs/data/data5").new DataTransfer());
        assertEquals("hdfs:dn:data1", first.logicalNodeId);
        assertEquals("hdfs:dn:data5", second.logicalNodeId);
        assertFalse(first.gap);
        assertFalse(second.gap);
    }

    @Test
    public void actorThreadPropagatesNodeIdentityIntoHelperIoAndClearsIt() {
        DataXceiver actor = new DataXceiver(
                "[DISK]file:/tmp/runA/data/dfs/data/data5");
        ActorIdentity.bindCurrentThread(actor);
        try {
            assertEquals("hdfs:dn:data5", ActorIdentity.resolve(
                    new Object(), "<example.Helper: void io()>#u1", "worker")
                    .logicalNodeId);
        } finally {
            ActorIdentity.clearCurrentThread();
        }
        assertFalse(ActorIdentity.resolve(new Object(),
                "<example.Helper: void io()>#u1", "worker").applies());
    }
}
