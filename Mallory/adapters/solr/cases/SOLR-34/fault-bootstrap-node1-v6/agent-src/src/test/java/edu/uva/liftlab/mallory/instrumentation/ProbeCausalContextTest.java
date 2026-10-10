package edu.uva.liftlab.mallory.instrumentation;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;
import org.junit.Test;
import static org.junit.Assert.*;

public final class ProbeCausalContextTest {
  @Test public void linksRootRegionToExactObservedReceiveWithoutInventingAnotherHandoff()
      throws Exception {
    File eventsFile = File.createTempFile("mallory-causal-context", ".jsonl");
    Probe.install("causal-context", eventsFile, new FaultPlan());
    String token = "zk-quorum:connection-7:request-42";
    try (Probe.NodeScope ignored = Probe.withNode("zk2", 1)) {
      Probe.receive("zk-quorum", token, "request", "LearnerHandler.readPacket");
      try (Probe.ContextScope context = Probe.withCausalContext(token)) {
        assertEquals(token, Probe.captureContext());
        assertEquals("zk2", Probe.currentNode());
        assertEquals(1, Probe.currentEpoch());
        Probe.regionEnter("LearnerHandler.request");
        Probe.method("LearnerHandler.submitLearnerRequest");
        Probe.regionExit("LearnerHandler.request");
      }
      assertEquals("root", Probe.captureContext());
      assertEquals("zk2", Probe.currentNode());
      assertEquals(1, Probe.currentEpoch());
    }

    List<JsonObject> events = readEvents(eventsFile);
    assertEquals(1, countType(events, "RECV"));
    assertEquals(1, countType(events, "REGION_ENTER"));
    assertEquals(0, countType(events, "TASK_CLAIM"));
    JsonObject region = firstType(events, "REGION_ENTER");
    assertEquals(token, region.get("parent_id").getAsString());
    assertEquals(token, region.get("context").getAsString());
    assertEquals("zk2", region.get("node").getAsString());
    assertEquals(1, region.get("epoch").getAsInt());
    assertTrue(region.get("occurrence").getAsString().contains(token));
  }

  @Test public void nestedScopesRestorePriorContextAndRejectMissingToken() throws Exception {
    Probe.install("causal-nested", File.createTempFile("mallory-causal-nested", ".jsonl"),
        new FaultPlan());
    try (Probe.NodeScope ignored = Probe.withNode("zk4", 3);
         Probe.ContextScope outer = Probe.withCausalContext("packet-1")) {
      assertEquals("packet-1", Probe.captureContext());
      try (Probe.ContextScope inner = Probe.withCausalContext("packet-2")) {
        assertEquals("packet-2", Probe.captureContext());
      }
      assertEquals("packet-1", Probe.captureContext());
      try {
        Probe.withCausalContext("  ");
        fail("Blank token should be rejected");
      } catch (IllegalArgumentException expected) {
        assertEquals("packet-1", Probe.captureContext());
      }
      assertEquals("zk4", Probe.currentNode());
      assertEquals(3, Probe.currentEpoch());
    }
    assertEquals("root", Probe.captureContext());
  }

  @Test public void rootSegmentsAreThreadScopedAndRotateAtRegionAndContextBoundaries()
      throws Exception {
    File eventsFile = File.createTempFile("mallory-root-segments", ".jsonl");
    Probe.install("root-segments", eventsFile, new FaultPlan());
    try (Probe.NodeScope ignored = Probe.withNode("zk1", 2)) {
      Probe.send("rpc", "before", "request", "before-region");
      Probe.regionEnter("work");
      Probe.regionExit("work");
      Probe.send("rpc", "after", "request", "after-region");
      try (Probe.ContextScope scope = Probe.withCausalContext("handoff")) {
        Probe.send("rpc", "scoped", "request", "context-work");
      }
      Probe.send("rpc", "restored", "request", "restored-root");
    }
    List<JsonObject> rows = readEvents(eventsFile);
    List<JsonObject> sends = new ArrayList<JsonObject>();
    for (JsonObject row : rows)
      if ("SEND".equals(row.get("type").getAsString())) sends.add(row);
    assertEquals(4, sends.size());
    String before = sends.get(0).get("occurrence").getAsString();
    String after = sends.get(1).get("occurrence").getAsString();
    String restored = sends.get(3).get("occurrence").getAsString();
    assertTrue(before.startsWith("unscoped:zk1:2:root:thread:"));
    assertNotEquals(before, after);
    assertNotEquals(after, restored);
    assertEquals(before, firstType(rows, "REGION_ENTER").get("parent_id").getAsString());
    assertEquals(sends.get(0).get("thread_id").getAsLong(),
        firstType(rows, "REGION_ENTER").get("thread_id").getAsLong());
  }

  @Test public void reusedCausalTokenDoesNotMergeTwoThreads() throws Exception {
    File eventsFile = File.createTempFile("mallory-token-threads", ".jsonl");
    Probe.install("token-threads", eventsFile, new FaultPlan());
    Runnable work = new Runnable() {
      @Override public void run() {
        try (Probe.NodeScope node = Probe.withNode("zk2", 0);
             Probe.ContextScope context = Probe.withCausalContext("reused-token")) {
          Probe.send("rpc", "message", "request", "send");
        }
      }
    };
    Thread first = new Thread(work, "first-token-thread");
    Thread second = new Thread(work, "second-token-thread");
    first.start();
    second.start();
    first.join();
    second.join();
    List<JsonObject> sends = new ArrayList<JsonObject>();
    for (JsonObject row : readEvents(eventsFile))
      if ("SEND".equals(row.get("type").getAsString())) sends.add(row);
    assertEquals(2, sends.size());
    assertNotEquals(sends.get(0).get("thread_id"), sends.get(1).get("thread_id"));
    assertNotEquals(sends.get(0).get("occurrence"), sends.get(1).get("occurrence"));
    for (JsonObject send : sends)
      assertTrue(send.get("occurrence").getAsString().startsWith(
          "unscoped:zk2:0:reused-token:thread:"));
  }

  private static List<JsonObject> readEvents(File path) throws Exception {
    List<JsonObject> events = new ArrayList<JsonObject>();
    for (String line : Files.readAllLines(path.toPath(), StandardCharsets.UTF_8))
      events.add(new JsonParser().parse(line).getAsJsonObject());
    return events;
  }

  private static int countType(List<JsonObject> events, String type) {
    int count = 0;
    for (JsonObject event : events)
      if (type.equals(event.get("type").getAsString())) count++;
    return count;
  }

  private static JsonObject firstType(List<JsonObject> events, String type) {
    for (JsonObject event : events)
      if (type.equals(event.get("type").getAsString())) return event;
    return null;
  }
}
