package edu.uva.liftlab.mallory.graphchecker.weave;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors;
import java.io.InputStream;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import org.junit.Test;

public final class StateGapWeaveTest {
    private static final String TYPE =
            "edu.uva.liftlab.mallory.graphchecker.weave.fixture.FixtureState";

    @Test public void selectedDirectAccessEmitsBoundedGapWithoutStateEdge() throws Exception {
        Path work = Files.createTempDirectory("mallory-gc-state-gap-");
        Path input = Files.createDirectories(work.resolve("original"));
        Path output = Files.createDirectories(work.resolve("woven"));
        String resource = TYPE.replace('.', '/') + ".class";
        Path source = input.resolve(resource);
        Files.createDirectories(source.getParent());
        try (InputStream stream = getClass().getClassLoader().getResourceAsStream(resource)) {
            if (stream == null) throw new IllegalStateException("missing fixture class");
            Files.copy(stream, source);
        }
        Path manifest = work.resolve("manifest.json");
        String field = "<" + TYPE + ": int value>";
        Files.write(manifest, ("{\"stateCandidates\":["
                + "{\"clazz\":\"" + TYPE + "\",\"method\":\"read\",\"descriptor\":\"()I\","
                + "\"line\":6,\"unitIndex\":1,\"siteId\":\"read-site\","
                + "\"access\":\"READ\",\"field\":\"" + field + "\"},"
                + "{\"clazz\":\"" + TYPE + "\",\"method\":\"write\",\"descriptor\":\"(I)V\","
                + "\"line\":8,\"unitIndex\":2,\"siteId\":\"write-site\","
                + "\"access\":\"WRITE\",\"field\":\"" + field + "\"}]}"
                ).getBytes(StandardCharsets.UTF_8));
        WeaveMain.weave(manifest, input, output, System.getProperty("java.class.path"));

        Path trace = work.resolve("trace.jsonl");
        System.setProperty("mallory.graphchecker.trace.file", trace.toString());
        Object anchor = new Object();
        MessageDoors.registerNode(anchor, "EXTERNAL_APP", "CLIENT", "state-gap-smoke");
        MessageDoors.startRecording();
        long root = MessageDoors.beginRequest(anchor, "state-test");
        try (ChildFirst loader = new ChildFirst(output.toUri().toURL(), getClass().getClassLoader())) {
            Class<?> type = Class.forName(TYPE, true, loader);
            Object instance = type.getConstructor().newInstance();
            assertEquals(1, type.getMethod("read").invoke(instance));
            type.getMethod("write", int.class).invoke(instance, 7);
            assertEquals(7, type.getMethod("read").invoke(instance));
        } finally {
            MessageDoors.endRequest(root, "state-test");
            MessageDoors.stopRecording();
        }
        List<String> rows = Files.readAllLines(trace, StandardCharsets.UTF_8);
        int gaps = 0;
        for (String text : rows) {
            JsonObject row = JsonParser.parseString(text).getAsJsonObject();
            String kind = row.get("kind").getAsString();
            assertTrue(!"STATE_READ".equals(kind) && !"STATE_WRITE".equals(kind));
            if ("GAP".equals(kind) && row.has("gapKind")
                    && "STATE_ACCESS_UNHOOKED".equals(row.get("gapKind").getAsString())) gaps++;
        }
        assertEquals(2, gaps);
    }

    private static final class ChildFirst extends URLClassLoader {
        ChildFirst(URL url, ClassLoader parent) { super(new URL[]{url}, parent); }

        @Override protected synchronized Class<?> loadClass(String name, boolean resolve)
                throws ClassNotFoundException {
            if (!name.equals(TYPE)) return super.loadClass(name, resolve);
            Class<?> loaded = findLoadedClass(name);
            if (loaded == null) loaded = findClass(name);
            if (resolve) resolveClass(loaded);
            return loaded;
        }
    }
}
