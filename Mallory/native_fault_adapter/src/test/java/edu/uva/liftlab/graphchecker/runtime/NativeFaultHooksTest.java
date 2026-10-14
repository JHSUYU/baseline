package edu.uva.liftlab.graphchecker.runtime;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.junit.Test;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

/** A shutting-down workload may report a final I/O door on an interrupted thread. */
public final class NativeFaultHooksTest {
    @Test public void interruptedThreadCanStillPublishFaultReceipt() throws Exception {
        Path receipt = Files.createTempFile("native-fault-interrupted-", ".jsonl");
        Field events = NativeFaultHooks.class.getDeclaredField("events");
        Field sequence = NativeFaultHooks.class.getDeclaredField("seq");
        Method emit = NativeFaultHooks.class.getDeclaredMethod(
                "emit", String.class, JsonObject.class);
        events.setAccessible(true);
        sequence.setAccessible(true);
        emit.setAccessible(true);
        Path previousEvents = (Path) events.get(null);
        long previousSequence = sequence.getLong(null);
        try {
            events.set(null, receipt);
            sequence.setLong(null, 0L);
            Thread.currentThread().interrupt();
            JsonObject fields = new JsonObject();
            fields.addProperty("siteId", "interrupted-door");
            emit.invoke(null, "FAULT_DOOR", fields);
            assertTrue(Thread.currentThread().isInterrupted());
        } finally {
            Thread.interrupted();
            events.set(null, previousEvents);
            sequence.setLong(null, previousSequence);
        }
        JsonObject row = new JsonParser().parse(new String(
                Files.readAllBytes(receipt), StandardCharsets.UTF_8).trim()).getAsJsonObject();
        assertEquals("FAULT_DOOR", row.get("kind").getAsString());
        assertEquals("interrupted-door", row.get("siteId").getAsString());
        assertEquals(1L, row.get("seq").getAsLong());
    }
}
