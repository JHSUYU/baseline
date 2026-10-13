package edu.uva.liftlab.mallory.graphchecker.weave;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;
import edu.uva.liftlab.mallory.instrumentation.Probe;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.IOException;
import java.io.InputStream;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import org.junit.Test;

public final class OriginalJUnitWeaveSmokeTest {
    private static final String PREFIX =
            "edu.uva.liftlab.mallory.graphchecker.weave.fixture.";

    @Test public void originalJUnitRunsWithSelectedRegionAndBothBranchOutcomes()
            throws Throwable {
        Path work = Files.createTempDirectory("mallory-gc-weave-");
        Path input = Files.createDirectories(work.resolve("original"));
        Path output = Files.createDirectories(work.resolve("woven"));
        copyClass(input, PREFIX + "FixtureOperation");
        copyClass(input, PREFIX + "FixtureJUnit");
        copyClass(input, PREFIX + "FixtureServer");
        copyClass(input, PREFIX + "FixtureServerJUnit");
        copyClass(input, PREFIX + "FixtureUnregisteredJUnit");
        copyClass(input, PREFIX + "FixtureFirstCall");
        copyClass(input, PREFIX + "FixtureFirstCallJUnit");
        copyClass(input, PREFIX + "FixtureScopeBoundary");
        copyClass(input, PREFIX + "FixtureScopeBoundaryJUnit");
        Path manifest = work.resolve("sites.json");
        Files.write(manifest, ("{\"faultController\":\"MALLORY_PROBE\",\"regions\":[{\"clazz\":\"" + PREFIX
                + "FixtureOperation\",\"method\":\"classify\",\"descriptor\":\"(I)I\","
                + "\"regionId\":\"fixture-region\"},"
                + "{\"clazz\":\"" + PREFIX
                + "FixtureServer\",\"method\":\"isReady\",\"descriptor\":\"(Z)Z\","
                + "\"regionId\":\"server-region\",\"sourceOwner\":\"THIS\"},"
                + "{\"clazz\":\"" + PREFIX
                + "FixtureFirstCall\",\"method\":\"callFirst\",\"descriptor\":\"()I\","
                + "\"regionId\":\"first-call-region\"},"
                + "{\"clazz\":\"" + PREFIX
                + "FixtureScopeBoundary\",\"method\":\"run\",\"descriptor\":\"()I\","
                + "\"regionId\":\"scope-boundary-region\"}],"
                + "\"targets\":[{\"clazz\":\"" + PREFIX
                + "FixtureOperation\",\"method\":\"classify\",\"descriptor\":\"(I)I\","
                + "\"line\":5,\"kind\":\"BRANCH\",\"siteId\":\"fixture-check\"},"
                + "{\"clazz\":\"" + PREFIX
                + "FixtureOperation\",\"method\":\"classify\",\"descriptor\":\"(I)I\","
                + "\"line\":6,\"kind\":\"THROW\",\"siteId\":\"fixture-throw\","
                + "\"exceptionClass\":\"java.lang.IllegalStateException\"},"
                + "{\"clazz\":\"" + PREFIX
                + "FixtureServer\",\"method\":\"isReady\",\"descriptor\":\"(Z)Z\","
                + "\"line\":5,\"kind\":\"BRANCH\",\"siteId\":\"fixture-server-check\"},"
                + "{\"clazz\":\"" + PREFIX
                + "FixtureOperation\",\"method\":\"choose\",\"descriptor\":\"(I)I\","
                + "\"line\":12,\"kind\":\"SWITCH\",\"siteId\":\"fixture-switch\"}],"
                + "\"coverage\":[{\"clazz\":\"" + PREFIX
                + "FixtureOperation\",\"method\":\"classify\",\"descriptor\":\"(I)I\","
                + "\"siteId\":\"fixture-method\"},{\"clazz\":\"" + PREFIX
                + "FixtureOperation\",\"method\":\"classify\",\"descriptor\":\"(I)I\","
                + "\"line\":5,\"siteId\":\"fixture-branch-coverage\"},"
                + "{\"clazz\":\"" + PREFIX
                + "FixtureFirstCall\",\"method\":\"callFirst\",\"descriptor\":\"()I\","
                + "\"siteId\":\"first-call-method\"},"
                + "{\"clazz\":\"" + PREFIX
                + "FixtureScopeBoundary\",\"method\":\"run\",\"descriptor\":\"()I\","
                + "\"siteId\":\"scope-boundary-method\"}],"
                + "\"frames\":[{\"clazz\":\"" + PREFIX
                + "FixtureJUnit\",\"method\":\"originalTestMethod\",\"descriptor\":\"()V\"},"
                + "{\"clazz\":\"" + PREFIX
                + "FixtureOperation\",\"method\":\"classify\",\"descriptor\":\"(I)I\"},"
                + "{\"clazz\":\"" + PREFIX
                + "FixtureFirstCall\",\"method\":\"callFirst\",\"descriptor\":\"()I\"},"
                + "{\"clazz\":\"" + PREFIX
                + "FixtureScopeBoundary\",\"method\":\"run\",\"descriptor\":\"()I\"}],"
                + "\"doors\":[{\"clazz\":\"" + PREFIX
                + "FixtureOperation\",\"method\":\"classify\",\"descriptor\":\"(I)I\","
                + "\"line\":6,\"siteId\":\"fixture-door\","
                + "\"callee\":\"<java.lang.IllegalStateException: void <init>(java.lang.String)>\","
                + "\"exceptionClass\":\"java.io.IOException\"}]}"
                ).getBytes(StandardCharsets.UTF_8));
        WeaveMain.weave(manifest, input, output, System.getProperty("java.class.path"));

        Path trace = work.resolve("trace.jsonl");
        System.setProperty("mallory.graphchecker.trace.file", trace.toString());
        ClassLoader prior = Thread.currentThread().getContextClassLoader();
        int firstRunLines, secondRunLines, thirdRunLines, fourthRunLines,
                fifthRunLines;
        try (ChildFirst loader = new ChildFirst(output.toUri().toURL(), prior)) {
            Thread.currentThread().setContextClassLoader(loader);
            JUnitTrialRunner.main(new String[]{PREFIX + "FixtureJUnit", "originalTestMethod"});
            firstRunLines = Files.readAllLines(trace, StandardCharsets.UTF_8).size();
            Probe.inject = true;
            try {
                JUnitTrialRunner.main(new String[]{PREFIX + "FixtureJUnit", "originalTestMethod"});
                throw new AssertionError("injected IOException should leave original JUnit failed");
            } catch (java.io.IOException expected) {
                assertEquals("synthetic transport fault", expected.getMessage());
            } finally {
                Probe.inject = false;
            }
            secondRunLines = Files.readAllLines(trace, StandardCharsets.UTF_8).size();
            JUnitTrialRunner.main(new String[]{PREFIX + "FixtureServerJUnit", "originalServerTest"});
            thirdRunLines = Files.readAllLines(trace, StandardCharsets.UTF_8).size();
            JUnitTrialRunner.main(new String[]{PREFIX + "FixtureUnregisteredJUnit", "missingSourceBinding"});
            fourthRunLines = Files.readAllLines(trace, StandardCharsets.UTF_8).size();
            JUnitTrialRunner.main(new String[]{PREFIX + "FixtureFirstCallJUnit", "originalFirstCall"});
            fifthRunLines = Files.readAllLines(trace, StandardCharsets.UTF_8).size();
            JUnitTrialRunner.main(new String[]{PREFIX + "FixtureScopeBoundaryJUnit",
                    "originalScopeBoundary"});
        } finally {
            Thread.currentThread().setContextClassLoader(prior);
        }
        List<String> lines = Files.readAllLines(trace, StandardCharsets.UTF_8);
        int activations = 0, hits = 0, checksTrue = 0,
                checksFalse = 0, throwsSeen = 0, doors = 0;
        int switchCase = 0, switchDefault = 0;
        int coveredTrue = 0, coveredFalse = 0;
        for (String line : lines.subList(0, firstRunLines)) {
            JsonObject row = JsonParser.parseString(line).getAsJsonObject();
            String kind = row.get("kind").getAsString();
            if ("GAP".equals(kind)) {
                String gap = row.get("gapKind").getAsString();
                assertTrue("balanced healthy JUnit trace: " + gap,
                        !"CALL_UNBALANCED".equals(gap)
                                && !"REGION_UNBALANCED".equals(gap));
            }
            if ("ACTIVATION".equals(kind)) activations++;
            if ("COVERAGE".equals(kind)) {
                hits++;
                if (row.has("branchSiteId")
                        && "fixture-branch-coverage".equals(row.get("branchSiteId").getAsString())) {
                    if (row.get("outcome").getAsBoolean()) coveredTrue++;
                    else coveredFalse++;
                }
            }
            if ("TARGET_THROW".equals(kind)) throwsSeen++;
            if ("FAULT_DOOR".equals(kind)) {
                doors++;
                assertTrue(row.has("occurrenceId"));
            }
            if ("TARGET_CHECK".equals(kind)) {
                if ("TRUE".equals(row.get("outcome").getAsString())) checksTrue++;
                if ("FALSE".equals(row.get("outcome").getAsString())) checksFalse++;
                if ("CASE:1".equals(row.get("outcome").getAsString())) switchCase++;
                if ("DEFAULT".equals(row.get("outcome").getAsString())) switchDefault++;
                assertTrue(row.has("occurrenceId"));
            }
        }
        assertEquals(2, activations);
        assertEquals(4, hits);
        assertEquals(1, coveredTrue);
        assertEquals(1, coveredFalse);
        assertEquals(1, checksTrue);
        assertEquals(1, checksFalse);
        assertEquals(1, throwsSeen);
        assertEquals(1, switchCase);
        assertEquals(1, switchDefault);
        assertEquals(1, doors);
        assertEquals("fixture-door:java.io.IOException", Probe.observed);
        int secondRunDoors = 0, secondRunThrows = 0;
        for (String line : lines.subList(firstRunLines, secondRunLines)) {
            JsonObject row = JsonParser.parseString(line).getAsJsonObject();
            String kind = row.get("kind").getAsString();
            if ("FAULT_DOOR".equals(kind)) secondRunDoors++;
            if ("TARGET_THROW".equals(kind)) secondRunThrows++;
        }
        assertEquals(1, secondRunDoors);
        assertEquals(0, secondRunThrows);
        int serverChecks = 0;
        for (String line : lines.subList(secondRunLines, thirdRunLines)) {
            JsonObject row = JsonParser.parseString(line).getAsJsonObject();
            if (!"TARGET_CHECK".equals(row.get("kind").getAsString())
                    || !"fixture-server-check".equals(row.get("siteId").getAsString())) continue;
            serverChecks++;
            assertEquals("nn-1#epoch0", row.get("node").getAsString());
        }
        assertEquals(1, serverChecks);
        int unboundChecks = 0, bindingGaps = 0;
        for (String line : lines.subList(thirdRunLines, fourthRunLines)) {
            JsonObject row = JsonParser.parseString(line).getAsJsonObject();
            String kind = row.get("kind").getAsString();
            if ("GAP".equals(kind)) {
                assertTrue("rejected owner must not produce a fake region exit",
                        !"REGION_UNBALANCED".equals(row.get("gapKind").getAsString()));
            }
            if ("TARGET_CHECK".equals(kind)
                    && "fixture-server-check".equals(row.get("siteId").getAsString())) {
                unboundChecks++;
                assertTrue(!row.has("occurrenceId"));
            }
            if ("GAP".equals(kind)
                    && "UNREGISTERED_SOURCE".equals(row.get("gapKind").getAsString())) {
                bindingGaps++;
            }
        }
        assertEquals(1, unboundChecks);
        assertTrue(bindingGaps >= 1);
        int firstCallActivation = 0;
        for (String line : lines.subList(fourthRunLines, fifthRunLines)) {
            JsonObject row = JsonParser.parseString(line).getAsJsonObject();
            String kind = row.get("kind").getAsString();
            if ("GAP".equals(kind)) {
                String gap = row.get("gapKind").getAsString();
                assertTrue("first invocation must be inside a balanced region: " + gap,
                        !"CALL_UNBALANCED".equals(gap)
                                && !"REGION_UNBALANCED".equals(gap));
            }
            if ("ACTIVATION".equals(kind)
                    && "first-call-region".equals(row.get("regionId").getAsString())) {
                firstCallActivation++;
            }
        }
        assertEquals(1, firstCallActivation);
        int scopeBoundaryActivation = 0;
        for (String line : lines.subList(fifthRunLines, lines.size())) {
            JsonObject row = JsonParser.parseString(line).getAsJsonObject();
            String kind = row.get("kind").getAsString();
            if ("GAP".equals(kind)) {
                String gap = row.get("gapKind").getAsString();
                assertTrue("scope boundary must balance call receipts: " + gap,
                        !"CALL_UNBALANCED".equals(gap)
                                && !"REGION_UNBALANCED".equals(gap));
            }
            if ("ACTIVATION".equals(kind) && "scope-boundary-region".equals(
                    row.get("regionId").getAsString())) scopeBoundaryActivation++;
        }
        assertEquals(1, scopeBoundaryActivation);
    }

    private static void copyClass(Path input, String className) throws IOException {
        String relative = className.replace('.', '/') + ".class";
        Path destination = input.resolve(relative);
        Files.createDirectories(destination.getParent());
        try (InputStream stream = OriginalJUnitWeaveSmokeTest.class.getClassLoader()
                .getResourceAsStream(relative)) {
            if (stream == null) throw new IOException("missing class " + relative);
            Files.copy(stream, destination);
        }
    }

    private static final class ChildFirst extends URLClassLoader {
        ChildFirst(URL url, ClassLoader parent) { super(new URL[]{url}, parent); }

        @Override protected synchronized Class<?> loadClass(String name, boolean resolve)
                throws ClassNotFoundException {
            if (!name.startsWith(PREFIX)) return super.loadClass(name, resolve);
            Class<?> loaded = findLoadedClass(name);
            if (loaded == null) loaded = findClass(name);
            if (resolve) resolveClass(loaded);
            return loaded;
        }
    }
}
