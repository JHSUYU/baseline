package edu.uva.liftlab.mallory.graphchecker.weave;

import static org.junit.Assert.assertEquals;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.InputStream;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.Test;

/** A thrown factory return is attributed to the selected call only on the actual throw. */
public final class CallThrowFactoryWeaveTest {
    private static final String PREFIX =
            "edu.uva.liftlab.mallory.graphchecker.weave.fixture.";

    @Test public void factoryReturnHasOneExactTargetThrow() throws Throwable {
        Path work = Files.createTempDirectory("mallory-factory-throw-");
        Path input = Files.createDirectories(work.resolve("original"));
        Path output = Files.createDirectories(work.resolve("woven"));
        copy(input, PREFIX + "FixtureCallThrow");
        copy(input, PREFIX + "FixtureCallThrowJUnit");
        String clazz = PREFIX + "FixtureCallThrow";
        String manifest = "{\"regions\":[{\"clazz\":\"" + clazz
                + "\",\"method\":\"factory\",\"descriptor\":\"(Z)I\","
                + "\"regionId\":\"factory-region\"}],"
                + "\"targets\":[{\"clazz\":\"" + clazz
                + "\",\"method\":\"factory\",\"descriptor\":\"(Z)I\","
                + "\"line\":5,\"kind\":\"CALL_THROW\","
                + "\"siteId\":\"factory-call\","
                + "\"callee\":\"<" + clazz
                + ": java.lang.IllegalStateException makeFailure()>\","
                + "\"exceptionClass\":\"java.lang.IllegalStateException\"}]}";
        Path sites = work.resolve("sites.json");
        Files.write(sites, manifest.getBytes(StandardCharsets.UTF_8));
        WeaveMain.weave(sites, input, output, System.getProperty("java.class.path"));
        Path trace = work.resolve("trace.jsonl");
        String previousTrace = System.getProperty("mallory.graphchecker.trace.file");
        ClassLoader prior = Thread.currentThread().getContextClassLoader();
        try (ChildFirst loader = new ChildFirst(output.toUri().toURL(), prior)) {
            System.setProperty("mallory.graphchecker.trace.file", trace.toString());
            Thread.currentThread().setContextClassLoader(loader);
            JUnitTrialRunner.main(new String[]{PREFIX + "FixtureCallThrowJUnit",
                    "originalFactoryThrow"});
        } finally {
            Thread.currentThread().setContextClassLoader(prior);
            if (previousTrace == null) System.clearProperty("mallory.graphchecker.trace.file");
            else System.setProperty("mallory.graphchecker.trace.file", previousTrace);
        }
        int throwsSeen = 0;
        for (String line : Files.readAllLines(trace, StandardCharsets.UTF_8)) {
            JsonObject row = JsonParser.parseString(line).getAsJsonObject();
            if ("TARGET_THROW".equals(row.get("kind").getAsString())
                    && "factory-call".equals(row.get("siteId").getAsString())) throwsSeen++;
        }
        assertEquals(1, throwsSeen);
    }

    private static void copy(Path input, String clazz) throws Exception {
        String name = clazz.replace('.', '/') + ".class";
        Path target = input.resolve(name);
        Files.createDirectories(target.getParent());
        try (InputStream source = CallThrowFactoryWeaveTest.class.getClassLoader()
                .getResourceAsStream(name)) {
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
