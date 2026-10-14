package edu.uva.liftlab.graphchecker.plan;

import com.google.gson.JsonObject;
import org.junit.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;

public final class StaticScopeMapWriteSitesTest {
    private static JsonObject write(String siteId, String region,
                                    String cell, String carrier) {
        JsonObject row = new JsonObject();
        row.addProperty("schemaVersion", 1);
        row.addProperty("kind", StaticScopeMap.SITE_KIND);
        row.addProperty("role", StaticScopeMap.WRITE_SITE);
        row.addProperty("siteId", siteId);
        row.addProperty("regionId", region);
        row.addProperty("cell", cell);
        row.addProperty("carrier", carrier);
        return row;
    }

    private static List<String> names(List<StaticScopeMap.Site> sites) {
        List<String> result = new ArrayList<>();
        for (StaticScopeMap.Site site : sites) result.add(site.siteId);
        return result;
    }

    @Test
    public void oneSiteAppearsOnceWhenItsCellIsItsCarrier() throws Exception {
        Path path = Files.createTempDirectory("write-sites-")
                .resolve(StaticScopeMap.FILE);
        StringBuilder rows = new StringBuilder();
        for (JsonObject row : Arrays.asList(
                write("direct-1", "r1", "A", "A"),
                write("mutation", "r2", "B", "A"),
                write("direct-2", "r3", "A", "A"),
                write("carrier-only", "r4", "", "A"),
                write("unselected", "", "A", "A"))) {
            rows.append(row).append('\n');
        }
        Files.write(path, rows.toString().getBytes(StandardCharsets.UTF_8));
        Map<String, List<StaticScopeMap.Site>> byCell =
                StaticScopeMap.read(path).writeSitesByCell();
        assertEquals(Arrays.asList("direct-1", "mutation", "direct-2",
                "carrier-only"), names(byCell.get("A")));
        assertEquals(Arrays.asList("mutation"), names(byCell.get("B")));
        assertEquals(2, byCell.size());
    }
}
