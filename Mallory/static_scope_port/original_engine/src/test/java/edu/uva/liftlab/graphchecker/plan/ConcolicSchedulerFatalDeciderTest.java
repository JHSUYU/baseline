package edu.uva.liftlab.graphchecker.plan;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import org.junit.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

public final class ConcolicSchedulerFatalDeciderTest {
    private static final String GUARD = "<T: boolean f()>#u4";
    private static final String HELPER = "<H: boolean f()>#u3";

    private StaticScopeMap map(boolean includeSecondOpen) throws Exception {
        JsonObject row = new JsonObject();
        row.addProperty("schemaVersion", 1);
        row.addProperty("kind", "STATIC_SCOPE_SITE");
        row.addProperty("role", "TARGET_SITE");
        row.addProperty("regionId", "REGION.test");
        row.addProperty("siteId", "<T: void f()>#u10");
        JsonArray guards = new JsonArray();
        guards.add(GUARD);
        row.add("guards", guards);
        JsonArray outcomes = new JsonArray();
        outcomes.add(false);
        row.add("guardOutcomes", outcomes);
        JsonArray deciders = new JsonArray();
        JsonObject open = new JsonObject();
        open.addProperty("siteId", HELPER);
        open.addProperty("outcome", true);
        deciders.add(open);
        JsonObject nonFatal = new JsonObject();
        nonFatal.addProperty("siteId", HELPER);
        nonFatal.addProperty("outcome", false);
        nonFatal.addProperty("verdict", true);
        deciders.add(nonFatal);
        if (includeSecondOpen) {
            JsonObject another = new JsonObject();
            another.addProperty("siteId", "<H: boolean g()>#u1");
            another.addProperty("outcome", false);
            deciders.add(another);
        }
        JsonObject stated = new JsonObject();
        stated.add(GUARD, deciders);
        row.add("guardDeciders", stated);
        Path file = Files.createTempFile("mallory-decider-", ".jsonl");
        try {
            Files.write(file, (row.toString() + "\n").getBytes(StandardCharsets.UTF_8));
            return StaticScopeMap.read(file);
        } finally {
            Files.deleteIfExists(file);
        }
    }

    @Test
    public void excludesOnlyConstantReturnKnownToMissFatalArm() throws Exception {
        StaticScopeMap.Guard winner = ConcolicScheduler.fatalDecider(map(false), GUARD);
        assertEquals(HELPER, winner.siteId());
        assertEquals(Boolean.TRUE, winner.outcome());
        assertNull(winner.verdict());
    }

    @Test
    public void retainsRefusalWhenTwoCompatibleArmsRemain() throws Exception {
        try {
            ConcolicScheduler.fatalDecider(map(true), GUARD);
            fail("ambiguous open arms must still be refused");
        } catch (IllegalStateException expected) {
            assertTrue(expected.getMessage().contains("2 compatible of 3"));
        }
    }
}
