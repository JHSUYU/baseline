package edu.uva.liftlab.mallory.instrumentation;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;
import org.junit.Test;

public final class ExactReferenceStateTest {
  @Test public void exactReferenceRequiresTheActualLastPublishedObject() throws Exception {
    File trace = File.createTempFile("mallory-exact-state", ".jsonl");
    Probe.install("exact", trace, new FaultPlan());
    Object owner = new Object();
    Object otherOwner = new Object();
    Object first = new Object();
    Object second = new Object();
    Probe.stateWriteExact(owner, "collection", first, "publication-1");
    Probe.stateReadExact(owner, "collection", first, "matched-1");
    Probe.stateReadExact(owner, "collection", second, "wrong-value");
    Probe.stateReadExact(otherOwner, "collection", first, "wrong-owner");
    Probe.stateReadExact(owner, "other", first, "wrong-key");
    Probe.stateWriteExact(owner, "collection", second, "publication-2");
    Probe.stateReadExact(owner, "collection", first, "stale-value");
    Probe.stateReadExact(owner, "collection", second, "matched-2");

    List<JsonObject> rows = new ArrayList<JsonObject>();
    for (String line : Files.readAllLines(trace.toPath(), StandardCharsets.UTF_8))
      rows.add(new JsonParser().parse(line).getAsJsonObject());
    assertEquals(4, rows.size());
    assertEquals("STATE_WRITE", rows.get(0).get("type").getAsString());
    assertEquals("STATE_READ", rows.get(1).get("type").getAsString());
    assertEquals("STATE_WRITE", rows.get(2).get("type").getAsString());
    assertEquals("STATE_READ", rows.get(3).get("type").getAsString());
    for (JsonObject row : rows)
      assertEquals("exact", row.get("version_confidence").getAsString());
    assertEquals(rows.get(0).get("version").getAsLong(),
        rows.get(1).get("version").getAsLong());
    assertEquals(rows.get(2).get("version").getAsLong(),
        rows.get(3).get("version").getAsLong());
    assertTrue(rows.get(2).get("version").getAsLong() >
        rows.get(0).get("version").getAsLong());
    assertFalse(rows.get(0).get("object").getAsString().isEmpty());
  }
}
