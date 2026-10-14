package edu.uva.liftlab.graphchecker.causynth;

import com.google.gson.JsonObject;
import org.junit.Test;
import soot.Scene;
import soot.SootMethod;
import soot.Unit;
import soot.jimple.Stmt;
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
    @Test public void calledExceptionSeedsFromItsBooleanArgument() throws Exception {
        Path root = Files.createTempDirectory("mallory-original-callthrow-");
        Path source = root.resolve("fx/CalledCheck.java");
        Files.createDirectories(source.getParent());
        Files.write(source, ("package fx;\n"
                + "public final class CalledCheck {\n"
                + "  static void checkState(boolean valid) {\n"
                + "    if (!valid) throw new IllegalStateException(\"bad\");\n"
                + "  }\n"
                + "  public void check(Object first, Object second) {\n"
                + "    boolean valid = first == second || first.equals(second);\n"
                + "    checkState(valid);\n"
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
        SootMethod owner = Scene.v().getSootClass("fx.CalledCheck")
                .getMethodByName("check");
        int callIndex = -1;
        String callee = "";
        int ordinal = 0;
        for (Unit unit : owner.retrieveActiveBody().getUnits()) {
            if (unit instanceof Stmt && ((Stmt) unit).containsInvokeExpr()
                    && ((Stmt) unit).getInvokeExpr().getMethodRef()
                            .name().equals("checkState")) {
                callIndex = ordinal;
                callee = ((Stmt) unit).getInvokeExpr().getMethodRef()
                        .getSignature();
            }
            ordinal++;
        }
        assertTrue(callIndex >= 0);
        String oldBound = System.getProperty("causynth.loop.default.bound");
        try {
            System.setProperty("causynth.loop.default.bound", "3");
            JsonObject result = MalloryOriginalSeedBridge.analyzeCallThrow(
                    Collections.singletonList(root.toString()), root.resolve("out"),
                    owner.getSignature(), callIndex, callee,
                    "java.lang.IllegalStateException");
            assertEquals("CALL_THROW", result.getAsJsonObject("targetResolved")
                    .get("targetKind").getAsString());
            assertEquals(callIndex, result.getAsJsonObject("targetResolved")
                    .get("callUnitIndex").getAsInt());
            assertTrue(result.getAsJsonArray("regions").size() > 0);
            assertTrue(result.getAsJsonArray("staticScopeSites").size() > 0);
        } finally {
            if (oldBound == null) System.clearProperty("causynth.loop.default.bound");
            else System.setProperty("causynth.loop.default.bound", oldBound);
        }
    }

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
