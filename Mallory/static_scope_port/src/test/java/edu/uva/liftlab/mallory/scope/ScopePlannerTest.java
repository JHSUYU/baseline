package edu.uva.liftlab.mallory.scope;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import edu.uva.liftlab.graphchecker.MalloryLambdaClassNames;
import org.junit.Test;
import soot.PackManager;
import soot.Scene;
import soot.SootClass;
import soot.options.Options;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertTrue;

public class ScopePlannerTest {
    @Test
    public void graphCheckerRegionPortSelectsRealFixtureDoorWithoutChangingDefault()
            throws Exception {
        String source = new String(Files.readAllBytes(Paths.get(
                "src/test/java/edu/uva/liftlab/mallory/scope/ScopeFixture.java")),
                StandardCharsets.UTF_8);
        int line = 1;
        for (String text : source.split("\n", -1)) {
            if (text.contains("READ_TARGET")) break;
            line++;
        }
        JsonObject config = new JsonObject();
        JsonObject target = new JsonObject();
        target.addProperty("class", ScopeFixture.class.getName());
        target.addProperty("method", "checkReader");
        target.addProperty("line", line);
        target.addProperty("exception", "java.io.IOException");
        config.add("target", target);
        JsonObject analysis = new JsonObject();
        JsonArray paths = new JsonArray();
        paths.add("target/test-classes");
        analysis.add("process_dirs", paths);
        analysis.add("classpath", paths);
        config.add("analysis", analysis);

        JsonObject defaultResult = ScopePlanner.analyze(config);
        assertTrue(!defaultResult.has("graphCheckerRegionPort"));
        analysis.addProperty("graphchecker_region_port", true);
        JsonObject migrated = ScopePlanner.analyze(config);
        JsonObject port = migrated.getAsJsonObject("graphCheckerRegionPort");
        assertTrue(port.getAsJsonArray("regions").size() > 0);
        assertTrue(port.getAsJsonObject("facts").getAsJsonArray("edges").size() > 0);
        boolean readLine = false;
        for (JsonElement entry : port.getAsJsonObject("weaveManifest")
                .getAsJsonArray("doors")) {
            if (entry.getAsJsonObject().get("callee").getAsString()
                    .contains("readLine()")) readLine = true;
        }
        assertTrue(readLine);
        assertEquals(defaultResult.getAsJsonObject("weaveManifest")
                        .getAsJsonArray("targets").size(),
                port.getAsJsonObject("weaveManifest")
                        .getAsJsonArray("targets").size());
    }

    @Test
    public void instrumentationHelperIsInScopeButCannotBeAFaultDoor() throws Exception {
        String source = new String(Files.readAllBytes(Paths.get(
                "src/test/java/edu/uva/liftlab/mallory/scope/ScopeFixture.java")),
                StandardCharsets.UTF_8);
        int line = 1;
        for (String text : source.split("\n", -1)) {
            if (text.contains("HELPER_TARGET")) break;
            line++;
        }
        JsonObject config = new JsonObject();
        JsonObject target = new JsonObject();
        target.addProperty("class", ScopeFixture.class.getName());
        target.addProperty("method", "checkHelperDoor");
        target.addProperty("line", line);
        target.addProperty("exception", "java.io.IOException");
        config.add("target", target);
        JsonObject analysis = new JsonObject();
        JsonArray paths = new JsonArray();
        paths.add("target/test-classes");
        analysis.add("process_dirs", paths);
        analysis.add("classpath", paths);
        config.add("analysis", analysis);

        JsonObject result = ScopePlanner.analyze(config);
        boolean helperRegion = false;
        for (JsonElement entry : result.getAsJsonArray("scopeSites")) {
            JsonObject site = entry.getAsJsonObject();
            if (!site.get("clazz").getAsString()
                    .equals(GraphCheckerFixtureHelper.class.getName())) continue;
            if ("REGION_SITE".equals(site.get("role").getAsString())) helperRegion = true;
            assertTrue(!"DOOR_SITE".equals(site.get("role").getAsString()));
        }
        assertTrue(helperRegion);
    }

