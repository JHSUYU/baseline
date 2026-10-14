package edu.uva.liftlab.mallory.graphchecker.weave;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors;
import java.io.IOException;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

/** A replay selector must survive an exact occurrence change without losing actor identity. */
public final class GcFaultPlanMatcherTest {
    @Test public void uniqueSerializedMessageMayMoveActorsButChangedPayloadCannotMatch()
            throws Exception {
        Field singleton = GcFaultPlan.class.getDeclaredField("current");
        singleton.setAccessible(true);
        Object priorMatcher = singleton.get(null);
        String priorPlan = System.getProperty("mallory.gc.fault.plan");
        String priorTrace = System.getProperty("mallory.graphchecker.trace.file");
        Path work = Files.createTempDirectory("mallory-message-replay-");
        System.setProperty("mallory.graphchecker.trace.file", work.resolve("trace.jsonl").toString());
        Object sender = new Object();
        Object receiver = new Object();
        Object changedActor = new Object();
        MessageDoors.registerNode(sender, "TEST", "CLIENT", "sender");
        MessageDoors.registerNode(receiver, "TEST", "CLIENT", "receiver");
        MessageDoors.registerNode(changedActor, "TEST", "CLIENT", "changed-actor");
        MessageDoors.startRecording();
        try {
            singleton.set(null, null);
            MessageDoors.FaultDoorHit seed = messageDoor(sender, "payload-a");
            MessageDoors.FaultDoorHit migrated = messageDoor(receiver, "payload-a");
            MessageDoors.FaultDoorHit changed = messageDoor(changedActor, "payload-b");
            MessageDoors.FaultDoorHit ordinalDrift = messageDoor(receiver, "payload-a");
            MessageDoors.FaultDoorHit otherParent = messageDoor(receiver, "payload-a", "R.other");
            assertFalse(seed.node.equals(migrated.node));
            assertEquals(seed.messageReplayKey, migrated.messageReplayKey);
            assertEquals(seed.messageParentId, migrated.messageParentId);
            assertFalse(seed.messageReplayKey.equals(changed.messageReplayKey));
            assertEquals(seed.messageParentId, changed.messageParentId);
            assertFalse(seed.messageParentId.equals(ordinalDrift.messageParentId));
            assertFalse(seed.messageParentId.equals(otherParent.messageParentId));

            JsonObject fault = new JsonObject();
            fault.addProperty("siteId", seed.siteId);
            fault.addProperty("node", seed.node);
            fault.addProperty("occurrenceId", seed.occurrenceId);
            fault.addProperty("replayOccurrenceId", seed.replayOccurrenceId);
            fault.addProperty("ordinal", seed.ordinal);
            fault.addProperty("messageReplayKey", seed.messageReplayKey);
            fault.addProperty("messageParentId", seed.messageParentId);
            fault.addProperty("exceptionClass", IOException.class.getName());
            JsonArray faults = new JsonArray();
            faults.add(fault);
            JsonObject document = new JsonObject();
            document.add("faults", faults);
            Path plan = work.resolve("plan.json");
            Files.write(plan, document.toString().getBytes(StandardCharsets.UTF_8));
            System.setProperty("mallory.gc.fault.plan", plan.toString());
            GcFaultPlan matcher = GcFaultPlan.current();
            assertNull(matcher.consume(changed, IOException.class.getName()));
            assertNull(matcher.consume(ordinalDrift, IOException.class.getName()));
            assertNull(matcher.consume(otherParent, IOException.class.getName()));
            assertTrue(matcher.consume(migrated, IOException.class.getName()) instanceof IOException);
        } finally {
            MessageDoors.stopRecording();
            singleton.set(null, priorMatcher);
            if (priorPlan == null) System.clearProperty("mallory.gc.fault.plan");
            else System.setProperty("mallory.gc.fault.plan", priorPlan);
            if (priorTrace == null) System.clearProperty("mallory.graphchecker.trace.file");
            else System.setProperty("mallory.graphchecker.trace.file", priorTrace);
        }
    }

    private static MessageDoors.FaultDoorHit messageDoor(Object owner, String data) {
        return messageDoor(owner, data, "R.offer");
    }

