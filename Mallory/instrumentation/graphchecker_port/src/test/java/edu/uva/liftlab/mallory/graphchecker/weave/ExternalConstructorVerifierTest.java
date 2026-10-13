package edu.uva.liftlab.mallory.graphchecker.weave;

import java.io.InputStream;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.Test;

/** A selected external resource constructor keeps its uninitialized receiver valid. */
public final class ExternalConstructorVerifierTest {
    private static final String PREFIX =
            "edu.uva.liftlab.mallory.graphchecker.weave.fixture.";

    @Test public void originalReaderConstructorWithDoorAndCallFrame() throws Throwable {
        Path work = Files.createTempDirectory("mallory-external-ctor-");
        Path input = Files.createDirectories(work.resolve("original"));
        Path output = Files.createDirectories(work.resolve("woven"));
        copy(input, PREFIX + "FixtureExternalConstructor");
        copy(input, PREFIX + "FixtureExternalConstructorJUnit");
        String clazz = PREFIX + "FixtureExternalConstructor";
        String method = "\"clazz\":\"" + clazz + "\",\"method\":\"firstLine\","
                + "\"descriptor\":\"(Ljava/nio/file/Path;)Ljava/lang/String;\"";
        String manifest = "{\"regions\":[{" + method
                + ",\"regionId\":\"external-ctor-region\"}],"
                + "\"frames\":[{" + method + "}],"
                + "\"doors\":[{" + method
                + ",\"line\":11,\"siteId\":\"file-reader-open\","
                + "\"callee\":\"<java.io.FileReader: void <init>(java.io.File)>\","
                + "\"exceptionClass\":\"java.io.IOException\"}]}";
        Path sites = work.resolve("sites.json");
        Files.write(sites, manifest.getBytes(StandardCharsets.UTF_8));
        WeaveMain.weave(sites, input, output, System.getProperty("java.class.path"));

        ClassLoader prior = Thread.currentThread().getContextClassLoader();
        try (ChildFirst loader = new ChildFirst(output.toUri().toURL(), prior)) {
            Thread.currentThread().setContextClassLoader(loader);
            JUnitTrialRunner.main(new String[]{PREFIX + "FixtureExternalConstructorJUnit",
                    "originalReaderConstructor"});
        } finally {
            Thread.currentThread().setContextClassLoader(prior);
        }
    }

    private static void copy(Path input, String clazz) throws Exception {
        String name = clazz.replace('.', '/') + ".class";
        Path target = input.resolve(name);
        Files.createDirectories(target.getParent());
        try (InputStream source = ExternalConstructorVerifierTest.class.getClassLoader()
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