    @Test
    public void checkedResourceOpeningConstructorIsAnIoDoor() throws Exception {
        String source = new String(Files.readAllBytes(Paths.get(
                "src/test/java/edu/uva/liftlab/mallory/scope/ScopeFixture.java")),
                StandardCharsets.UTF_8);
        int line = 1;
        for (String text : source.split("\n", -1)) {
            if (text.contains("FILE_READ_TARGET")) break;
            line++;
        }
        JsonObject config = new JsonObject();
        JsonObject target = new JsonObject();
        target.addProperty("class", ScopeFixture.class.getName());
        target.addProperty("method", "checkFileReader");
        target.addProperty("line", line);
        target.addProperty("exception", "java.io.IOException");
        config.add("target", target);
        JsonObject analysis = new JsonObject();
        JsonArray paths = new JsonArray();
        paths.add("target/test-classes");
        analysis.add("process_dirs", paths);
        analysis.add("classpath", paths);
        analysis.addProperty("constructor_io_doors_verified", true);
        config.add("analysis", analysis);

        JsonObject result = ScopePlanner.analyze(config);
        boolean opening = false;
        for (JsonElement entry : result.getAsJsonArray("scopeSites")) {
            JsonObject site = entry.getAsJsonObject();
            if ("DOOR_SITE".equals(site.get("role").getAsString())
                    && site.get("callee").getAsString()
                    .contains("java.io.FileReader: void <init>(java.io.File)")) {
                opening = true;
            }
        }
        assertTrue(opening);
        analysis.remove("constructor_io_doors_verified");
        JsonObject unverified = ScopePlanner.analyze(config);
        for (JsonElement entry : unverified.getAsJsonArray("scopeSites")) {
            JsonObject site = entry.getAsJsonObject();
            assertTrue(!"DOOR_SITE".equals(site.get("role").getAsString())
                    || !site.get("callee").getAsString()
                    .contains("java.io.FileReader: void <init>(java.io.File)"));
        }
        boolean gap = false;
        for (JsonElement entry : unverified.getAsJsonArray("analysisGaps")) {
            if (entry.getAsString().startsWith("resource_constructor_probe_unverified:")) gap = true;
        }
        assertTrue(gap);
    }

    @Test
    public void checkedReaderReadLineIsAnIoDoor() throws Exception {
        String source = new String(Files.readAllBytes(Paths.get(
                "src/test/java/edu/uva/liftlab/mallory/scope/ScopeFixture.java")),
                StandardCharsets.UTF_8);
        int line = 1;
        for (String text : source.split("\n", -1)) {
            if (text.contains("READ_TARGET")) break;
            line++;
        }
        JsonObject config = new JsonObject();
        JsonObject target = new JsonObject();
        target.addProperty("class", ScopeFixture.class.getName());
        target.addProperty("method", "checkReader");
        target.addProperty("line", line);
        target.addProperty("exception", "java.io.IOException");
        config.add("target", target);
        JsonObject analysis = new JsonObject();
        JsonArray paths = new JsonArray();
        paths.add("target/test-classes");
        analysis.add("process_dirs", paths);
        analysis.add("classpath", paths);
        config.add("analysis", analysis);

        JsonObject result = ScopePlanner.analyze(config);
        boolean readLine = false;
        for (JsonElement entry : result.getAsJsonArray("scopeSites")) {
            JsonObject site = entry.getAsJsonObject();
            if ("DOOR_SITE".equals(site.get("role").getAsString())
                    && site.get("callee").getAsString().contains("readLine()")) {
                readLine = true;
            }
        }
        assertTrue(readLine);
    }

