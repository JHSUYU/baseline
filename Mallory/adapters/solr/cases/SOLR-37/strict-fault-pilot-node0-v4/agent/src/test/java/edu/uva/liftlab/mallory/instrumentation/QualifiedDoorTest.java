package edu.uva.liftlab.mallory.instrumentation;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;
import org.junit.Test;

public final class QualifiedDoorTest {
  private static final String SITE = "solr37:qualified";
  private static final String REGION = "official:StateWatcher.refreshAndWatch";
  private static final String RESOURCE = "/collections/collection1/state.json";

  @Test public void injectsOnlyAtRegisteredExactReferenceAndResource() throws Exception {
    File trace = File.createTempFile("mallory-qualified", ".jsonl");
    FaultPlan plan = new FaultPlan();
    FaultPlan.Fault fault = new FaultPlan.Fault();
    fault.fault_id = "f1";
    fault.fault_type = "EXCEPTION";
    fault.exception_class = "java.io.IOException";
    fault.point = new FaultPlan.Point();
    fault.point.site = SITE;
    fault.point.node = "shard-4";
    fault.point.epoch = 0;
    fault.point.door_ordinal = 1L;
    fault.point.resource = RESOURCE;
    fault.point.region = REGION;
    fault.point.occurrence_kind = "watcher_region";
    plan.faults.add(fault);
    Probe.install("qualified", trace, plan);
    Object reader = new Object();
    Object other = new Object();
    Object published = new Object();
    Probe.registerNode(reader, "shard-4", 0);
    Probe.setNode("shard-4", 0);
    Probe.stateWriteExact(reader, "clusterState", published, "published");
    Probe.regionEnter(REGION);
    Probe.beforeQualifiedDoor(SITE, "java.io.IOException", other, published, RESOURCE, RESOURCE, REGION);
    Probe.beforeQualifiedDoor(SITE, "java.io.IOException", reader, new Object(), RESOURCE, RESOURCE, REGION);
    Probe.beforeQualifiedDoor(SITE, "java.io.IOException", reader, published,
        "/collections/other/state.json", RESOURCE, REGION);
    Probe.beforeQualifiedDoor(SITE, "java.io.IOException", reader, published, RESOURCE,
        RESOURCE, "different-region");
    try {
      Probe.beforeQualifiedDoor(SITE, "java.io.IOException", reader, published,
          RESOURCE, RESOURCE, REGION);
      throw new AssertionError("the qualified fault was not injected");
    } catch (Throwable expected) {
      assertTrue(expected instanceof IOException);
      assertTrue(expected.getMessage().contains("f1"));
    }
    Probe.regionExit(REGION);
    List<JsonObject> rows = new ArrayList<JsonObject>();
    for (String line : Files.readAllLines(trace.toPath(), StandardCharsets.UTF_8))
      rows.add(new JsonParser().parse(line).getAsJsonObject());
    List<JsonObject> qualified = new ArrayList<JsonObject>();
    for (JsonObject row : rows) {
      String type = row.get("type").getAsString();
      if (type.equals("DOOR_OBSERVED") || type.equals("FAULT_MATCHED")
          || type.equals("FAULT_APPLIED")) qualified.add(row);
    }
    assertEquals(3, qualified.size());
    assertEquals("DOOR_OBSERVED", qualified.get(0).get("type").getAsString());
    assertEquals("FAULT_MATCHED", qualified.get(1).get("type").getAsString());
    assertEquals("FAULT_APPLIED", qualified.get(2).get("type").getAsString());
    for (JsonObject row : qualified) {
      assertEquals(RESOURCE, row.get("resource").getAsString());
      assertEquals(REGION, row.get("region").getAsString());
      assertEquals("watcher_region", row.get("occurrence_kind").getAsString());
      assertEquals(1, row.get("door_ordinal").getAsLong());
      assertEquals(1, row.get("state_version").getAsLong());
      assertEquals(qualified.get(0).get("reader_ref").getAsString(),
          row.get("reader_ref").getAsString());
      assertEquals(qualified.get(0).get("occurrence").getAsString(),
          row.get("occurrence").getAsString());
    }
  }
}
