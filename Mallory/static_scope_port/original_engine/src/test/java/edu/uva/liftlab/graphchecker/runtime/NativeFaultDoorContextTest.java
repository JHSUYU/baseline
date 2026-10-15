package edu.uva.liftlab.graphchecker.runtime;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.File;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;
import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

/** The native door may claim an original call only by exact receiver identity. */
public final class NativeFaultDoorContextTest {
    @Test public void matchingOwnerCarriesExactOriginalCallAndMismatchFailsClosed()
            throws Exception {
        Object owner = new Object();
        CausynthTraceRecorder.startRecording();
        long callId = CausynthTraceRecorder.enterMethod(
                "<test.Native: void exercise()>", owner, "");
        try {
            CausynthTraceRecorder.recordNativeFaultDoor("rpc#u2", "client#epoch3",
                    "occurrence", 4L, "java.io.IOException", owner);
            CausynthTraceRecorder.recordNativeFaultDoor("rpc#u2", "client#epoch3",
                    "occurrence", 5L, "java.io.IOException", new Object());
        } finally {
            CausynthTraceRecorder.exitActiveMethod(null, "", false);
            CausynthTraceRecorder.stopRecording();
            Method shutdown = CausynthTraceRecorder.class.getDeclaredMethod("shutdown");
            shutdown.setAccessible(true);
            shutdown.invoke(null);
        }
        List<JsonObject> doors = new ArrayList<>();
        JsonObject enter = null;
        for (String line : Files.readAllLines(new File(
                "target/causynth-trace/runtime_trace.jsonl").toPath(),
                StandardCharsets.UTF_8)) {
            JsonObject row = new JsonParser().parse(line).getAsJsonObject();
            String event = row.get("event").getAsString();
            if ("METHOD_ENTER".equals(event)
                    && row.get("callId").getAsLong() == callId) enter = row;
            if ("NATIVE_FAULT_DOOR".equals(event)) doors.add(row);
        }
        assertEquals(2, doors.size());
        assertEquals("client", doors.get(0).get("node").getAsString());
        assertEquals(3, doors.get(0).get("actorEpochOrdinal").getAsInt());
        assertEquals("rpc#u2", doors.get(0).get("siteId").getAsString());
        assertEquals("occurrence", doors.get(0).get("occurrenceId").getAsString());
        assertEquals(4L, doors.get(0).get("ordinal").getAsLong());
        assertEquals("java.io.IOException",
                doors.get(0).get("exceptionClass").getAsString());
        assertEquals("owner_matches_active_receiver",
                doors.get(0).get("identityStatus").getAsString());
        assertEquals(callId, doors.get(0).get("callId").getAsLong());
        assertTrue(enter != null);
        assertEquals(enter.get("objectId").getAsInt(),
                doors.get(0).get("receiverObjectId").getAsInt());
        assertEquals("unproven", doors.get(1).get("identityStatus").getAsString());
        assertEquals(0L, doors.get(1).get("callId").getAsLong());
        assertEquals(0, doors.get(1).get("receiverObjectId").getAsInt());
    }
}