    @Test
    public void branchTargetExportsItsUniqueControlledFatalThrow() throws Exception {
        String source = new String(Files.readAllBytes(Paths.get(
                "src/test/java/edu/uva/liftlab/mallory/scope/ScopeFixture.java")),
                StandardCharsets.UTF_8);
        int line = 1;
        for (String text : source.split("\n", -1)) {
            if (text.contains("SCOPE_TARGET")) break;
            line++;
        }
        JsonObject config = new JsonObject();
        JsonObject target = new JsonObject();
        target.addProperty("class", ScopeFixture.class.getName());
        target.addProperty("method", "check");
        target.addProperty("line", line);
        target.addProperty("kind", "BRANCH");
        target.addProperty("exception", "java.io.IOException");
        config.add("target", target);
        JsonObject analysis = new JsonObject();
        JsonArray paths = new JsonArray();
        paths.add("target/test-classes");
        analysis.add("process_dirs", paths);
        analysis.add("classpath", paths);
        config.add("analysis", analysis);

        JsonObject result = ScopePlanner.analyze(config);
        assertTrue(!result.get("throwSiteId").getAsString().isEmpty());
        assertTrue(hasRole(result, "TARGET_SITE"));
        assertTrue(hasRole(result, "THROW_SITE"));
        assertEquals(2, result.getAsJsonObject("weaveManifest")
                .getAsJsonArray("targets").size());
        boolean typedOracle = false;
        for (JsonElement entry : result.getAsJsonObject("weaveManifest")
                .getAsJsonArray("targets")) {
            JsonObject site = entry.getAsJsonObject();
            if ("THROW".equals(site.get("kind").getAsString())) {
                typedOracle = "java.io.IOException".equals(
                        site.get("exceptionClass").getAsString());
            }
        }
        assertTrue(typedOracle);
    }

    @Test
    public void fieldJumpAndMappedWirePublishMaySitesButNoRuntimeEdge() throws Exception {
        String source = new String(Files.readAllBytes(Paths.get(
                "src/test/java/edu/uva/liftlab/mallory/scope/ScopeFixture.java")),
                StandardCharsets.UTF_8);
        int line = 1;
        for (String text : source.split("\n", -1)) {
            if (text.contains("SCOPE_TARGET")) break;
            line++;
        }
        JsonObject config = new JsonObject();
        config.addProperty("case_id", "fixture");
        JsonObject target = new JsonObject();
        target.addProperty("class", ScopeFixture.class.getName());
        target.addProperty("method", "check");
        target.addProperty("line", line);
        target.addProperty("exception", "IOException");
        config.add("target", target);
        JsonObject analysis = new JsonObject();
        JsonArray dirs = new JsonArray();
        dirs.add("target/test-classes");
        analysis.add("process_dirs", dirs);
        JsonArray cp = new JsonArray();
        cp.add("target/test-classes");
        analysis.add("classpath", cp);
        JsonArray maps = new JsonArray();
        JsonObject mapping = new JsonObject();
        mapping.addProperty("portId", "fixture:wire");
        mapping.addProperty("transport", "TEST_WIRE");
        mapping.addProperty("sendMethod", "ScopeFixture:.*send\\(");
        mapping.addProperty("receiveMethod", "ScopeFixture:.*receive\\(");
        maps.add(mapping);
        analysis.add("rpc_mappings", maps);
        config.add("analysis", analysis);

        Path temp = Files.createTempDirectory("mallory-scope-test-");
        JsonObject result = ScopePlanner.plan(config, temp);
        assertEquals("graphchecker_derived_static_scope",
                result.get("analysisKind").getAsString());
        assertTrue(hasRole(result, "TARGET_SITE"));
        assertTrue(hasRole(result, "THROW_SITE"));
        assertTrue(hasRole(result, "READ_SITE"));
        assertTrue(hasRole(result, "WRITE_SITE"));
        assertTrue(hasRole(result, "EXPORT_SITE"));
        assertTrue(hasRole(result, "IMPORT_SITE"));
        assertTrue(hasEvidence(result, "formal_actual_jump"));
        assertTrue(Files.readAllLines(temp.resolve("static_scope_map.jsonl")).size() > 5);
        assertTrue(result.getAsJsonObject("weaveManifest").getAsJsonArray("targets").size() >= 2);
        assertEquals(result.get("sootDependencyClasspathSha256").getAsString(),
                result.getAsJsonObject("weaveManifest")
                        .get("sootDependencyClasspathSha256").getAsString());
        assertEquals(64, result.get("sootDependencyClasspathSha256")
                .getAsString().length());
        for (JsonElement row : result.getAsJsonArray("scopeSites")) {
            JsonObject site = row.getAsJsonObject();
            assertEquals("STATIC_SCOPE_SITE", site.get("kind").getAsString());
            assertTrue(site.has("unitIndex"));
            assertTrue(!site.has("observedProducer"));
        }
    }

