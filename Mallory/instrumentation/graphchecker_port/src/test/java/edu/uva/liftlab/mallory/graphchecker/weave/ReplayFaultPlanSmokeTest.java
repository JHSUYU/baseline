package edu.uva.liftlab.mallory.graphchecker.weave;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public final class ReplayFaultPlanSmokeTest {
    @Test public void replaySelectorMatchesWhileActualExactOccurrenceIsRecorded()
            throws Exception {
        Path work = Files.createTempDirectory("mallory-gc-replay-plan-");
        Path trace = work.resolve("trace.jsonl");
        Path plan = work.resolve("plan.json");
        System.setProperty("mallory.graphchecker.trace.file", trace.toString());
        Object owner = new Object();
        MessageDoors.registerNode(owner, "TEST", "CLIENT", "stable-client");
        MessageDoors.startRecording();
        long request = MessageDoors.beginRequest(owner, "operation");
        try {
            MessageDoors.FaultDoorHit seed = MessageDoors.faultDoorHit("io-site", owner);
            assertFalse(seed.replayOccurrenceId.isEmpty());
            JsonObject fault = new JsonObject();
            fault.addProperty("siteId", seed.siteId);
            fault.addProperty("node", seed.node);
            fault.addProperty("occurrenceId", "deliberately-stale-exact-occurrence");
            fault.addProperty("replayOccurrenceId", seed.replayOccurrenceId);
            fault.addProperty("ordinal", seed.ordinal + 1);
            fault.addProperty("exceptionClass", "java.io.IOException");
            JsonArray faults = new JsonArray();
            faults.add(fault);
            JsonObject document = new JsonObject();
            document.add("faults", faults);
            Files.write(plan, document.toString().getBytes(StandardCharsets.UTF_8));
            System.setProperty("mallory.gc.fault.plan", plan.toString());
            try {
                TraceHooks.faultDoor("io-site", owner, "java.io.IOException", 2);
                throw new AssertionError("replay fault was not thrown");
            } catch (Throwable expected) {
                assertTrue(expected instanceof IOException);
            }
            int applied = 0;
            for (String line : Files.readAllLines(trace, StandardCharsets.UTF_8)) {
                JsonObject row = JsonParser.parseString(line).getAsJsonObject();
                if (!"FAULT_APPLIED".equals(row.get("kind").getAsString())) continue;
                applied++;
                assertEquals(seed.occurrenceId, row.get("occurrenceId").getAsString());
                assertEquals(seed.replayOccurrenceId,
                        row.get("replayOccurrenceId").getAsString());
            }
            assertEquals(1, applied);
        } finally {
            MessageDoors.endRequest(request, "operation");
            MessageDoors.stopRecording();
            System.clearProperty("mallory.gc.fault.plan");
        }
    }
}
