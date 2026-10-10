package edu.uva.liftlab.mallory.instrumentation;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.fail;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.List;
import org.junit.Test;

public final class Solr15ParentSelectorTest {
  private static final String PATH = "/live_nodes/127.0.0.1:42553_";

  private static FaultPlan plan() {
    FaultPlan result = new FaultPlan();
    FaultPlan.Fault fault = new FaultPlan.Fault();
    fault.fault_id = "f1";
    fault.fault_type = "EXCEPTION";
    fault.exception_class = "java.io.IOException";
    fault.point = new FaultPlan.Point();
    fault.point.site = Solr15ParentSelector.NATIVE;
    fault.point.node = "control";
    fault.point.epoch = 0;
    fault.point.solr15_parent_lookup = "second";
    result.faults.add(fault);
    return result;
  }

  private static FaultPlan threeFaultPlan(String literalResource, String resourceRole) {
    FaultPlan result = plan();
    FaultPlan.Fault retry = new FaultPlan.Fault();
    retry.fault_id = "f2";
    retry.fault_type = "EXCEPTION";
    retry.exception_class = "java.io.IOException";
    retry.point = new FaultPlan.Point();
    retry.point.site = Solr15ParentSelector.NATIVE;
    retry.point.node = "control";
    retry.point.epoch = 0;
    retry.point.solr15_parent_lookup = "retry";
    result.faults.add(retry);
    FaultPlan.Fault third = new FaultPlan.Fault();
    third.fault_id = "f3";
    third.fault_type = "EXCEPTION";
    third.exception_class = "java.io.IOException";
    third.point = new FaultPlan.Point();
    third.point.site = Solr15ParentSelector.NATIVE;
    third.point.node = "control";
    third.point.epoch = 0;
    third.point.solr15_parent_lookup = "after_pair";
    third.point.resource = literalResource;
    third.point.resource_role = resourceRole;
    result.faults.add(third);
    return result;
  }

  private static void expectInjection(String site, String resource) {
    try {
      door(site, resource);
      fail("qualified fault must inject");
    } catch (Throwable expected) {
      assertEquals("java.io.IOException", expected.getClass().getName());
    }
  }

  private static void door(String site, String path) {
    Probe.beforeDoor(site, "java.io.IOException", path);
  }

  private static int applied(File events, long expectedOrdinal) throws Exception {
    int count = 0;
    List<String> lines = Files.readAllLines(events.toPath(), StandardCharsets.UTF_8);
    for (String line : lines) {
      JsonObject row = new JsonParser().parse(line).getAsJsonObject();
      if ("FAULT_APPLIED".equals(row.get("type").getAsString())) {
        assertEquals(PATH, row.get("resource").getAsString());
        assertEquals(PATH, row.get("bound_resource").getAsString());
        assertEquals("second", row.get("selector_phase").getAsString());
        if (expectedOrdinal > 0)
          assertEquals(expectedOrdinal, row.get("door_ordinal").getAsLong());
        count++;
      }
    }
    return count;
  }

  @Test public void shiftedOrdinalAndOverseerQueueCannotConsumeFault() throws Exception {
    File events = File.createTempFile("solr15-selector", ".jsonl");
    Probe.install("shifted", events, plan());
    Probe.setNode("control", 0);
    Probe.regionEnter(Solr15ParentSelector.SPLIT);
    door(Solr15ParentSelector.FIRST, null);
    door(Solr15ParentSelector.NATIVE, PATH);
    for (int index = 0; index < 45; index++)
      door(Solr15ParentSelector.NATIVE, "/overseer/queue");
    door(Solr15ParentSelector.SECOND, null);
    try {
      door(Solr15ParentSelector.NATIVE, PATH);
      fail("qualified second parent lookup must inject");
    } catch (Throwable expected) {
      assertEquals("java.io.IOException", expected.getClass().getName());
    }
    assertEquals(1, applied(events, 47));
  }

  @Test public void wrongNextPathFailsClosedEvenWhenDesiredPathAppearsLater() throws Exception {
    File events = File.createTempFile("solr15-selector", ".jsonl");
    Probe.install("wrong-path", events, plan());
    Probe.setNode("control", 0);
    Probe.regionEnter(Solr15ParentSelector.SPLIT);
    door(Solr15ParentSelector.FIRST, null);
    door(Solr15ParentSelector.NATIVE, PATH);
    door(Solr15ParentSelector.SECOND, null);
    door(Solr15ParentSelector.NATIVE, "/overseer/queue");
    door(Solr15ParentSelector.NATIVE, PATH);
    assertEquals(0, applied(events, 0));
  }

  @Test public void actorEpochOccurrenceAndParentPathMustAgree() {
    Solr15ParentSelector selector = new Solr15ParentSelector();
    assertFalse(Solr15ParentSelector.liveNodePath("/live_nodes/"));
    assertFalse(Solr15ParentSelector.liveNodePath("/live_nodes/a/b"));
    selector.observe(Solr15ParentSelector.FIRST, "control", 0, "split-1", null);
    assertNull(selector.observe(Solr15ParentSelector.NATIVE, "control", 0,
        "split-1", PATH));
    selector.observe(Solr15ParentSelector.SECOND, "control", 1, "split-1", null);
    assertNull(selector.observe(Solr15ParentSelector.NATIVE, "control", 0,
        "split-1", PATH));
    selector.observe(Solr15ParentSelector.SECOND, "control", 0, "split-2", null);
    assertNull(selector.observe(Solr15ParentSelector.NATIVE, "control", 0,
        "split-2", PATH));
    selector.observe(Solr15ParentSelector.SECOND, "control", 0, "split-1", null);
    assertNull(selector.observe(Solr15ParentSelector.NATIVE, "shard-1", 0,
        "split-1", PATH));
    assertNull(selector.observe(Solr15ParentSelector.NATIVE, "control", 0,
        "split-1", PATH));
  }