    @Test
    public void normalCodeAfterCatchDoesNotDemandProtectedCalls() throws Exception {
        String source = new String(Files.readAllBytes(Paths.get(
                "src/test/java/edu/uva/liftlab/mallory/scope/ScopeFixture.java")),
                StandardCharsets.UTF_8);
        int line = 1;
        for (String text : source.split("\n", -1)) {
            if (text.contains("AFTER_CATCH_TARGET")) break;
            line++;
        }
        JsonObject config = new JsonObject();
        JsonObject target = new JsonObject();
        target.addProperty("class", ScopeFixture.class.getName());
        target.addProperty("method", "afterCatch");
        target.addProperty("line", line);
        target.addProperty("exception", "IOException");
        config.add("target", target);
        JsonObject analysis = new JsonObject();
        JsonArray paths = new JsonArray();
        paths.add("target/test-classes");
        analysis.add("process_dirs", paths);
        analysis.add("classpath", paths.deepCopy());
        config.add("analysis", analysis);
        JsonObject result = ScopePlanner.analyze(config);
        assertTrue(hasRole(result, "TARGET_SITE"));
        assertTrue(!hasEvidence(result, "caught_call_may"));
    }

    @Test
    public void disjointLocalAllocationsDoNotJumpToUnrelatedFieldWriter() throws Exception {
        String source = new String(Files.readAllBytes(Paths.get(
                "src/test/java/edu/uva/liftlab/mallory/scope/ScopeFixture.java")),
                StandardCharsets.UTF_8);
        int targetLine = 0;
        int unrelatedLine = 0;
        int line = 1;
        for (String text : source.split("\n", -1)) {
            if (text.contains("BOX_TARGET")) targetLine = line;
            if (text.contains("unrelated.value =")) unrelatedLine = line;
            line++;
        }
        JsonObject config = new JsonObject();
        JsonObject target = new JsonObject();
        target.addProperty("class", ScopeFixture.class.getName());
        target.addProperty("method", "checkDistinctBox");
        target.addProperty("line", targetLine);
        target.addProperty("exception", "IOException");
        config.add("target", target);
        JsonObject analysis = new JsonObject();
        JsonArray paths = new JsonArray();
        paths.add("target/test-classes");
        analysis.add("process_dirs", paths);
        analysis.add("classpath", paths.deepCopy());
        config.add("analysis", analysis);
        JsonObject result = ScopePlanner.analyze(config);
        assertTrue(hasEvidence(result, "field_wide_writer_jump"));
        for (JsonElement item : result.getAsJsonArray("scopeSites")) {
            JsonObject row = item.getAsJsonObject();
            if (row.get("line").getAsInt() != unrelatedLine) continue;
            for (JsonElement reason : row.getAsJsonArray("evidence")) {
                assertTrue(!"field_wide_writer_jump".equals(reason.getAsString()));
            }
        }
    }

