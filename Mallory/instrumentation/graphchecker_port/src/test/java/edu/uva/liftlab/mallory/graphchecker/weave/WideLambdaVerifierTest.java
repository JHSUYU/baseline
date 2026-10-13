package edu.uva.liftlab.mallory.graphchecker.weave;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotEquals;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.InputStream;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import org.junit.Test;

/** Regression for a Solr-style synthetic lambda with wide locals and catches. */
public final class WideLambdaVerifierTest {
    private static final String PREFIX =
            "edu.uva.liftlab.mallory.graphchecker.weave.fixture.";

    @Test public void wideLambdaLoadsAndClosesItsRegion() throws Throwable {
        Path work = Files.createTempDirectory("mallory-wide-lambda-");
        Path input = Files.createDirectories(work.resolve("original"));
        Path output = Files.createDirectories(work.resolve("woven"));
        copy(input, PREFIX + "FixtureWideLambda");
        copy(input, PREFIX + "FixtureWideLambdaJUnit");
        String clazz = PREFIX + "FixtureWideLambda";
        String manifest = "{\"regions\":[{\"clazz\":\"" + clazz
                + "\",\"method\":\"lambda$compute$0\",\"descriptor\":\"(JJ)J\","
                + "\"regionId\":\"wide-lambda-region\"}],"
                + "\"frames\":[{\"clazz\":\"" + clazz
                + "\",\"method\":\"lambda$compute$0\",\"descriptor\":\"(JJ)J\"}],"
                + "\"coverage\":[{\"clazz\":\"" + clazz
                + "\",\"method\":\"lambda$compute$0\",\"descriptor\":\"(JJ)J\","
                + "\"siteId\":\"wide-lambda-method\"}],"
                + "\"doors\":[{\"clazz\":\"" + clazz
                + "\",\"method\":\"lambda$compute$0\",\"descriptor\":\"(JJ)J\","
                + "\"line\":9,\"siteId\":\"wide-lambda-door\","
                + "\"callee\":\"<" + clazz
                + ": long add(long,long)>\",\"exceptionClass\":\"java.io.IOException\"}]}";
        Path sites = work.resolve("sites.json");
        Files.write(sites, manifest.getBytes(StandardCharsets.UTF_8));
        WeaveMain.weave(sites, input, output, System.getProperty("java.class.path"));

        Path trace = work.resolve("trace.jsonl");
        String previousTrace = System.getProperty("mallory.graphchecker.trace.file");
        ClassLoader prior = Thread.currentThread().getContextClassLoader();
        try (ChildFirst loader = new ChildFirst(output.toUri().toURL(), prior)) {
            System.setProperty("mallory.graphchecker.trace.file", trace.toString());
            Thread.currentThread().setContextClassLoader(loader);
            JUnitTrialRunner.main(new String[]{PREFIX + "FixtureWideLambdaJUnit",
                    "originalWideLambda"});
        } finally {
            Thread.currentThread().setContextClassLoader(prior);
            if (previousTrace == null) System.clearProperty("mallory.graphchecker.trace.file");
            else System.setProperty("mallory.graphchecker.trace.file", previousTrace);
        }

        Map<String, Integer> kinds = new HashMap<>();
        for (String line : Files.readAllLines(trace, StandardCharsets.UTF_8)) {
            JsonObject row = JsonParser.parseString(line).getAsJsonObject();
            String kind = row.get("kind").getAsString();
            kinds.merge(kind, 1, Integer::sum);
            if ("GAP".equals(kind)) {
                String gap = row.get("gapKind").getAsString();
                assertNotEquals("CALL_UNBALANCED", gap);
                assertNotEquals("REGION_UNBALANCED", gap);
            }
        }
        assertEquals(Integer.valueOf(1), kinds.get("ACTIVATION"));
        assertEquals(Integer.valueOf(1), kinds.get("FAULT_DOOR"));
        assertEquals(Integer.valueOf(1), kinds.get("COVERAGE"));
    }

    @Test public void originalCatchReadsLiveIntAfterSyntheticCallHandler() throws Throwable {
        Path work = Files.createTempDirectory("mallory-live-int-catch-");
        Path input = Files.createDirectories(work.resolve("original"));
        Path output = Files.createDirectories(work.resolve("woven"));
        copy(input, PREFIX + "FixtureCatchLiveInt");
        copy(input, PREFIX + "FixtureCatchLiveIntJUnit");
        String clazz = PREFIX + "FixtureCatchLiveInt";
        String method = "\"clazz\":\"" + clazz
                + "\",\"method\":\"parse\",\"descriptor\":\"(Ljava/lang/String;)I\"";
        String manifest = "{\"regions\":[{" + method
                + ",\"regionId\":\"catch-live-int-region\"}],"
                + "\"frames\":[{" + method + "}],"
                + "\"coverage\":[{" + method
                + ",\"siteId\":\"catch-live-int-method\"}]}";
        Path sites = work.resolve("sites.json");
        Files.write(sites, manifest.getBytes(StandardCharsets.UTF_8));
        WeaveMain.weave(sites, input, output, System.getProperty("java.class.path"));

        Path trace = work.resolve("trace.jsonl");
        String previousTrace = System.getProperty("mallory.graphchecker.trace.file");
        ClassLoader prior = Thread.currentThread().getContextClassLoader();
        try (ChildFirst loader = new ChildFirst(output.toUri().toURL(), prior)) {
            System.setProperty("mallory.graphchecker.trace.file", trace.toString());
            Thread.currentThread().setContextClassLoader(loader);
            JUnitTrialRunner.main(new String[]{PREFIX + "FixtureCatchLiveIntJUnit",
                    "originalCatchReadsLiveInt"});
        } finally {
            Thread.currentThread().setContextClassLoader(prior);
            if (previousTrace == null) System.clearProperty("mallory.graphchecker.trace.file");
            else System.setProperty("mallory.graphchecker.trace.file", previousTrace);
        }
    }

    private static void copy(Path input, String clazz) throws Exception {
        String name = clazz.replace('.', '/') + ".class";
        Path target = input.resolve(name);
        Files.createDirectories(target.getParent());
        try (InputStream source = WideLambdaVerifierTest.class.getClassLoader()
                .getResourceAsStream(name)) {
            if (source == null) throw new IllegalStateException("missing fixture " + name);
            Files.copy(source, target);
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
