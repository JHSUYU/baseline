package edu.uva.liftlab.graphchecker.causynth;

import com.google.gson.JsonObject;
import org.junit.Test;
import soot.Scene;
import soot.options.Options;

import javax.tools.JavaCompiler;
import javax.tools.ToolProvider;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Collections;
import java.util.zip.GZIPInputStream;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

/** Executes the vendored original analyzer, region planner and scope map. */
public class MalloryOriginalSeedBridgeTest {
    @Test public void originalEngineBuildsScopeFromUnmodifiedClass() throws Exception {
        Path root = Files.createTempDirectory("mallory-original-seed-");
        Path source = root.resolve("fx/Check.java");
        Files.createDirectories(source.getParent());
        Files.write(source, ("package fx;\n"
                + "public final class Check {\n"
                + "  public void check(boolean bad) throws java.io.IOException {\n"
                + "    if (bad) throw new java.io.IOException(\"bad\");\n"
                + "  }\n"
                + "}\n").getBytes(StandardCharsets.UTF_8));
        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        assertEquals(0, compiler.run(null, null, null, "-g", "-d",
                root.toString(), source.toString()));
        soot.G.reset();
        Options.v().set_prepend_classpath(true);
        Options.v().set_allow_phantom_refs(true);
        Options.v().set_process_dir(Collections.singletonList(root.toString()));
        Options.v().set_soot_classpath(root.toString());
        Options.v().set_output_format(Options.output_format_none);
        Scene.v().loadNecessaryClasses();
        String oldBound = System.getProperty("causynth.loop.default.bound");
        try {
            System.setProperty("causynth.loop.default.bound", "3");
            JsonObject result = MalloryOriginalSeedBridge.analyze(
                    Collections.singletonList(root.toString()),
                    root.resolve("out"), "fx.Check", 4,
                    "java.io.IOException");
            assertEquals("original_graphchecker_seed_backward",
                    result.get("engine").getAsString());
            assertFalse(result.has("edges"));
            try (BufferedReader edges = new BufferedReader(
                    new InputStreamReader(new GZIPInputStream(Files.newInputStream(
                            root.resolve("out/candidate_dataflow_edges.jsonl.gz"))),
                            StandardCharsets.UTF_8))) {
                assertTrue(edges.readLine() != null);
            }
            assertTrue(result.getAsJsonArray("regions").size() > 0);
            assertTrue(result.getAsJsonArray("staticScopeSites").size() > 0);
            assertTrue(Files.size(root.resolve("out/static_scope_map.jsonl")) > 0);
            assertTrue(Files.size(root.resolve("out/root_demand.jsonl")) > 0);
        } finally {
            if (oldBound == null) System.clearProperty("causynth.loop.default.bound");
            else System.setProperty("causynth.loop.default.bound", oldBound);
        }
    }
}
