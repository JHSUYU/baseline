package edu.uva.liftlab.mallory.instrumentation;

import static org.junit.Assert.*;
import org.junit.Test;

public class CommandRoleBindingRegistryTest {
  @Test public void bindsOnlyExactCommandAndNamedActor() {
    CommandRoleBindingRegistry registry = new CommandRoleBindingRegistry();
    String region = CommandRoleBindingRegistry.REGION;
    String occurrence2 = "node2:0:" + region + ":task:1:1";
    String occurrence4 = "node4:0:" + region + ":task:2:1";
    assertFalse(registry.atDoor(CommandRoleBindingRegistry.SITE, "unknown", 0,
        region, occurrence2).bound);
    assertFalse(registry.atDoor(CommandRoleBindingRegistry.SITE, "node2", 0,
        "unrelated", occurrence2).bound);
    assertFalse(registry.atDoor(CommandRoleBindingRegistry.SITE, "node4", 0,
        region, occurrence2).bound);
    CommandRoleBindingRegistry.Resolution first = registry.atDoor(
        CommandRoleBindingRegistry.SITE, "node2", 0, region, occurrence2);
    CommandRoleBindingRegistry.Resolution second = registry.atDoor(
        CommandRoleBindingRegistry.SITE, "node4", 0, region, occurrence4);
    assertTrue(first.bound);
    assertEquals(1, first.roleOrdinal);
    assertEquals("node2", first.physicalNode);
    assertEquals(occurrence2, first.sourceOccurrence);
    assertTrue(second.bound);
    assertEquals(2, second.roleOrdinal);
    assertEquals("node4", second.physicalNode);
  }

  @Test public void rolePlanNeedsRuntimeResolution() {
    FaultPlan.Fault fault = new FaultPlan.Fault();
    fault.point = new FaultPlan.Point();
    fault.point.site = CommandRoleBindingRegistry.SITE;
    fault.point.role = CommandRoleBindingRegistry.ROLE;
    fault.point.role_ordinal = 1L;
    assertFalse(fault.matches(CommandRoleBindingRegistry.SITE, "node2", 0,
        "anything", 1, 1));
    assertTrue(fault.matches(CommandRoleBindingRegistry.SITE, "node4", 0,
        "anything", 1, 1, CommandRoleBindingRegistry.ROLE, 1));
    assertFalse(fault.matches(CommandRoleBindingRegistry.SITE, "node4", 0,
        "anything", 1, 1, CommandRoleBindingRegistry.ROLE, 2));
  }
}
