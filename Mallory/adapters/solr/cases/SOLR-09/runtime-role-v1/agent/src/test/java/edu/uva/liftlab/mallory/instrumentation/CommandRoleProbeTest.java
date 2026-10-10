package edu.uva.liftlab.mallory.instrumentation;

import static org.junit.Assert.*;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.List;
import org.junit.Test;

public class CommandRoleProbeTest {
  @Test public void emitsPhysicalIdentityAtRoleBoundFault() throws Exception {
    File events = File.createTempFile("solr09-command-role-", ".jsonl");
    events.deleteOnExit();
    FaultPlan plan = new FaultPlan();
    FaultPlan.Fault fault = new FaultPlan.Fault();
    fault.fault_id = "solr09-role-test";
    fault.fault_type = "EXCEPTION";
    fault.exception_class = "java.util.concurrent.TimeoutException";
    fault.point = new FaultPlan.Point();
    fault.point.site = CommandRoleBindingRegistry.SITE;
    fault.point.role = CommandRoleBindingRegistry.ROLE;
    fault.point.role_ordinal = 1L;
    plan.faults.add(fault);
    Probe.install("solr09-command-role", events, plan);
    Probe.setNode("node2", 0);
    Probe.regionEnter(CommandRoleBindingRegistry.REGION);
    try {
      Probe.beforeDoor(CommandRoleBindingRegistry.SITE,
          "java.util.concurrent.TimeoutException");
      fail("selected role fault must throw");
    } catch (Throwable expected) {
      assertTrue(expected instanceof java.util.concurrent.TimeoutException);
    } finally {
      Probe.regionExit(CommandRoleBindingRegistry.REGION);
    }
    List<String> lines = Files.readAllLines(events.toPath(), StandardCharsets.UTF_8);
    JsonObject applied = null;
    for (String line : lines) {
      JsonObject row = new JsonParser().parse(line).getAsJsonObject();
      if ("FAULT_APPLIED".equals(row.get("type").getAsString())) applied = row;
    }
    assertNotNull(applied);
    assertEquals("node2", applied.get("node").getAsString());
    assertEquals("node2", applied.get("role_node").getAsString());
    assertEquals(0, applied.get("role_epoch").getAsInt());
    assertEquals(1, applied.get("role_ordinal").getAsInt());
    assertEquals(applied.get("occurrence").getAsString(),
        applied.get("role_source_occurrence").getAsString());
    assertEquals(CommandRoleBindingRegistry.REGION, applied.get("region").getAsString());
  }
}