    @Test
    public void callableDispatchAndExecutorSubmissionRemainInStaticScope() throws Exception {
        String source = new String(Files.readAllBytes(Paths.get(
                "src/test/java/edu/uva/liftlab/mallory/scope/ScopeFixture.java")),
                StandardCharsets.UTF_8);
        int callableLine = 0;
        int callbackLine = 0;
        int line = 1;
        for (String text : source.split("\n", -1)) {
            if (text.contains("CALLABLE_TARGET")) callableLine = line;
            if (text.contains("CALLBACK_TARGET")) callbackLine = line;
            line++;
        }
        JsonObject analysis = new JsonObject();
        JsonArray paths = new JsonArray();
        paths.add("target/test-classes");
        analysis.add("process_dirs", paths);
        analysis.add("classpath", paths.deepCopy());

        JsonObject direct = new JsonObject();
        JsonObject target = new JsonObject();
        target.addProperty("class", ScopeFixture.class.getName());
        target.addProperty("method", "checkCallable");
        target.addProperty("line", callableLine);
        target.addProperty("exception", "IOException");
        direct.add("target", target);
        direct.add("analysis", analysis);
        JsonObject directResult = ScopePlanner.analyze(direct);
        assertTrue(hasMethod(directResult, "java.lang.String call()"));

        JsonObject async = new JsonObject();
        JsonObject callbackTarget = new JsonObject();
        callbackTarget.addProperty("class", ScopeFixture.Job.class.getName());
        callbackTarget.addProperty("method", "run");
        callbackTarget.addProperty("line", callbackLine);
        callbackTarget.addProperty("exception", "IllegalStateException");
        async.add("target", callbackTarget);
        async.add("analysis", analysis.deepCopy());
        JsonObject asyncResult = ScopePlanner.analyze(async);
        assertTrue(hasMethod(asyncResult, "void schedule(java.util.concurrent.Executor)"));
    }

    @Test
    public void sootLambdaBootstrapNarrowsCallableDispatchToItsAllocation() throws Exception {
        String source = new String(Files.readAllBytes(Paths.get(
                "src/test/java/edu/uva/liftlab/mallory/scope/ScopeFixture.java")),
                StandardCharsets.UTF_8);
        int targetLine = 1;
        for (String text : source.split("\n", -1)) {
            if (text.contains("LAMBDA_TARGET")) break;
            targetLine++;
        }
        JsonObject config = new JsonObject();
        JsonObject target = new JsonObject();
        target.addProperty("class", ScopeFixture.class.getName());
        target.addProperty("method", "checkLambdaCallable");
        target.addProperty("line", targetLine);
        target.addProperty("exception", "IOException");
        config.add("target", target);
        JsonObject analysis = new JsonObject();
        JsonArray paths = new JsonArray();
        paths.add("target/test-classes");
        analysis.add("process_dirs", paths);
        analysis.add("classpath", paths.deepCopy());
        config.add("analysis", analysis);
        JsonObject result = ScopePlanner.analyze(config);
        java.util.Set<String> lambdaCalls = new java.util.HashSet<>();
        for (JsonElement element : result.getAsJsonArray("scopeSites")) {
            String vmSite = element.getAsJsonObject().get("vmSite").getAsString();
            if (vmSite.contains("$lambda_checkLambdaCallable_")
                    && vmSite.contains(" call()")) lambdaCalls.add(vmSite);
        }
        assertEquals(1, lambdaCalls.size());
    }

