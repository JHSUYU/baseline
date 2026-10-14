package edu.uva.liftlab.mallory.graphchecker.runtime;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import org.junit.Test;

/** Repeated failed entries carry no causal edge and need one bounded diagnostic. */
public final class UnattributedRegionGapTest {
    @Test public void coalescesOnlyUnattributedRegionWithinWindow() throws Exception {
        Path trace = Files.createTempFile("mallory-unattributed-region-", ".jsonl");
        Process process = new ProcessBuilder(
                System.getProperty("java.home") + "/bin/java", "-cp",
                System.getProperty("java.class.path"),
                UnattributedRegionGapFixture.class.getName(), trace.toString())
                .inheritIO().start();
        assertEquals(0, process.waitFor());
        List<String> lines = Files.readAllLines(trace, StandardCharsets.UTF_8);
        int region = 0, aggregate = 0, other = 0;
        long suppressed = 0;
        for (String line : lines) {
            JsonObject row = JsonParser.parseString(line).getAsJsonObject();
            if (!"GAP".equals(row.get("kind").getAsString())) continue;
            String kind = row.get("gapKind").getAsString();
            if ("UNATTRIBUTED_REGION".equals(kind)) region++;
            if ("UNATTRIBUTED_REGION_COALESCED".equals(kind)) {
                aggregate++;
                suppressed += row.get("suppressedCount").getAsLong();
            }
            if ("WIRE_HEADER_MISSING".equals(kind)) other++;
        }
        assertEquals(1, region);
        assertEquals(1, aggregate);
        assertEquals(49, suppressed);
        assertEquals(2, other);
        assertTrue(lines.get(lines.size()-1).contains("WINDOW_CLOSE"));
    }
}
