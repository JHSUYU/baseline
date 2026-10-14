package edu.uva.liftlab.graphchecker.plan;

import edu.uva.liftlab.graphchecker.contract.Clock;
import org.junit.Test;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;

/** Checks innermost ownership, including incomparable and equal-size regions. */
public final class StaticScopeOwnershipTest {
    private static final String A = "<example.A: void a()>";
    private static final String B = "<example.B: void b()>";
    private static final String C = "<example.C: void c()>";
    private static final String D = "<example.D: void d()>";

    private static Map<String, Object> region(String id, String... methods) {
        Map<String, Object> row = new LinkedHashMap<String, Object>();
        row.put("regionId", id);
        row.put("methods", Arrays.asList(methods));
        return row;
    }

    private static Map<String, Object> edge(String kind, String method,
                                             int index) {
        Map<String, Object> row = new LinkedHashMap<String, Object>();
        row.put("kind", kind);
        row.put("method", method);
        row.put("unitIndex", index);
        return row;
    }

    @Test
    public void preservesNestedSiblingEqualAndUnheldAuthorities() {
        List<Map<String, Object>> regions = Arrays.asList(
                region("outer", A, B, C),
                region("inner", A),
                region("equal", A),
                region("sibling", A, C));
        List<Map<String, Object>> edges = new ArrayList<Map<String, Object>>();
        edges.add(edge("exception_throw", A, 1));
        edges.add(edge("exception_throw", B, 2));
        Map<String, Object> unheldRoot = edge("call_return", D, 3);
        unheldRoot.put("definitionSite", true);
        unheldRoot.put("fromCell", A + ".return");
        unheldRoot.put("toCell", D + "::result");
        edges.add(unheldRoot);

        List<String> owners = new ArrayList<String>();
        for (StaticScopeMap.Site site : StaticScopeMap.sites(edges, regions,
                Collections.<String, Clock>emptyMap(),
                (method, unit, callee) -> null,
                (site, cell) -> null, value -> false,
                value -> SharedFieldFlow.TrackedKind.NONE,
                value -> false, value -> false)) {
            owners.add(site.role + ":" + site.regionId);
        }
        assertEquals(Arrays.asList("TARGET_SITE:inner", "TARGET_SITE:equal",
                "TARGET_SITE:outer", "ROOT_SITE:"), owners);
    }
}
