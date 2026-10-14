package edu.uva.liftlab.graphchecker.plan;

import com.google.gson.JsonObject;
import org.junit.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertSame;

public final class StaticScopeMapDeclaredIndexTest {
    private static JsonObject row(String role, String siteId, String callee,
                                  String region, String edge, String cell,
                                  boolean declared) {
        JsonObject result = new JsonObject();
        result.addProperty("schemaVersion", 1);
        result.addProperty("kind", StaticScopeMap.SITE_KIND);
        result.addProperty("role", role);
        result.addProperty("siteId", siteId);
        result.addProperty("declaredCallee", callee);
        result.addProperty("regionId", region);
        result.addProperty("cell", cell);
        if (declared) {
            result.addProperty("declaredKind", StaticScopeMap.CALL_RETURN);
            result.addProperty("edgeId", edge);
            result.addProperty("dependencyCell", "dependency");
        }
        return result;
    }

    /** The pre-index full scan is the semantic oracle, including its exact
     *  candidate-edge deduplication key and first-wins publication order. */
    private static List<StaticScopeMap.Site> fullScan(StaticScopeMap map,
                                                      String siteId,
                                                      String callee) {
        String named = siteId == null ? "" : siteId;
        String called = callee == null ? "" : callee;
        List<StaticScopeMap.Site> found = new ArrayList<>();
        Set<String> seen = new LinkedHashSet<>();
        for (StaticScopeMap.Site site : map.declaredSites()) {
            if (named.equals(site.siteId) && called.equals(site.declaredCallee)
                    && seen.add(site.declared.kind + "|" + site.declared.edgeId
                            + "|" + site.cell + "|"
                            + site.declared.dependencyCell)) {
                found.add(site);
            }
        }
        return found;
    }

    @Test
    public void indexedLookupPreservesFullScanOrderAndDeduplication() throws Exception {
        List<JsonObject> rows = Arrays.asList(
                row(StaticScopeMap.DECLARED_SITE, "A", "call", "r1", "e1", "c", true),
                row(StaticScopeMap.DECLARED_SITE, "B", "call", "r2", "e2", "c", true),
                row(StaticScopeMap.DECLARED_SITE, "A", "other", "r3", "e3", "c", true),
                row(StaticScopeMap.DECLARED_SITE, "A", "call", "r4", "e1", "c", true),
                row(StaticScopeMap.DECLARED_SITE, "A", "call", "r5", "e4", "c", true),
                row(StaticScopeMap.WRITE_SITE, "A", "call", "r6", "e5", "c", true),
                row(StaticScopeMap.DECLARED_SITE, "A", "call", "r7", "e6", "c", false),
                row(StaticScopeMap.DECLARED_SITE, "", "", "r8", "e7", "c", true));
        StringBuilder content = new StringBuilder();
        for (JsonObject row : rows) content.append(row).append('\n');
        Path directory = Files.createTempDirectory("declared-sites-index-");
        Path file = directory.resolve(StaticScopeMap.FILE);
        byte[] source = content.toString().getBytes(StandardCharsets.UTF_8);
        Files.write(file, source);
        StaticScopeMap map = StaticScopeMap.read(file);
        assertArrayEquals(source, Files.readAllBytes(file));
        for (String[] query : new String[][]{{"A", "call"}, {"A", "other"},
                {"B", "call"}, {"missing", "call"}, {null, null}}) {
            List<StaticScopeMap.Site> expected = fullScan(map, query[0], query[1]);
            List<StaticScopeMap.Site> actual = map.declaredSitesAt(query[0], query[1]);
            assertEquals(expected.size(), actual.size());
            for (int i = 0; i < expected.size(); i++) {
                assertSame(expected.get(i), actual.get(i));
            }
        }
        List<StaticScopeMap.Site> first = map.declaredSitesAt("A", "call");
        assertEquals("r1", first.get(0).regionId);
        assertEquals("r5", first.get(1).regionId);
        first.clear();
        assertEquals(2, map.declaredSitesAt("A", "call").size());
    }
}