    private static MessageDoors.FaultDoorHit messageDoor(Object owner, String data,
                                                         String region) {
        long request = MessageDoors.beginRequest(owner, "offer");
        try (MessageDoors.MessagePayloadScope ignored =
                     MessageDoors.beginMessagePayload("QUEUE", "/queue", data.getBytes(StandardCharsets.UTF_8))) {
            MessageDoors.enterRegion(region, "offer-entry", 0);
            try {
                return MessageDoors.faultDoorHit("queue-io", owner);
            } finally {
                MessageDoors.exitRegion(region);
            }
        } finally {
            MessageDoors.endRequest(request, "offer");
        }
    }

    @Test public void replaySelectorMatchesOnlyItsActorAndLineage() throws Exception {
        Field singleton = GcFaultPlan.class.getDeclaredField("current");
        singleton.setAccessible(true);
        Object previousMatcher = singleton.get(null);
        String previousPlan = System.getProperty("mallory.gc.fault.plan");
        String previousTrace = System.getProperty("mallory.graphchecker.trace.file");
        Path work = Files.createTempDirectory("mallory-gc-matcher-");
        System.setProperty("mallory.graphchecker.trace.file", work.resolve("trace.jsonl").toString());
        Object intendedOwner = new Object();
        Object otherOwner = new Object();
        MessageDoors.registerNode(intendedOwner, "TEST", "CLIENT", "intended");
        MessageDoors.registerNode(otherOwner, "TEST", "CLIENT", "other");
        MessageDoors.startRecording();
        try {
            singleton.set(null, null);
            long intendedRequest = MessageDoors.beginRequest(intendedOwner, "request-a");
            MessageDoors.FaultDoorHit intended;
            try {
                intended = MessageDoors.faultDoorHit("io-site", intendedOwner);
            } finally {
                MessageDoors.endRequest(intendedRequest, "request-a");
            }
            long otherLineageRequest = MessageDoors.beginRequest(intendedOwner, "request-b");
            MessageDoors.FaultDoorHit otherLineage;
            try {
                otherLineage = MessageDoors.faultDoorHit("io-site", intendedOwner);
            } finally {
                MessageDoors.endRequest(otherLineageRequest, "request-b");
            }
            long otherActorRequest = MessageDoors.beginRequest(otherOwner, "request-a");
            MessageDoors.FaultDoorHit otherActor;
            try {
                otherActor = MessageDoors.faultDoorHit("io-site", otherOwner);
            } finally {
                MessageDoors.endRequest(otherActorRequest, "request-a");
            }
            assertEquals(intended.node, otherLineage.node);
            assertFalse(intended.replayOccurrenceId.equals(otherLineage.replayOccurrenceId));
            assertFalse(intended.node.equals(otherActor.node));
            assertEquals(intended.ordinal, otherLineage.ordinal);
            assertEquals(intended.ordinal, otherActor.ordinal);

            JsonObject fault = new JsonObject();
            fault.addProperty("siteId", intended.siteId);
            fault.addProperty("node", intended.node);
            fault.addProperty("occurrenceId", "exact-occurrence-from-another-run");
            fault.addProperty("replayOccurrenceId", intended.replayOccurrenceId);
            fault.addProperty("ordinal", intended.ordinal);
            fault.addProperty("exceptionClass", IOException.class.getName());
            JsonArray faults = new JsonArray();
            faults.add(fault);
            JsonObject document = new JsonObject();
            document.add("faults", faults);
            Path plan = work.resolve("plan.json");
            Files.write(plan, document.toString().getBytes(StandardCharsets.UTF_8));
            System.setProperty("mallory.gc.fault.plan", plan.toString());
            GcFaultPlan matcher = GcFaultPlan.current();
            assertNull(matcher.consume(otherLineage, IOException.class.getName()));
            assertNull(matcher.consume(otherActor, IOException.class.getName()));
            assertTrue(matcher.consume(intended, IOException.class.getName()) instanceof IOException);
        } finally {
            MessageDoors.stopRecording();
            singleton.set(null, previousMatcher);
            if (previousPlan == null) System.clearProperty("mallory.gc.fault.plan");
            else System.setProperty("mallory.gc.fault.plan", previousPlan);
            if (previousTrace == null) System.clearProperty("mallory.graphchecker.trace.file");
            else System.setProperty("mallory.graphchecker.trace.file", previousTrace);
        }
    }
}
