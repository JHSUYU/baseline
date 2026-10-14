package edu.uva.liftlab.graphchecker.causynth;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertSame;

public final class StaticProgramRegionMethodIndexTest {
    @Test
    public void filtersEachRegionInOriginalGraphOrderIncludingDuplicates() {
        StaticProgram program = new StaticProgram();
        program.skeletons.put("r1", skeleton("r1", "A", "B"));
        program.skeletons.put("r2", skeleton("r2", "A"));
        Map<String, Object> first = row("method", "A", "siteId", "a1");
        Map<String, Object> second = row("method", "B", "siteId", "b1");
        Map<String, Object> third = row("method", "A", "siteId", "a2");
        program.graph = Arrays.asList(first, second, third, third);

        for (String region : Arrays.asList("r1", "r2", "unknown")) {
            for (String method : Arrays.asList("A", "B", "unknown")) {
                List<Map<String, Object>> expected = new ArrayList<>();
                for (Map<String, Object> edge : program.regionGraph(region)) {
                    if (method.equals(MapFields.text(edge.get("method")))) {
                        expected.add(edge);
                    }
                }
                List<Map<String, Object>> actual =
                        program.regionGraphInMethod(region, method);
                assertEquals(region + "/" + method, expected, actual);
                for (int i = 0; i < expected.size(); i++) {
                    assertSame(expected.get(i), actual.get(i));
                }
            }
        }
        assertEquals(Arrays.asList(first, third, third),
                program.regionGraphInMethod("r1", "A"));
        assertEquals(Arrays.asList(first, third, third),
                program.regionGraphInMethod("r2", "A"));
        assertEquals(Collections.singletonList(second),
                program.regionGraphInMethod("r1", "B"));
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

    private static Map<String, Object> row(Object... fields) {
        Map<String, Object> row = new LinkedHashMap<>();
        for (int i = 0; i < fields.length; i += 2) {
            row.put((String) fields[i], fields[i + 1]);
        }
        return row;
    }
}
