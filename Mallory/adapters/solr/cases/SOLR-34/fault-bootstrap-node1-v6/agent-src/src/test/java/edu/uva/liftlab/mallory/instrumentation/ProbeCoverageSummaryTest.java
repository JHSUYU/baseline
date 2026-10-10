package edu.uva.liftlab.mallory.instrumentation;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.File;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.Test;
import static org.junit.Assert.*;

public final class ProbeCoverageSummaryTest {
  @Test public void keepsCoverageInEachOccurrenceAndEveryTargetCheck() throws Exception {
    File eventsFile = File.createTempFile("mallory-coverage-occurrences", ".jsonl");
    Probe.install("coverage-occurrences", eventsFile, new FaultPlan());
    try (Probe.NodeScope node = Probe.withNode("solr-1", 0)) {
      Probe.regionEnter("outside-target-closure");
      Probe.branch("C#shared", true, false);
      Probe.method("C#work");
      Probe.regionExit("outside-target-closure");
      Probe.regionEnter("inside-target-closure");
      for (int i = 0; i < 3; i++) Probe.branch("C#shared", true, true);
      Probe.method("C#work");
      Probe.regionExit("inside-target-closure");
    }
    Probe.flushCoverage();
    List<JsonObject> events = readEvents(eventsFile);
    assertEquals(3, countType(events, "TARGET_CHECK"));
    assertEquals(0, countType(events, "BRANCH"));
    assertEquals(0, countType(events, "METHOD"));
    List<JsonObject> summaries = byType(events, "COVERAGE_SUMMARY");
    assertEquals(2, summaries.size());
    assertNotEquals(summaries.get(0).get("occurrence"), summaries.get(1).get("occurrence"));
    for (JsonObject summary : summaries) {
      assertEquals("solr-1", summary.get("node").getAsString());
      assertEquals(Arrays.asList("C#shared:TAKEN", "C#work"), coverageIds(events, summary));
    }
  }

  @Test public void concurrentHitsKeepEachThreadRootOccurrence() throws Exception {
    File eventsFile = File.createTempFile("mallory-coverage-concurrent", ".jsonl");
    Probe.install("coverage-concurrent", eventsFile, new FaultPlan());
    int workers = 8;
    int iterations = 100;
    CountDownLatch ready = new CountDownLatch(workers);
    CountDownLatch start = new CountDownLatch(1);
    CountDownLatch done = new CountDownLatch(workers);
    AtomicReference<Throwable> failure = new AtomicReference<Throwable>();
    for (int index = 0; index < workers; index++) {
      Thread worker = new Thread(new Runnable() {
        @Override public void run() {
          try (Probe.NodeScope node = Probe.withNode("solr-2", 1)) {
            ready.countDown();
            start.await();
            for (int i = 0; i < iterations; i++) {
              Probe.method("C#work");
              Probe.branch("C#guard", true, true);
              Probe.branchCase("C#switch", "CASE:1", false);
            }
          } catch (Throwable error) {
            failure.compareAndSet(null, error);
          } finally {
            done.countDown();
          }
        }
      });
      worker.start();
    }
    ready.await();
    start.countDown();
    done.await();
    if (failure.get() != null) throw new AssertionError(failure.get());
    Probe.flushCoverage();
    List<JsonObject> events = readEvents(eventsFile);
    assertEquals(workers * iterations, countType(events, "TARGET_CHECK"));
    List<JsonObject> summaries = byType(events, "COVERAGE_SUMMARY");
    assertEquals(workers, summaries.size());
    java.util.Set<String> rootOccurrences = new java.util.HashSet<String>();
    for (JsonObject summary : summaries) {
      assertEquals(Arrays.asList("C#guard:TAKEN", "C#switch:CASE:1", "C#work"),
          coverageIds(events, summary));
      String occurrence = summary.get("occurrence").getAsString();
      assertTrue(occurrence.startsWith("unscoped:solr-2:1:root:thread:"));
      rootOccurrences.add(occurrence);
    }
    assertEquals(workers, rootOccurrences.size());
    assertEquals(3, countType(events, "COVERAGE_DEF"));
    int firstSummary = events.indexOf(summaries.get(0));
    for (JsonObject definition : byType(events, "COVERAGE_DEF"))
      assertTrue(events.indexOf(definition) < firstSummary);
    assertEquals(0, countType(events, "TRACE_TRUNCATED"));
  }

  @Test public void newInstallationStartsFreshCoverageSet() throws Exception {
    File first = File.createTempFile("mallory-coverage-first", ".jsonl");
    Probe.install("coverage-first", first, new FaultPlan());
    Probe.method("C#work");
    Probe.flushCoverage();
    File second = File.createTempFile("mallory-coverage-second", ".jsonl");
    Probe.install("coverage-second", second, new FaultPlan());
    Probe.method("C#work");
    Probe.flushCoverage();
    assertEquals(1, countType(readEvents(first), "COVERAGE_SUMMARY"));
    assertEquals(1, countType(readEvents(second), "COVERAGE_SUMMARY"));
  }

  @Test public void refusesReferenceOverflowWithoutEmittingAConflictingDefinition() throws Exception {
    File eventsFile = File.createTempFile("mallory-coverage-overflow", ".jsonl");
    Probe.install("coverage-overflow", eventsFile, new FaultPlan());
    Field field = Probe.class.getDeclaredField("COVERAGE_ID_SEQUENCE");
    field.setAccessible(true);
    AtomicInteger sequence = (AtomicInteger) field.get(null);
    try {
      sequence.set(Integer.MAX_VALUE);
      try {
        Probe.method("C#overflow");
        fail("The compact coverage reference must not wrap into a reused value");
      } catch (IllegalStateException expected) {
        assertTrue(expected.getMessage().contains("exhausted"));
      }
      Probe.flushCoverage();
      assertEquals(0, countType(readEvents(eventsFile), "COVERAGE_DEF"));
      assertEquals(0, countType(readEvents(eventsFile), "COVERAGE_SUMMARY"));
    } finally {
      sequence.set(0);
    }
  }

  private static List<String> coverageIds(List<JsonObject> events, JsonObject summary) {
    Map<Integer, String> definitions = new HashMap<Integer, String>();
    for (JsonObject event : byType(events, "COVERAGE_DEF"))
      definitions.put(event.get("coverage_ref").getAsInt(), event.get("coverage_id").getAsString());
    List<String> ids = new ArrayList<String>();
    for (JsonElement ref : summary.getAsJsonArray("coverage_refs"))
      ids.add(definitions.get(ref.getAsInt()));
    java.util.Collections.sort(ids);
    return ids;
  }

  private static List<JsonObject> readEvents(File path) throws Exception {
    List<JsonObject> events = new ArrayList<JsonObject>();
    for (String line : Files.readAllLines(path.toPath(), StandardCharsets.UTF_8))
      events.add(new JsonParser().parse(line).getAsJsonObject());
    return events;
  }

  private static int countType(List<JsonObject> events, String type) {
    return byType(events, type).size();
  }

  private static List<JsonObject> byType(List<JsonObject> events, String type) {
    List<JsonObject> matched = new ArrayList<JsonObject>();
    for (JsonObject event : events)
      if (type.equals(event.get("type").getAsString())) matched.add(event);
    return matched;
  }
}
