package edu.uva.liftlab.mallory.graphchecker.weave;

import edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder;
import edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors;
import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;

/** The opt-in bridge forwards the exact native hit before any injection. */
public final class NativeFaultDoorBridgeTest {
    @Test public void nativeHitIsForwardedWithItsOwnerAndDoorOrdinal() {
        String prior = System.getProperty("mallory.gc.nativeFaultDoorContext");
        System.setProperty("mallory.gc.nativeFaultDoorContext", "true");
        Object owner = new Object();
        MessageDoors.registerNode(owner, "EXTERNAL_APP", "CLIENT", "bridge-smoke");
        MessageDoors.startRecording();
        long request = MessageDoors.beginRequest(owner, "operation");
        try {
            TraceHooks.faultDoor("rpc#u2", owner, "java.io.IOException", 0);
            assertEquals("rpc#u2", CausynthTraceRecorder.siteId);
            assertEquals("bridge-smoke#epoch0", CausynthTraceRecorder.nodeId);
            assertTrue(CausynthTraceRecorder.occurrenceId.length() > 0);
            assertTrue(CausynthTraceRecorder.ordinal > 0L);
            assertEquals("java.io.IOException", CausynthTraceRecorder.exceptionClass);
            assertSame(owner, CausynthTraceRecorder.owner);
        } finally {
            MessageDoors.endRequest(request, "operation");
            MessageDoors.stopRecording();
            if (prior == null) System.clearProperty("mallory.gc.nativeFaultDoorContext");
            else System.setProperty("mallory.gc.nativeFaultDoorContext", prior);
        }
    }
}
