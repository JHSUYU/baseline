package edu.uva.liftlab.mallory.scope;

import com.google.gson.JsonObject;
import org.junit.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.LinkedHashSet;
import java.util.zip.GZIPOutputStream;

import static org.junit.Assert.assertEquals;

public class StaticValueProjectionTest {
    @Test public void projectsOnlySelectedDirectedValueTransfers() throws Exception {
        String source = "<fx.Producer: java.lang.Object fetch()>";
        String target = "<fx.Consumer: void check()>";
        String other = "<fx.Unselected: java.lang.Object get()>";
        Path directory = Files.createTempDirectory("static-value-");
        StringBuilder edges = new StringBuilder();
        for (String[] edge : Arrays.asList(
                new String[] {"call_return", source + ".return", target + "::$r0"},
                new String[] {"call_return", source + ".return", target + "::$r1"},
                new String[] {"guard_dependency", source + "::$z0", target + "::$z1"},
                new String[] {"call_return", other + ".return", target + "::$r2"},
                new String[] {"dispatch_activation", source + ".return", target + "::$r3"},
                new String[] {"call_return", target + ".return", source + "::$r0"})) {
            JsonObject row = new JsonObject();
            row.addProperty("kind", edge[0]);
            row.addProperty("transferKind", edge[0].equals("guard_dependency")
                    ? "GUARD" : edge[0].equals("dispatch_activation")
                    ? "DYNAMIC_DISPATCH" : "VALUE_TRANSFER");
            row.addProperty("fromCell", edge[1]);
            row.addProperty("toCell", edge[2]);
            edges.append(row).append('\n');
        }
        try (GZIPOutputStream output = new GZIPOutputStream(Files.newOutputStream(
                directory.resolve("candidate_dataflow_edges.jsonl.gz")))) {
            output.write(edges.toString().getBytes(StandardCharsets.UTF_8));
        }
        Map<String, Set<String>> regions = new HashMap<>();
        regions.put(source, new LinkedHashSet<>(Arrays.asList("producer", "producer2")));
        regions.put(target, new LinkedHashSet<>(Arrays.asList("target1", "target")));
        List<JsonObject> projected = StaticValueProjection.read(directory, regions);
        assertEquals(6, projected.size());
        assertEquals("STATIC_VALUE_EDGE", projected.get(0).get("role").getAsString());
        assertEquals(source, projected.get(0).get("producerMethod").getAsString());
        assertEquals(target, projected.get(0).get("consumerMethod").getAsString());
        assertEquals("STATIC_REGION_METHOD", projected.get(3).get("role").getAsString());
        assertEquals("producer2", projected.get(3).get("regionId").getAsString());
        assertEquals("target", projected.get(5).get("regionId").getAsString());
    }
}
