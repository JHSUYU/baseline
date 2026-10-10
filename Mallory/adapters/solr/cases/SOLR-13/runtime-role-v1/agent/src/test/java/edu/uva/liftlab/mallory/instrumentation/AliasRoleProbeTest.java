package edu.uva.liftlab.mallory.instrumentation;

import static org.junit.Assert.*;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.List;
import org.junit.Test;

public class AliasRoleProbeTest {
  @Test public void emitsPhysicalIdentityAtRoleBoundFault() throws Exception {
    File events = File.createTempFile("solr13-alias-role-", ".jsonl");
    events.deleteOnExit();
    FaultPlan plan = new FaultPlan();
    FaultPlan.Fault fault = new FaultPlan.Fault();
    fault.fault_id = "solr13-role-test";
    fault.fault_type = "EXCEPTION";
    fault.exception_class = "java.util.concurrent.TimeoutException";
    fault.point = new FaultPlan.Point();
    fault.point.site = AliasRoleBindingRegistry.SITE;
    fault.point.role = AliasRoleBindingRegistry.ROLE;
    fault.point.role_ordinal = 1L;
    plan.faults.add(fault);
    Probe.install("solr13-alias-role", events, plan);
    Probe.setNode("node2", 0);
    Probe.regionEnter(AliasRoleBindingRegistry.PARENT_REGION);
    Probe.regionEnter(AliasRoleBindingRegistry.REGION);
    try {
      Probe.beforeDoor(AliasRoleBindingRegistry.SITE,
          "java.util.concurrent.TimeoutException");
      fail("selected role fault must throw");
    } catch (Throwable expected) {
      assertTrue(expected instanceof java.util.concurrent.TimeoutException);
    } finally {
      Probe.regionExit(AliasRoleBindingRegistry.REGION);
      Probe.regionExit(AliasRoleBindingRegistry.PARENT_REGION);
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
    assertTrue(applied.get("role_parent_occurrence").getAsString()
        .contains(AliasRoleBindingRegistry.PARENT_REGION));
    assertEquals(AliasRoleBindingRegistry.REGION, applied.get("region").getAsString());
  }
}
