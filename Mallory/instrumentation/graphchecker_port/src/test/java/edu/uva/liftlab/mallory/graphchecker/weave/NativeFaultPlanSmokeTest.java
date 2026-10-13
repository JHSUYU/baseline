package edu.uva.liftlab.mallory.graphchecker.weave;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import org.junit.Test;

public final class NativeFaultPlanSmokeTest {
    @Test public void orderedFaultsCarryExactObservedDoorIdentity() throws Exception {
        Path work = Files.createTempDirectory("mallory-gc-native-plan-");
        Path trace = work.resolve("trace.jsonl");
        Path plan = work.resolve("plan.json");
        System.setProperty("mallory.graphchecker.trace.file", trace.toString());
        Object owner = new Object();
        MessageDoors.registerNode(owner, "EXTERNAL_APP", "CLIENT", "native-smoke");
        MessageDoors.startRecording();
        long request = MessageDoors.beginRequest(owner, "operation");
        try {
            MessageDoors.FaultDoorHit first = MessageDoors.faultDoorHit("io-site", owner);
            JsonObject document = new JsonObject();
            JsonArray faults = new JsonArray();
            for (int offset = 1; offset <= 2; offset++) {
                JsonObject fault = new JsonObject();
                fault.addProperty("siteId", first.siteId);
                fault.addProperty("node", first.node);
                fault.addProperty("occurrenceId", first.occurrenceId);
                fault.addProperty("ordinal", first.ordinal + offset);
                fault.addProperty("exceptionClass", "java.io.IOException");
                faults.add(fault);
            }
            document.add("faults", faults);
            Files.write(plan, document.toString().getBytes(StandardCharsets.UTF_8));
            System.setProperty("mallory.gc.fault.plan", plan.toString());
            for (int attempt = 0; attempt < 2; attempt++) {
                try {
                    TraceHooks.faultDoor("io-site", owner, "java.io.IOException", 2);
                    throw new AssertionError("native fault was not thrown");
                } catch (Throwable expected) {
                    assertTrue(expected instanceof IOException);
                    assertEquals("Mallory injected at GraphChecker fault door", expected.getMessage());
                }
            }
            // Both ordered faults were consumed. A later matching door cannot
            // silently reapply either fault.
            TraceHooks.faultDoor("io-site", owner, "java.io.IOException", 2);
            List<String> rows = Files.readAllLines(trace, StandardCharsets.UTF_8);
            int applied = 0;
            for (String text : rows) {
                JsonObject row = JsonParser.parseString(text).getAsJsonObject();
                if (!"FAULT_APPLIED".equals(row.get("kind").getAsString())) continue;
                applied++;
                assertEquals(first.node, row.get("node").getAsString());
                assertEquals(first.occurrenceId, row.get("occurrenceId").getAsString());
                assertEquals(first.siteId, row.get("siteId").getAsString());
                assertEquals(first.ordinal + applied, row.get("doorOrdinal").getAsLong());
                assertEquals("java.io.IOException", row.get("exceptionClass").getAsString());
            }
            assertEquals(2, applied);
            assertTrue(first.ordinal >= 1);
        } finally {
            MessageDoors.endRequest(request, "operation");
            MessageDoors.stopRecording();
            System.clearProperty("mallory.gc.fault.plan");
        }
    }
}