    @Test
    public void staticScopeAndGraphCheckerWeaveUseIdenticalLambdaClassNames() throws Exception {
        assertArrayEquals("The static planner must use the exact migrated GraphChecker factory",
                Files.readAllBytes(Paths.get("original_engine/vendor/src/main/java/edu/uva/"
                        + "liftlab/graphchecker/LambdaClassNames.java")),
                Files.readAllBytes(Paths.get("src/main/java/edu/uva/liftlab/graphchecker/"
                        + "LambdaClassNames.java")));
        String source = new String(Files.readAllBytes(Paths.get(
                "src/test/java/edu/uva/liftlab/mallory/scope/ScopeFixture.java")),
                StandardCharsets.UTF_8);
        int targetLine = 1;
        for (String text : source.split("\n", -1)) {
            if (text.contains("LAMBDA_TARGET")) break;
            targetLine++;
        }
        JsonObject config = new JsonObject();
        JsonObject target = new JsonObject();
        target.addProperty("class", ScopeFixture.class.getName());
        target.addProperty("method", "checkLambdaCallable");
        target.addProperty("line", targetLine);
        target.addProperty("exception", "IOException");
        config.add("target", target);
        JsonObject analysis = new JsonObject();
        JsonArray paths = new JsonArray();
        paths.add("target/test-classes");
        analysis.add("process_dirs", paths);
        analysis.add("classpath", paths.deepCopy());
        config.add("analysis", analysis);

        JsonObject staticScope = ScopePlanner.analyze(config);
        java.util.Set<String> staticLambdaNames = lambdaNames(staticScope);
        assertTrue(staticLambdaNames.toString(), !staticLambdaNames.isEmpty());

        // A separate Soot scene models GraphCheckerMain's production weave:
        // classes are loaded first, then the original content-stable factory
        // is installed before runPacks materializes any lambda body.
        soot.G.reset();
        Options.v().set_prepend_classpath(true);
        Options.v().set_allow_phantom_refs(true);
        Options.v().set_whole_program(false);
        Options.v().set_output_format(Options.output_format_none);
        Options.v().set_process_dir(java.util.Collections.singletonList("target/test-classes"));
        Options.v().set_soot_classpath("target/test-classes");
        Scene.v().loadNecessaryClasses();
        MalloryLambdaClassNames.install();
        PackManager.v().runPacks();
        java.util.Set<String> weaveLambdaNames = new java.util.HashSet<>();
        for (SootClass clazz : Scene.v().getClasses()) {
            if (clazz.getName().contains("ScopeFixture$lambda_checkLambdaCallable_")) {
                weaveLambdaNames.add(clazz.getName());
            }
        }
        assertTrue(weaveLambdaNames.toString(), weaveLambdaNames.containsAll(staticLambdaNames));
    }

    @Test
    public void originalSeedUsesIdenticalSharedInitializationSplitter() throws Exception {
        assertArrayEquals("The original seed and concolic weave must lower the same Jimple",
                Files.readAllBytes(Paths.get("original_engine/vendor/src/main/java/edu/uva/"
                        + "liftlab/graphchecker/SharedInitializationSplitter.java")),
                Files.readAllBytes(Paths.get("src/main/java/edu/uva/liftlab/graphchecker/"
                        + "SharedInitializationSplitter.java")));
    }

    private static java.util.Set<String> lambdaNames(JsonObject scope) {
        java.util.Set<String> names = new java.util.HashSet<>();
        for (JsonElement entry : scope.getAsJsonArray("scopeSites")) {
            String vmSite = entry.getAsJsonObject().get("vmSite").getAsString();
            int start = vmSite.indexOf('<');
            int end = vmSite.indexOf(':', start + 1);
            if (start >= 0 && end > start) {
                String owner = vmSite.substring(start + 1, end);
                if (owner.contains("ScopeFixture$lambda_checkLambdaCallable_")) names.add(owner);
            }
        }
        return names;
    }

    private static boolean hasMethod(JsonObject result, String signatureSuffix) {
        for (JsonElement item : result.getAsJsonArray("scopeSites")) {
            String method = item.getAsJsonObject().get("siteId").getAsString();
            if (method.contains(signatureSuffix)) return true;
        }
        return false;
    }

    private static boolean hasRole(JsonObject result, String role) {
        for (JsonElement item : result.getAsJsonArray("scopeSites")) {
            if (role.equals(item.getAsJsonObject().get("role").getAsString())) return true;
        }
        return false;
    }

    private static boolean hasEvidence(JsonObject result, String evidence) {
        for (JsonElement item : result.getAsJsonArray("scopeSites")) {
            JsonObject row = item.getAsJsonObject();
            if (!row.has("evidence")) continue;
            for (JsonElement reason : row.getAsJsonArray("evidence")) {
                if (evidence.equals(reason.getAsString())) return true;
            }
        }
        return false;
    }
}
