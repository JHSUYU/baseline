package edu.uva.liftlab.graphchecker.causynth;

import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;
import org.junit.Test;

import static org.junit.Assert.assertEquals;

/** Cached adjacency must preserve summary invalidation and live call links. */
public class ReturnOnlyFormalsBodyCacheTest {
    private static final String ID =
            "<fx.Id: java.lang.String id(java.lang.String)>";
    private static final String CALLER =
            "<fx.Caller: java.lang.String call(java.lang.String)>";
    private static final String ID_ARG = ID + ".param0:java.lang.String";
    private static final String CALLER_ARG = CALLER + ".param0:java.lang.String";

    @Test public void cacheUpdateAndEvictionAgreeWithUncachedSummary()
            throws Exception {
        Fixture cached = new Fixture(16, 2);
        Fixture evicting = new Fixture(2, 1);
        Fixture uncached = new Fixture(0, 0);
        for (Fixture fixture : Arrays.asList(cached, evicting, uncached)) {
            fixture.relevant.put(ID, set(ID_ARG));
            fixture.relevant.put(CALLER, set(CALLER_ARG));
            fixture.flow.row(row("local_def_use", ID_ARG, ID + ".return", -1));
            fixture.flow.row(row("call_return", ID + ".return",
                    CALLER + ".return", 4));
            fixture.flow.row(row("call_argument", CALLER_ARG, ID_ARG, 4));
        }
        assertDemand(false, cached, evicting, uncached);
        for (Fixture fixture : Arrays.asList(cached, evicting, uncached)) {
            // A newly observed effect invalidates the callee's return-only
            // summary. The caller's call-result link must then disappear.
            fixture.flow.row(row("field_write", ID_ARG,
                    "<fx.Id: java.lang.String visible>", -1));
        }
        assertDemand(true, cached, evicting, uncached);
    }

    private static void assertDemand(boolean expected, Fixture... fixtures) {
        for (Fixture fixture : fixtures) {
            assertEquals(expected,
                    fixture.flow.demanded(ID, ID_ARG, false, CALLER));
            assertEquals(expected,
                    fixture.flow.demanded(CALLER, CALLER_ARG, false, "root"));
        }
    }

    private static Set<String> set(String cell) {
        Set<String> result = new LinkedHashSet<>();
        result.add(cell);
        return result;
    }

    private static Map<String, Object> row(String kind, String from,
                                           String to, int unitIndex) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("kind", kind);
        row.put("fromCell", from);
        row.put("toCell", to);
        row.put("unitIndex", unitIndex);
        return row;
    }

    private static final class Fixture implements ReturnOnlyFormals.Slice {
        final Map<String, Set<String>> relevant = new LinkedHashMap<>();
        final ReturnOnlyFormals flow;

        Fixture(int maxRows, int maxMethods) {
            flow = new ReturnOnlyFormals(this, maxRows, maxMethods);
        }

        @Override public Set<String> relevant(String method) {
            return relevant.getOrDefault(method, new LinkedHashSet<String>());
        }

        @Override public String thisCell(String method) { return null; }

        @Override public void requeue(String method) { }
    }
}
