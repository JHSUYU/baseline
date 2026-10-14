package edu.uva.liftlab.mallory.graphchecker.runtime;

import com.google.gson.JsonObject;
import org.junit.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Collections;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class StaticScopeValueTest {
    @Test public void valueEdgeReachesProducerButReverseEdgeDoesNot() throws Exception {
        Path positive = Files.createTempFile("static-value-positive-", ".jsonl");
        Files.write(positive, (row("TARGET_SITE", "target", "check") + "\n"
                + row("DOOR_SITE", "producer2", "rpc") + "\n"
                + membership("producer", "fx.Producer.fetch") + "\n"
                + membership("producer2", "fx.Producer.fetch") + "\n"
                + membership("target1", "fx.Consumer.check") + "\n"
                + membership("target", "fx.Consumer.check") + "\n"
                + edge("fx.Producer.fetch", "fx.Consumer.check") + "\n")
                .getBytes(StandardCharsets.UTF_8));
        StaticScope.Result reached = StaticScope.read(positive).mayReach("check",
                Collections.<String>emptySet());
        assertTrue(reached.targetFound);
        assertTrue(reached.regions.contains("producer"));
        assertTrue(reached.regions.contains("producer2"));
        assertTrue(reached.doorSites.contains("rpc"));
        assertEquals("STATIC_VALUE", reached.relations.get(0).get("kind").getAsString());

        Path negative = Files.createTempFile("static-value-negative-", ".jsonl");
        Files.write(negative, (row("TARGET_SITE", "target", "check") + "\n"
                + row("DOOR_SITE", "producer", "rpc") + "\n"
                + membership("producer", "fx.Producer.fetch") + "\n"
                + membership("target", "fx.Consumer.check") + "\n"
                + edge("fx.Consumer.check", "fx.Producer.fetch") + "\n")
                .getBytes(StandardCharsets.UTF_8));
        StaticScope.Result excluded = StaticScope.read(negative).mayReach("check",
                Collections.<String>emptySet());
        assertFalse(excluded.regions.contains("producer"));
        assertFalse(excluded.doorSites.contains("rpc"));
    }

    private static JsonObject row(String role, String region, String site) {
        JsonObject row = new JsonObject();
        row.addProperty("kind", "STATIC_SCOPE_SITE");
        row.addProperty("role", role);
        row.addProperty("regionId", region);
        row.addProperty("siteId", site);
        return row;
    }

    private static JsonObject membership(String region, String method) {
        JsonObject row = row("STATIC_REGION_METHOD", region, "");
        row.addProperty("vmMethod", method);
        return row;
    }

    private static JsonObject edge(String producer, String consumer) {
        JsonObject row = row("STATIC_VALUE_EDGE", "", "");
        row.addProperty("producerMethod", producer);
        row.addProperty("consumerMethod", consumer);
        row.addProperty("carrier", "call_return");
        return row;
    }
}
