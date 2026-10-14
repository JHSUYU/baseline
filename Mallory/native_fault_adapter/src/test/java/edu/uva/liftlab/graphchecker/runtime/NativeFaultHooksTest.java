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
import static org.junit.Assert.assertFalse;

/** A shutting-down workload may report a final I/O door on an interrupted thread. */
public final class NativeFaultHooksTest {
    @Test public void keyedFaultRequiresExactPayloadAndParentAcrossActors()
            throws Exception {
        Class<?> type = Class.forName(
                "edu.uva.liftlab.graphchecker.runtime.NativeFaultHooks$Fault");
        Method from = type.getDeclaredMethod("from", JsonObject.class);
        Method matches = type.getDeclaredMethod("matches", String.class,
                SourceRef.class, int.class, String.class, String.class,
                String.class);
        from.setAccessible(true);
        matches.setAccessible(true);
        String key = repeat('a');
        String parent = repeat('b');
        JsonObject row = new JsonObject();
        row.addProperty("siteId", "site");
        row.addProperty("node", "seed-node");
        row.addProperty("actorEpochOrdinal", 0);
        row.addProperty("ordinal", 2);
        row.addProperty("exceptionClass", "java.io.IOException");
        row.addProperty("messageReplayKey", key);
        row.addProperty("messageParentId", parent);
        Object fault = from.invoke(null, row);
        SourceRef moved = new SourceRef("SOLR", "SERVER", "trial-node", 5);
        assertTrue((Boolean) matches.invoke(fault, "site", moved, 9,
                "java.io.IOException", key, parent));
        assertFalse((Boolean) matches.invoke(fault, "site", moved, 9,
                "java.io.IOException", repeat('c'), parent));
        assertFalse((Boolean) matches.invoke(fault, "site", moved, 9,
                "java.io.IOException", key, repeat('c')));
        row.remove("messageParentId");
        try {
            from.invoke(null, row);
            throw new AssertionError("one-sided native message selector admitted");
        } catch (java.lang.reflect.InvocationTargetException expected) {
            assertTrue(expected.getCause() instanceof IllegalArgumentException);
        }
        row.remove("messageReplayKey");
        Object old = from.invoke(null, row);
        assertFalse((Boolean) matches.invoke(old, "site", moved, 9,
                "java.io.IOException", key, parent));
    }

    private static String repeat(char value) {
        char[] chars = new char[64];
        java.util.Arrays.fill(chars, value);
        return new String(chars);
    }

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
