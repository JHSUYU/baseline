package edu.uva.liftlab.graphchecker.causynth;

import edu.uva.liftlab.graphchecker.plan.StaticScopeMap;

import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.Test;

import static org.junit.Assert.assertEquals;

public final class RegionDemandIncomingOrderTest {
    @Test
    public void retainsFirstSourceOrderBeforeObservedMethodFiltering()
            throws Exception {
        StaticProgram program = new StaticProgram();
        program.skeletons.put("r1", skeleton("r1", "M1", "M2"));
        program.skeletons.put("r2", skeleton("r2", "M2", "M3"));
        program.skeletons.put("r3", skeleton("r3", "M4"));
        program.regions.add(row("regionId", "r1"));
        program.regions.add(row("regionId", "r2"));
        program.activations.put("o1", activation("r1",
                Arrays.asList("r2"), "M2", "M3"));
        program.activations.put("o2", activation("r2",
                Collections.<String>emptyList(), "M2", "M3"));
        program.activations.put("o3", activation("r1",
                Collections.<String>emptyList(), "M2"));
        program.activations.put("o4", activation("r3",
                Collections.<String>emptyList(), "M4"));

        List<Map<String, Object>> graph = new ArrayList<>();
        graph.add(edge("M1", "X", "C", "DATA"));
        graph.add(edge("M2", "Y", "C", "DATA"));
        graph.add(edge("M2", "X", "C", "DATA"));
        graph.add(edge("M3", "Z", "C", "DATA"));
        graph.add(edge("M4", "W", "C", "DATA"));
        graph.add(edge("M1", "P", "G", "GUARD"));
        graph.add(edge("M2", "Q", "G", "GUARD"));
        graph.add(edge("M2", "P", "G", "GUARD"));
        graph.add(edge("M3", "R", "G", "GUARD"));
        graph.add(edge("M4", "S", "G", "GUARD"));
        graph.add(graph.get(2));
        program.graph = graph;

        Class<?> type = Class.forName(RuntimeSelectedRegionFinalizer.class
                .getName() + "$RegionDemandIndex");
        Constructor<?> constructor = type.getDeclaredConstructor(
                StaticProgram.class, StaticScopeMap.class, List.class);
        constructor.setAccessible(true);
        Object index = constructor.newInstance(program, StaticScopeMap.empty(),
                Collections.emptyList());
        Method incoming = type.getDeclaredMethod("incomingCells",
                String.class, String.class);
        Method guards = type.getDeclaredMethod("guardCells",
                String.class, String.class);
        incoming.setAccessible(true);
        guards.setAccessible(true);

        assertEquals(Arrays.asList("X", "Y", "Z"),
                incoming.invoke(index, "o1", "C"));
        assertEquals(Arrays.asList("Y", "X", "Z"),
                incoming.invoke(index, "o2", "C"));
        assertEquals(Arrays.asList("X", "Y"),
                incoming.invoke(index, "o3", "C"));
        assertEquals(Collections.emptyList(),
                incoming.invoke(index, "o4", "C"));
        assertEquals(Arrays.asList("P", "Q", "R"),
                guards.invoke(index, "o1", "G"));
        assertEquals(Arrays.asList("Q", "P", "R"),
                guards.invoke(index, "o2", "G"));
        assertEquals(Arrays.asList("P", "Q"),
                guards.invoke(index, "o3", "G"));
        assertEquals(Collections.emptyList(),
                guards.invoke(index, "o4", "G"));

        // Both bounded caches must evict these first queries.  Rebuilding
        // their shared region projection must keep the same source order and
        // the later-edge OR that makes X and P live in o1.
        for (int i = 0; i < 8200; i++) {
            incoming.invoke(index, "o1", "unused-" + i);
        }
        Field projection = type.getDeclaredField("localRegionProjection");
        projection.setAccessible(true);
        assertEquals(4096, ((Map<?, ?>) projection.get(index)).size());
        assertEquals(Arrays.asList("X", "Y", "Z"),
                incoming.invoke(index, "o1", "C"));
    }

    private static StaticProgram.RegionRow skeleton(String id,
                                                     String... methods) {
        Map<String, Object> row = row("schemaVersion",
                RuntimeSelectedRegionFinalizer.REGION_SCHEMA_VERSION,
                "kind", RuntimeSelectedRegionFinalizer.SKELETON_KIND,
                "regionId", id, "rootMethod", methods[0],
                "anchorMethod", methods[0], "methods", Arrays.asList(methods));
        return StaticProgram.regionRows(Collections.singletonList(row),
                RuntimeSelectedRegionFinalizer.SKELETON_KIND, "fixture")
                .get(0);
    }

    private static Map<String, Object> activation(String region,
            List<String> folded, String... methods) {
        return row("regionId", region,
                RuntimeSelectedRegionFinalizer.FOLDED_REGION_IDS, folded,
                "observedMethods", Arrays.asList(methods));
    }

    private static Map<String, Object> edge(String method, String from,
            String to, String transfer) {
        return row("method", method, "fromCell", from, "toCell", to,
                "transferKind", transfer, "siteId", to);
    }

    private static Map<String, Object> row(Object... fields) {
        Map<String, Object> row = new LinkedHashMap<>();
        for (int index = 0; index < fields.length; index += 2) {
            row.put((String) fields[index], fields[index + 1]);
        }
        return row;
    }
}
