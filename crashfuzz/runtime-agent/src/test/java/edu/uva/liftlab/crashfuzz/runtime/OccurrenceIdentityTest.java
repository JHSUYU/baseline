package edu.uva.liftlab.crashfuzz.runtime;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotEquals;

public class OccurrenceIdentityTest {
    @Test
    public void transientSocketAndBlockIdsDoNotBreakActorReplay() {
        String site = "/<example.DataXceiver: void replaceBlock()>#u101";
        String first = "local/DataXceiver for client /127.0.0.1:49718 "
                + "[Replacing block BP-1810136525-128.110.217.200-1791840306052:"
                + "blk_1073741832_1008 from f5205531-0996-4a38-81d2-6488ad4a823f]" + site;
        String second = "local/DataXceiver for client /127.0.0.1:55540 "
                + "[Replacing block BP-1756035988-128.110.217.200-1791840317376:"
                + "blk_1073741837_1013 from 8046a21a-9288-410a-82aa-227cd5e73437]" + site;
        assertEquals(OccurrenceIdentity.stable(first), OccurrenceIdentity.stable(second));
        assertNotEquals(OccurrenceIdentity.stable(first),
                OccurrenceIdentity.stable(second.replace("replaceBlock", "writeBlock")));
    }

    @Test
    public void regeneratedDfsClientIdKeepsBlockReceiverReplayable() {
        String site = "/<example.DataXceiver: void writeBlock()>#u257";
        String first = "local/DataXceiver for client DFSClient_NONMAPREDUCE_-529516321_1 "
                + "at /127.0.0.1:50820 [Receiving block "
                + "BP-1319269182-128.110.217.200-1791835652282:blk_1073741825_1001]" + site;
        String second = "local/DataXceiver for client DFSClient_NONMAPREDUCE_1383440130_1 "
                + "at /127.0.0.1:37998 [Receiving block "
                + "BP-1605120718-128.110.217.200-1791835769457:blk_1073741825_1001]" + site;
        assertEquals(OccurrenceIdentity.stable(first), OccurrenceIdentity.stable(second));
    }

    @Test
    public void embeddedClusterHostPortsDoNotBreakReplay() {
        String site = "/<example.AsyncFSWAL: void append()>#u9";
        String first = "local/AsyncFSWAL-0-hdfs://localhost:46863/user/test/"
                + "96b28524-5161-b1b3-2c84-94e5e9111c03/region on ms1140:41175 "
                + "RpcServer.handler=18,queue=9,port=45509" + site;
        String second = "local/AsyncFSWAL-0-hdfs://localhost:59312/user/test/"
                + "a1dff305-4807-4118-8dd1-4dc1b78fe279/region on ms1140:36393 "
                + "RpcServer.handler=18,queue=9,port=43017" + site;
        assertEquals(OccurrenceIdentity.stable(first), OccurrenceIdentity.stable(second));
        assertNotEquals(OccurrenceIdentity.stable(first),
                OccurrenceIdentity.stable(second.replace("handler=18", "handler=19")));
    }

    @Test
    public void hbaseListenerSlashPortDoesNotBreakReplay() {
        String site = "/<example.Listener: void accept()>#u3";
        String first = "local/Listener at localhost/45157" + site;
        String second = "local/Listener at localhost/40285" + site;
        assertEquals(OccurrenceIdentity.stable(first), OccurrenceIdentity.stable(second));
        assertNotEquals(OccurrenceIdentity.stable(first),
                OccurrenceIdentity.stable(second.replace("Listener", "Worker")));
    }
}
