package edu.uva.liftlab.mallory.staticfrontier;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import org.junit.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

public class StaticFrontierTest {
    @Test
    public void targetAndControlAndCallersAreIdentified() throws Exception {
        String source = new String(Files.readAllBytes(Paths.get(
                "src/test/java/edu/uva/liftlab/mallory/staticfrontier/Fixture.java")),
                StandardCharsets.UTF_8);
        int line = 1;
        for (String text : source.split("\\n", -1)) {
            if (text.contains("TARGET_MISSING_KEY")) break;
            line++;
        }
        JsonObject target = new JsonObject();
        target.addProperty("class", Fixture.class.getName());
        target.addProperty("method", "check");
        target.addProperty("line", line);
        target.addProperty("line_start", line - 1);
        target.addProperty("line_end", line + 1);
        target.addProperty("exception", "IllegalStateException");
        JsonObject analysis = new JsonObject();
        JsonArray dirs = new JsonArray();
        dirs.add("target/test-classes");
        analysis.add("process_dirs", dirs);
        JsonArray classpath = new JsonArray();
        classpath.add("target/test-classes");
        analysis.add("classpath", classpath);
        JsonObject config = new JsonObject();
        config.addProperty("case_id", "fixture");
        config.add("target", target);
        config.add("analysis", analysis);
        JsonObject result = StaticFrontier.analyze(config);
        assertEquals("conservative_static_frontier",
                result.get("analysis_kind").getAsString());
        assertEquals(line, result.getAsJsonObject("target").get("line").getAsInt());
        assertTrue(hasEvidence(result, "declared_target"));
        assertTrue(hasEvidence(result, "control_postdom_may"));
        assertTrue(hasEvidence(result, "call_return_may"));
        assertTrue(hasEvidence(result, "field_name_may_writer"));
        assertTrue(result.getAsJsonArray("gaps").toString()
                .contains("jimple_only_site_ids_require_runtime_bytecode_mapping"));
    }

    private static boolean hasEvidence(JsonObject result, String evidence) {
        for (com.google.gson.JsonElement item : result.getAsJsonArray("frontier")) {
            for (com.google.gson.JsonElement reason : item.getAsJsonObject()
                    .getAsJsonArray("evidence")) {
                if (evidence.equals(reason.getAsString())) return true;
            }
        }
        return false;
    }
}
