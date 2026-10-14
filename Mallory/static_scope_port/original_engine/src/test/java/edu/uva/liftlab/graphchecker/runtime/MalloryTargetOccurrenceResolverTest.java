package edu.uva.liftlab.graphchecker.runtime;

import static org.junit.Assert.assertEquals;
import com.google.gson.JsonObject;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.Test;

public final class MalloryTargetOccurrenceResolverTest {
    @Test
    public void registeredServerOccurrenceWinsOverEarlierClientSetup() {
        JsonObject client = event(10, "CLIENT");
        JsonObject server = event(20, "NAMENODE");
        assertEquals(20L, MalloryTargetOccurrenceResolver.selectOccurrence(
                Arrays.asList(client, server)).get("eventSeq").getAsLong());
        assertEquals(10L, MalloryTargetOccurrenceResolver.selectOccurrence(
                Arrays.asList(client, event(30, "CLIENT"))).get("eventSeq")
                .getAsLong());
    }

    private static JsonObject event(long seq, String role) {
        JsonObject row = new JsonObject();
        row.addProperty("eventSeq", seq);
        row.addProperty("sourceRole", role);
        return row;
    }

    @Test
    public void exactCallAndFoldedTargetRegionFindOneOwner() {
        List<Map<String, Object>> activations = new ArrayList<>();
        activations.add(activation("outer", Arrays.asList("target"),
                Arrays.asList(11L, 12L)));
        activations.add(activation("unrelated", Arrays.asList("target"),
                Arrays.asList(20L)));
        assertEquals(1, MalloryTargetOccurrenceResolver.owners(
                activations, "target", 12L).size());
        assertEquals("outer", MalloryTargetOccurrenceResolver.owners(
                activations, "target", 12L).get(0).get("regionId"));
        assertEquals(0, MalloryTargetOccurrenceResolver.owners(
                activations, "target", 99L).size());
    }

    private static Map<String, Object> activation(String region,
            List<String> folded, List<Long> calls) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("regionId", region);
        result.put("foldedRegionIds", folded);
        result.put("callIds", calls);
        return result;
    }
}
