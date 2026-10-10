package edu.uva.liftlab.mallory.instrumentation;

import static org.junit.Assert.*;
import org.junit.Test;

public class AliasRoleBindingRegistryTest {
  @Test public void bindsOnlyExactCommandAndNamedActor() {
    AliasRoleBindingRegistry registry = new AliasRoleBindingRegistry();
    String region = AliasRoleBindingRegistry.REGION;
    String parent = AliasRoleBindingRegistry.PARENT_REGION;
    String occurrence2 = "node2:0:" + region + ":task:1:1";
    String occurrence4 = "node4:0:" + region + ":task:2:1";
    String parent2 = "node2:0:" + parent + ":task:1:1";
    String parent4 = "node4:0:" + parent + ":task:2:1";
    assertFalse(registry.atDoor(AliasRoleBindingRegistry.SITE, "unknown", 0,
        region, occurrence2, parent2).bound);
    assertFalse(registry.atDoor(AliasRoleBindingRegistry.SITE, "node2", 0,
        "unrelated", occurrence2, parent2).bound);
    assertFalse(registry.atDoor(AliasRoleBindingRegistry.SITE, "node4", 0,
        region, occurrence2, parent2).bound);
    assertFalse(registry.atDoor(AliasRoleBindingRegistry.SITE, "node2", 0,
        region, occurrence2, null).bound);
    AliasRoleBindingRegistry.Resolution first = registry.atDoor(
        AliasRoleBindingRegistry.SITE, "node2", 0, region, occurrence2, parent2);
    AliasRoleBindingRegistry.Resolution second = registry.atDoor(
        AliasRoleBindingRegistry.SITE, "node4", 0, region, occurrence4, parent4);
    assertTrue(first.bound);
    assertEquals(1, first.roleOrdinal);
    assertEquals("node2", first.physicalNode);
    assertEquals(occurrence2, first.sourceOccurrence);
    assertEquals(parent2, first.parentOccurrence);
    assertTrue(second.bound);
    assertEquals(2, second.roleOrdinal);
    assertEquals("node4", second.physicalNode);
  }

  @Test public void rolePlanNeedsRuntimeResolution() {
    FaultPlan.Fault fault = new FaultPlan.Fault();
    fault.point = new FaultPlan.Point();
    fault.point.site = AliasRoleBindingRegistry.SITE;
    fault.point.role = AliasRoleBindingRegistry.ROLE;
    fault.point.role_ordinal = 1L;
    assertFalse(fault.matches(AliasRoleBindingRegistry.SITE, "node2", 0,
        "anything", 1, 1));
    assertTrue(fault.matches(AliasRoleBindingRegistry.SITE, "node4", 0,
        "anything", 1, 1, AliasRoleBindingRegistry.ROLE, 1));
    assertFalse(fault.matches(AliasRoleBindingRegistry.SITE, "node4", 0,
        "anything", 1, 1, AliasRoleBindingRegistry.ROLE, 2));
  }
}
