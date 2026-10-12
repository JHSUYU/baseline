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
import java.util.Collections;
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

    @Test public void boundedWriterFanoutKeepsDirectIoCaller() throws Exception {
        String writer = "<example.Actor: void write()>";
        String ordinary = "<example.Actor: void alpha()>";
        String io = "<example.RemoteActor: void zetaIo()>";
        Map<String, String> selected = new LinkedHashMap<>();
        selected.put(writer, "writer");
        Map<String, Set<String>> callers = new LinkedHashMap<>();
        Set<String> possibilities = new LinkedHashSet<>();
        possibilities.add(ordinary);
        possibilities.add(io);
        callers.put(writer, possibilities);
        Method select = CoarseSelector.class.getDeclaredMethod("extendWriterCallers",
                Map.class, Set.class, Map.class, Set.class, int.class, int.class,
                int[].class, int.class, Set.class);
        select.setAccessible(true);
        select.invoke(null, selected, Collections.singleton(writer), callers,
                Collections.singleton(io), 1, 1, new int[] {2}, 2,
                new LinkedHashSet<String>());
        assertEquals(2, selected.size());
        assertTrue(selected.containsKey(io));
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

    @Test public void reportsTargetThrowAndItsControllingBranch() {
        String target = "<" + PREFIX + "$ThrowLineReader: void check()>";
        JsonObject input = new JsonObject();
        input.addProperty("target_method", target);
        JsonObject analysis = new JsonObject();
        JsonArray dirs = new JsonArray();
        dirs.add("target/test-classes");
        analysis.add("process_dirs", dirs);
        analysis.add("classpath", new JsonArray());
        input.add("analysis", analysis);
        JsonObject result = CoarseSelector.analyze(input);
        JsonArray sites = result.getAsJsonArray("target_throw_sites");
        boolean found = false;
        for (com.google.gson.JsonElement element : sites) {
            JsonObject site = element.getAsJsonObject();
            if (!"java.lang.IllegalStateException".equals(
                    site.get("thrown_type").getAsString())) continue;
            assertEquals(target, site.get("method").getAsString());
            assertTrue(site.get("line").getAsInt() > 0);
            assertTrue(site.getAsJsonArray("controlled_by").size() >= 1);
            String branchId = site.getAsJsonArray("controlled_by").get(0)
                    .getAsString();
            assertTrue(branchId.startsWith(target + "#u"));
            assertTrue(site.has("soot_site_id"));
            boolean branchFound = false;
            for (com.google.gson.JsonElement branch : result.getAsJsonArray("branches")) {
                JsonObject check = branch.getAsJsonObject();
                if (branchId.equals(check.get("site_id").getAsString())) {
                    assertTrue(check.get("line").getAsInt() < site.get("line").getAsInt());
                    branchFound = true;
                }
            }
            assertTrue(branchFound);
            found = true;
        }
        assertTrue(found);
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

    @Test public void followsMappedWireProducerToSendingIoBoundary() throws Exception {
        Path mapping = Files.createTempFile("crashfuzz-wire-sender-", ".jsonl");
        try {
            String producer = "<" + PREFIX + "$WireValueSource: int encode()>";
            String consumer = "<" + PREFIX + "$WireTarget: void check(boolean)>";
            JsonObject row = new JsonObject();
            row.addProperty("schemaVersion", 2);
            row.addProperty("kind", "WIRE_FLOW");
            row.addProperty("id", "fixture-sender");
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
            analysis.addProperty("max_methods", 100);
            input.add("analysis", analysis);

            JsonObject result = CoarseSelector.analyze(input);
            String sender = "<" + PREFIX + "$WireSender: int sixth()>";
            assertTrue(result.getAsJsonObject("selection_reasons").has(sender));
            assertTrue(result.getAsJsonObject("selection_reasons").get(sender)
                    .getAsString().startsWith("rpc_wire_sender_direct_io_caller_depth_6"));
            assertTrue(result.getAsJsonArray("io_calls").toString()
                    .contains("java.io.FileOutputStream: void write(int)"));
            assertTrue(result.getAsJsonArray("coverage_methods").size() <= 100);
        } finally {
            Files.deleteIfExists(mapping);
        }
    }
}
