package edu.uva.liftlab.crashfuzz.staticselection;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import org.junit.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.lang.reflect.Method;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

public class CoarseSelectorTest {
    private static final String PREFIX = "edu.uva.liftlab.crashfuzz.staticselection.SelectionFixture";

    @Test public void smallerLaterPhaseCannotGrowAnAlreadyFullSelection() throws Exception {
        Map<String, String> selected = new LinkedHashMap<>();
        selected.put("first", "prior phase");
        selected.put("second", "prior phase");
        Set<String> gaps = new LinkedHashSet<>();
        Method add = CoarseSelector.class.getDeclaredMethod("add", Map.class,
                String.class, String.class, int.class, Set.class);
        add.setAccessible(true);
        add.invoke(null, selected, "third", "later phase", 1, gaps);
        assertEquals(2, selected.size());
    }

    @Test public void neverExceedsMethodBudgetAcrossSelectionPhases() {
        JsonObject input = new JsonObject();
        input.addProperty("target_method", "<" + PREFIX + "$Reader: void check()>");
        JsonObject analysis = new JsonObject();
        JsonArray dirs = new JsonArray();
        dirs.add("target/test-classes");
        analysis.add("process_dirs", dirs);
        analysis.add("classpath", new JsonArray());
        analysis.addProperty("max_methods", 3);
        input.add("analysis", analysis);
        JsonObject result = CoarseSelector.analyze(input);
        assertTrue(result.getAsJsonArray("coverage_methods").size() <= 3);
    }

    @Test public void followsIoFromNestedWriterIntoItsOuterClass() {
        JsonObject input = new JsonObject();
        input.addProperty("target_method", "<" + PREFIX + "$WatchedReader: void check()>");
        JsonObject analysis = new JsonObject();
        JsonArray dirs = new JsonArray();
        dirs.add("target/test-classes");
        analysis.add("process_dirs", dirs);
        analysis.add("classpath", new JsonArray());
        analysis.addProperty("max_methods", 20);
        analysis.addProperty("max_callee_depth", 0);
        analysis.addProperty("max_jump_depth", 0);
        input.add("analysis", analysis);
        JsonObject result = CoarseSelector.analyze(input);
        assertTrue(result.getAsJsonArray("coverage_methods").toString()
                .contains("$WatchOwner: void fetch()"));
        assertTrue(result.getAsJsonArray("io_calls").toString()
                .contains("java.io.FileInputStream: int read()"));
    }

    @Test public void discoversTypedIoFailureFromSelectedCallee() {
        JsonObject input = new JsonObject();
        input.addProperty("target_method", "<" + PREFIX + "$ProtocolUser: void check()>");
        JsonObject analysis = new JsonObject();
        JsonArray dirs = new JsonArray();
        dirs.add("target/test-classes");
        analysis.add("process_dirs", dirs);
        analysis.add("classpath", new JsonArray());
        JsonArray io = new JsonArray();
        io.add(PREFIX + "$Protocol");
        analysis.add("io_patterns", io);
        input.add("analysis", analysis);
        JsonObject result = CoarseSelector.analyze(input);
        boolean found = false;
        for (com.google.gson.JsonElement element : result.getAsJsonArray("io_calls")) {
            JsonObject row = element.getAsJsonObject();
            if (row.get("callee").getAsString().contains("$Protocol: int read()")) {
                assertTrue(row.getAsJsonArray("exception_candidates").toString()
                        .contains("$ProtocolException"));
                found = true;
            }
        }
        assertTrue(found);
    }

    @Test public void followsFieldTaskAndDeclaredRpcJumps() throws Exception {
        Path mapping = Files.createTempFile("crashfuzz-wire-", ".jsonl");
        try {
            String producer = "<" + PREFIX + "$RpcProducer: void send()>";
            String consumer = "<" + PREFIX + "$Reader: void check()>";
            JsonObject row = new JsonObject();
            row.addProperty("schemaVersion", 2);
            row.addProperty("kind", "WIRE_FLOW");
            row.addProperty("id", "fixture-wire");
            JsonObject from = new JsonObject();
            from.addProperty("method", producer);
            JsonObject to = new JsonObject();
            to.addProperty("method", consumer);
            row.add("producer", from);
            row.add("consumer", to);
            Files.write(mapping, (row.toString() + "\n").getBytes(StandardCharsets.UTF_8));

            JsonObject input = new JsonObject();
            input.addProperty("target_method", consumer);
            JsonObject analysis = new JsonObject();
            JsonArray dirs = new JsonArray();
            dirs.add("target/test-classes");
            analysis.add("process_dirs", dirs);
            analysis.add("classpath", new JsonArray());
            JsonArray mappings = new JsonArray();
            mappings.add(mapping.toString());
            analysis.add("rpc_mapping_files", mappings);
            input.add("analysis", analysis);
            JsonObject result = CoarseSelector.analyze(input);
            String selected = result.getAsJsonArray("coverage_methods").toString();
            assertTrue(selected.contains("$Writer: void run()"));
            assertTrue(selected.contains("$MapWriter: void update()"));
            assertTrue(selected.contains("$Wrapper: void install()"));
            assertTrue(selected.contains("$RpcHandler: void receive()"));
            String heartbeat = "<" + PREFIX + "$Actor: void sendHeartbeat()>";
            assertTrue(selected.contains(heartbeat));
            assertTrue(result.getAsJsonObject("selection_reasons").get(heartbeat)
                    .getAsString().startsWith("target_actor_io_family")
                    || result.getAsJsonObject("selection_reasons").get(heartbeat)
                    .getAsString().startsWith("target_writer_actor_callee"));
            assertTrue(selected.contains("$Launcher: void launch("));
            assertTrue(selected.contains("$RpcProducer: void send()"));
            assertTrue(result.getAsJsonArray("io_calls").toString()
                    .contains("java.io.FileOutputStream: void write(int)"));
        } finally {
            Files.deleteIfExists(mapping);
        }
    }
}
