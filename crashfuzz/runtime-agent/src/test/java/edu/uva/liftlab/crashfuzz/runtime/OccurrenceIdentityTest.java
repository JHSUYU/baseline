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
}