  @Test public void retryRequiresAppliedSecondFaultOnSameExecutionAndPath() {
    Solr15ParentSelector selector = new Solr15ParentSelector();
    selector.observe(Solr15ParentSelector.FIRST, "control", 0, "split-1", null);
    selector.observe(Solr15ParentSelector.NATIVE, "control", 0, "split-1", PATH);
    selector.observe(Solr15ParentSelector.SECOND, "control", 0, "split-1", null);
    assertEquals("second", selector.observe(Solr15ParentSelector.NATIVE,
        "control", 0, "split-1", PATH));
    assertNull(selector.observe(Solr15ParentSelector.NATIVE, "control", 0,
        "split-1", PATH));
    selector.markApplied("second");
    assertNull(selector.observe(Solr15ParentSelector.NATIVE, "control", 0,
        "split-1", "/overseer/queue"));
    assertEquals("retry", selector.observe(Solr15ParentSelector.NATIVE,
        "control", 0, "split-1", PATH));
  }

  @Test public void thirdFaultMatchesLiteralResourceDespiteOrdinalDrift() throws Exception {
    File events = File.createTempFile("solr15-third-literal", ".jsonl");
    Probe.install("third-literal", events, threeFaultPlan("/overseer/queue", null));
    Probe.setNode("control", 0);
    Probe.regionEnter(Solr15ParentSelector.SPLIT);
    door(Solr15ParentSelector.FIRST, null);
    door(Solr15ParentSelector.NATIVE, PATH);
    for (int index = 0; index < 45; index++)
      door(Solr15ParentSelector.NATIVE, "/overseer/queue");
    door(Solr15ParentSelector.SECOND, null);
    expectInjection(Solr15ParentSelector.NATIVE, PATH);
    expectInjection(Solr15ParentSelector.NATIVE, PATH);
    door(Solr15ParentSelector.NATIVE, PATH);
    expectInjection(Solr15ParentSelector.NATIVE, "/overseer/queue");
    int count = 0;
    for (String line : Files.readAllLines(events.toPath(), StandardCharsets.UTF_8)) {
      JsonObject row = new JsonParser().parse(line).getAsJsonObject();
      if ("FAULT_APPLIED".equals(row.get("type").getAsString())) {
        count++;
        if ("f3".equals(row.get("fault_id").getAsString())) {
          assertEquals("/overseer/queue", row.get("resource").getAsString());
          assertEquals("after_pair", row.get("selector_phase").getAsString());
        }
      }
    }
    assertEquals(3, count);
  }

  @Test public void thirdFaultBindsCurrentParentPathRatherThanLiteralPort() throws Exception {
    File events = File.createTempFile("solr15-third-parent", ".jsonl");
    Probe.install("third-parent", events, threeFaultPlan(null, "bound_parent"));
    Probe.setNode("control", 0);
    Probe.regionEnter(Solr15ParentSelector.SPLIT);
    door(Solr15ParentSelector.FIRST, null);
    door(Solr15ParentSelector.NATIVE, PATH);
    door(Solr15ParentSelector.SECOND, null);
    expectInjection(Solr15ParentSelector.NATIVE, PATH);
    expectInjection(Solr15ParentSelector.NATIVE, PATH);
    door(Solr15ParentSelector.NATIVE, "/overseer/queue");
    expectInjection(Solr15ParentSelector.NATIVE, PATH);
    int third = 0;
    for (String line : Files.readAllLines(events.toPath(), StandardCharsets.UTF_8)) {
      JsonObject row = new JsonParser().parse(line).getAsJsonObject();
      if ("FAULT_APPLIED".equals(row.get("type").getAsString())
          && "f3".equals(row.get("fault_id").getAsString())) {
        third++;
        assertEquals(PATH, row.get("resource").getAsString());
      }
    }
    assertEquals(1, third);
  }

  @Test public void outsideActorNativeRequiresExactResourceOccurrenceAndOrdinal() {
    FaultPlan.Fault fault = new FaultPlan.Fault();
    fault.point = new FaultPlan.Point();
    fault.point.site = Solr15ParentSelector.NATIVE;
    fault.point.node = "shard-2";
    fault.point.epoch = 0;
    fault.point.occurrence = "shard-2:0:task:9";
    fault.point.door_ordinal = 10L;
    fault.point.solr15_parent_lookup = "explicit_resource";
    fault.point.resource = "/overseer/queue";
    assertFalse(fault.matches(Solr15ParentSelector.NATIVE, "shard-2", 0,
        "shard-2:0:task:9", 1, 10, null, "/live_nodes/other", null));
    assertFalse(fault.matches(Solr15ParentSelector.NATIVE, "shard-2", 0,
        "shard-2:0:task:8", 1, 10, null, "/overseer/queue", null));
    assertFalse(fault.matches(Solr15ParentSelector.NATIVE, "shard-2", 0,
        "shard-2:0:task:9", 1, 11, null, "/overseer/queue", null));
    assertEquals(true, fault.matches(Solr15ParentSelector.NATIVE, "shard-2", 0,
        "shard-2:0:task:9", 1, 10, null, "/overseer/queue", null));
  }
}
