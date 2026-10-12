package edu.uva.liftlab.mallory.instrumentation;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.Test;

public class FaultPlanRelativeTest {
  @Test public void laterFaultWaitsForSameNodeAndRelativeHit() throws Exception {
    Path file = Files.createTempFile("mallory-relative-plan-", ".json");
    try {
      Files.write(file, ("{\"schema_version\":1,\"faults\":["
          + "{\"point\":{\"site\":\"unload\"}},"
          + "{\"point\":{\"site\":\"getChildren\",\"after_fault\":0,"
          + "\"same_node_as\":0,\"relative_hit\":1}},"
          + "{\"point\":{\"site\":\"getData\",\"after_fault\":1,"
          + "\"same_node_as\":0,\"relative_hit\":2}}]}")
          .getBytes(StandardCharsets.UTF_8));
      FaultPlan plan = FaultPlan.load(file.toFile());
      assertFalse(plan.matches(1, "getChildren", "node1", 0, "a", 1, 1));
      assertTrue(plan.matches(0, "unload", "node3", 0, "a", 1, 1));
      plan.faults.get(0).markApplied("node3", 0);
      assertFalse(plan.matches(1, "getChildren", "node2", 0, "a", 1, 1));
      assertTrue(plan.matches(1, "getChildren", "node3", 0, "a", 1, 1));
      plan.faults.get(1).markApplied("node3", 0);
      assertFalse(plan.matches(2, "getData", "node3", 0, "a", 1, 1));
      assertFalse(plan.matches(2, "getData", "node3", 1, "a", 1, 1));
      assertTrue(plan.matches(2, "getData", "node3", 0, "a", 2, 2));
    } finally {
      Files.deleteIfExists(file);
    }
  }
}
