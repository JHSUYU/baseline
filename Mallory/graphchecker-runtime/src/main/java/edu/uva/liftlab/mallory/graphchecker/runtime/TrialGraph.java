package edu.uva.liftlab.mallory.graphchecker.runtime;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Consumer;
import java.util.zip.GZIPInputStream;

/**
 * The WaveGraph NODE/WIRE/STATE join, adapted to Mallory's raw JUnit rows.
 * An edge needs a unique concrete producer. A name or timestamp alone is
 * insufficient evidence. Target closure is a backward walk over these edges.
 */
public final class TrialGraph {
    private final Map<String, JsonObject> nodes = new LinkedHashMap<>();
    private final Map<String, JsonObject> edges = new LinkedHashMap<>();
    private final Map<String, Long> nodeFirstSeq = new HashMap<>();
    private final Map<String, Integer> gaps = new LinkedHashMap<>();
    private final List<JsonObject> targets = new ArrayList<>();
    private final Map<String, Set<String>> doors = new LinkedHashMap<>();
    private final Map<String, List<CoverageEvent>> coverageRows = new LinkedHashMap<>();
    private final Map<String, List<JsonObject>> doorRows = new LinkedHashMap<>();

    private TrialGraph() { }

    public static TrialGraph read(Path trace) throws IOException {
        TrialGraph graph = new TrialGraph();
        if (!Files.isRegularFile(trace)) {
            graph.gap("TRACE_MISSING");
            return graph;
        }
        graph.accept(trace);
        return graph;
    }

    private void eachRow(Path trace, boolean countInvalid,
                         Consumer<JsonObject> consumer) throws IOException {
        try (InputStream raw = Files.newInputStream(trace);
             InputStream input = trace.toString().endsWith(".gz")
                     ? new GZIPInputStream(raw) : raw;
             BufferedReader reader = new BufferedReader(new InputStreamReader(
                     input, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.trim().isEmpty()) continue;
                JsonObject row;
                try { row = new JsonParser().parse(line).getAsJsonObject(); }
                catch (RuntimeException invalid) {
                    if (countInvalid) gap("TRACE_ROW_INVALID");
                    continue;
                }
                consumer.accept(row);
            }
        }
    }

    private void accept(Path trace) throws IOException {
        Map<String, List<JsonObject>> exports = new HashMap<>();
        Map<String, List<JsonObject>> writes = new HashMap<>();
        Map<String, List<JsonObject>> reads = new HashMap<>();
        eachRow(trace, true, row -> {
            String kind = value(row, "kind");
            if ("ACTIVATION".equals(kind) || "SCOPE_ENTER".equals(kind)
                    || "TASK_CLAIM".equals(kind) || "SOURCE_SWITCH".equals(kind)) node(row);
            if ("TARGET_CHECK".equals(kind) || "TARGET_THROW".equals(kind)) {
                targets.add(row);
                node(row);
            }
            if ("EXPORT".equals(kind)) {
                put(exports, value(row, "producerEndpointId"), row);
                node(row);
            }
            if ("WRITE".equals(kind)) {
                put(writes, value(row, "locationVersion"), row);
                node(row);
            }
            if ("READ".equals(kind)) {
                put(reads, value(row, "readerEndpointId"), row);
                node(row);
            }
            if ("GAP".equals(kind)) gap(value(row, "gapKind"));
            if ("COVERAGE".equals(kind)) {
                String occurrence = value(row, "occurrenceId");
                String site = value(row, "siteId");
                if (occurrence.isEmpty() || site.isEmpty()) gap("COVERAGE_UNATTRIBUTED");
                else {
                    coverageRows.computeIfAbsent(occurrence,
                            unused -> new ArrayList<>()).add(new CoverageEvent(
                                    site, number(row, "seq")));
                }
            }
            if ("FAULT_DOOR".equals(kind)) {
                String occurrence = value(row, "occurrenceId");
                String site = value(row, "siteId");
                if (occurrence.isEmpty() || site.isEmpty()) gap("FAULT_DOOR_UNATTRIBUTED");
                else {
                    doors.computeIfAbsent(occurrence,
                            unused -> new LinkedHashSet<>()).add(site);
                    doorRows.computeIfAbsent(occurrence,
                            unused -> new ArrayList<>()).add(row);
                }
            }
        });
        eachRow(trace, false, row -> {
            String kind = value(row, "kind");
            if ("ATTACH".equals(kind)) {
                node(row);
                String producerId = value(row, "producerEndpointId");
                List<JsonObject> matched = exports.getOrDefault(producerId,
                        Collections.emptyList());
                if (matched.size() != 1) {
                    gap(matched.isEmpty() ? "WIRE_EXPORT_MISSING" :
                            "WIRE_EXPORT_AMBIGUOUS");
                    return;
                }
                JsonObject export = matched.get(0);
                if (!same(row, export, "transport", "correlationId", "attemptId", "half")
                        || !value(row, "producerOccurrenceId").equals(
                                value(export, "occurrenceId"))
                        || !value(row, "producer").equals(value(export, "producer"))) {
                    gap("WIRE_EXPORT_MISMATCH");
                    return;
                }
                long exportSeq = number(export, "seq");
                long attachSeq = number(row, "seq");
                if (exportSeq >= 0 && attachSeq >= 0 && exportSeq >= attachSeq) {
                    gap("WIRE_ORDER_INVALID");
                    return;
                }
                edge("WIRE", export, row, "producerEndpointId",
                        "consumerEndpointId", value(row, "transport") + "."
                                + value(row, "half"));
            } else if ("READ".equals(kind)) {
                String location = value(row, "locationVersion");
                List<JsonObject> matched = writes.getOrDefault(location,
                        Collections.emptyList());
                if (matched.size() != 1) {
                    gap(matched.isEmpty() ? "STATE_WRITE_MISSING" :
                            "STATE_WRITE_AMBIGUOUS");
                    return;
                }
                JsonObject write = matched.get(0);
                if (!value(row, "writerEndpointId").equals(
                        value(write, "writerEndpointId"))
                        || !value(row, "writerOccurrenceId").equals(
                                value(write, "occurrenceId"))
                        || number(write, "seq") >= number(row, "seq")) {
                    gap("STATE_WRITE_MISMATCH");
                    return;
                }
                edge("STATE", write, row, "writerEndpointId",
                        "readerEndpointId", location.split("\\n", 2)[0]);
            } else if ("QUEUE_CONSUMED".equals(kind)) {
                node(row);
                String readerId = value(row, "readEndpointId");
                List<JsonObject> matched = reads.getOrDefault(readerId,
                        Collections.emptyList());
                if (readerId.isEmpty() || matched.size() != 1) {
                    gap(matched.isEmpty() ? "QUEUE_READ_MISSING" :
                            "QUEUE_READ_AMBIGUOUS");
                    return;
                }
                JsonObject read = matched.get(0);
                if (!same(row, read, "locationVersion", "writerEndpointId",
                        "writerOccurrenceId")
                        || !value(row, "readOccurrenceId").equals(
                                value(read, "occurrenceId"))
                        || number(read, "seq") >= number(row, "seq")) {
                    gap("QUEUE_READ_MISMATCH");
                    return;
                }
                edge("HANDOFF", read, row, "readerEndpointId",
                        "consumerEndpointId", value(row, "transport") + ".QUEUE");
            }
        });
        eachRow(trace, false, row -> {
            if (!"ACTIVATION".equals(value(row, "kind"))) return;
            String parent = value(row, "parentOccurrenceId");
            String child = value(row, "occurrenceId");
            if (parent.isEmpty()) return; // older rows lack explicit scope parent
            JsonObject parentNode = nodes.get(parent);
            JsonObject childNode = nodes.get(child);
            if (parentNode == null || childNode == null
                    || !value(parentNode, "occurrence").equals(
                            value(row, "parentOccurrence"))
                    || !value(parentNode, "node").equals(value(childNode, "node"))
                    || nodeFirstSeq.getOrDefault(parent, Long.MAX_VALUE)
                            >= number(row, "seq")) {
                gap("SCOPE_PARENT_UNPROVEN");
                return;
            }
            JsonObject local = new JsonObject();
            local.addProperty("kind", "EDGE");
            local.addProperty("edge", "SCOPE");
            local.addProperty("edgeId", digest("SCOPE" + parent + child));
            local.addProperty("producerOccurrenceId", parent);
            local.addProperty("consumerOccurrenceId", child);
            local.addProperty("producerEndpointId", parent + ":scope");
            local.addProperty("consumerEndpointId", child + ":entry");
            local.addProperty("port", "scope.parent");
            local.addProperty("producerSeq", number(row, "seq"));
            local.addProperty("consumerSeq", number(row, "seq"));
            edges.put(value(local, "edgeId"), local);
        });
        eachRow(trace, false, row -> {
            if (!"REGION_COMPLETE".equals(value(row, "kind"))) return;
            String child = value(row, "occurrenceId");
            String parent = value(row, "parentOccurrenceId");
            JsonObject childNode = nodes.get(child);
            JsonObject parentNode = nodes.get(parent);
            long when = number(row, "seq");
            if (child.isEmpty() || parent.isEmpty()
                    || childNode == null || parentNode == null
                    || !value(childNode, "instrumented").equals("true")
                    || !value(childNode, "occurrence").equals(
                            value(row, "occurrence"))
                    || !value(parentNode, "occurrence").equals(
                            value(row, "parentOccurrence"))
                    || !value(parentNode, "node").equals(value(childNode, "node"))
                    || nodeFirstSeq.getOrDefault(child, Long.MAX_VALUE) >= when
                    || nodeFirstSeq.getOrDefault(parent, Long.MAX_VALUE) >= when) {
                gap("REGION_COMPLETE_UNPROVEN");
                return;
            }
            JsonObject returned = new JsonObject();
            returned.addProperty("kind", "EDGE");
            returned.addProperty("edge", "COMPLETION");
            returned.addProperty("edgeId", digest("COMPLETION" + child + parent + when));
            returned.addProperty("producerOccurrenceId", child);
            returned.addProperty("consumerOccurrenceId", parent);
            returned.addProperty("producerEndpointId", child + ":completion");
            returned.addProperty("consumerEndpointId", parent + ":resume");
            returned.addProperty("port", "scope.completion");
            returned.addProperty("producerSeq", when);
            returned.addProperty("consumerSeq", when);
            edges.put(value(returned, "edgeId"), returned);
        });
    }

    private static final class CoverageEvent {
        final String site;
        final long seq;
        CoverageEvent(String site, long seq) {
            this.site = site;
            this.seq = seq;
        }
    }

    private static void put(Map<String, List<JsonObject>> index, String key,
                            JsonObject row) {
        if (!key.isEmpty()) index.computeIfAbsent(key,
                unused -> new ArrayList<>()).add(row);
    }

    private void node(JsonObject trace) {
        String id = value(trace, "occurrenceId");
        if (id.isEmpty()) { gap("OCCURRENCE_MISSING"); return; }
        JsonObject row = nodes.get(id);
        if (row == null) {
            row = new JsonObject();
            row.addProperty("kind", "NODE");
            row.addProperty("occurrenceId", id);
            row.addProperty("occurrence", value(trace, "occurrence"));
            row.addProperty("node", value(trace, "node"));
            row.addProperty("regionId", value(trace, "regionId"));
            row.addProperty("instrumented", false);
            nodes.put(id, row);
            nodeFirstSeq.put(id, number(trace, "seq"));
        } else {
            long observed = number(trace, "seq");
            long first = nodeFirstSeq.getOrDefault(id, -1L);
            if (observed >= 0 && (first < 0 || observed < first)) {
                nodeFirstSeq.put(id, observed);
            }
        }
        if ("ACTIVATION".equals(value(trace, "kind"))) {
            row.addProperty("instrumented", true);
        }
    }

    private void edge(String kind, JsonObject producer, JsonObject consumer,
                      String producerField, String consumerField, String port) {
        String from = value(producer, "occurrenceId");
        String to = value(consumer, "occurrenceId");
        String p = value(producer, producerField);
        String c = value(consumer, consumerField);
        if (from.isEmpty() || to.isEmpty() || p.isEmpty() || c.isEmpty()) {
            gap(kind + "_ENDPOINT_MISSING");
            return;
        }
        String id = digest(kind + p + c);
        JsonObject row = new JsonObject();
        row.addProperty("kind", "EDGE");
        row.addProperty("edgeId", id);
        row.addProperty("edge", kind);
        row.addProperty("producerOccurrenceId", from);
        row.addProperty("consumerOccurrenceId", to);
        row.addProperty("producerEndpointId", p);
        row.addProperty("consumerEndpointId", c);
        row.addProperty("port", port);
        row.addProperty("producerSeq", number(producer, "seq"));
        row.addProperty("consumerSeq", number(consumer, "seq"));
        edges.put(id, row);
    }

    public Set<String> closure(String targetSite) {
        return closureResult(targetSite).nodes;
    }

    private ClosureResult closureResult(String targetSite) {
        Map<String, Long> latest = new LinkedHashMap<>();
        Deque<String> pending = new ArrayDeque<>();
        Set<String> usedEdges = new LinkedHashSet<>();
        for (JsonObject target : targets) {
            if (targetSite == null || targetSite.isEmpty()
                    || targetSite.equals(value(target, "siteId"))) {
                String id = value(target, "occurrenceId");
                if (id.isEmpty()) continue;
                long cutoff = number(target, "seq");
                if (cutoff < 0) cutoff = Long.MAX_VALUE;
                if (cutoff > latest.getOrDefault(id, Long.MIN_VALUE)) {
                    latest.put(id, cutoff);
                    pending.add(id);
                }
            }
        }
        Map<String, List<JsonObject>> incoming = new HashMap<>();
        for (JsonObject edge : edges.values()) {
            incoming.computeIfAbsent(value(edge, "consumerOccurrenceId"),
                    unused -> new ArrayList<>()).add(edge);
        }
        while (!pending.isEmpty()) {
            String consumer = pending.remove();
            long cutoff = latest.get(consumer);
            for (JsonObject edge : incoming.getOrDefault(consumer,
                    Collections.emptyList())) {
                long consumerSeq = number(edge, "consumerSeq");
                if (consumerSeq >= 0 && consumerSeq > cutoff) continue;
                usedEdges.add(value(edge, "edgeId"));
                String producer = value(edge, "producerOccurrenceId");
                long producerCutoff = number(edge, "producerSeq");
                if (producerCutoff < 0) producerCutoff = Long.MAX_VALUE;
                if (producerCutoff > latest.getOrDefault(producer, Long.MIN_VALUE)) {
                    latest.put(producer, producerCutoff);
                    pending.add(producer);
                }
            }
        }
        return new ClosureResult(new LinkedHashMap<>(latest), usedEdges);
    }

    private static final class ClosureResult {
        final Set<String> nodes;
        final Set<String> edges;
        final Map<String, Long> cutoffs;
        ClosureResult(Map<String, Long> cutoffs, Set<String> edges) {
            this.cutoffs = cutoffs;
            this.nodes = new LinkedHashSet<>(cutoffs.keySet());
            this.edges = edges;
        }
    }

    public JsonObject feedback(String targetSite, TrialGraph before) {
        return feedback(targetSite, before, null);
    }

    public JsonObject feedback(String targetSite, TrialGraph before,
                               StaticScope staticScope) {
        ClosureResult exact = closureResult(targetSite);
        Set<String> closure = exact.nodes;
        int targetChecks = 0;
        int targetThrows = 0;
        Set<String> thrownClasses = new LinkedHashSet<>();
        Set<String> checkOutcomes = new LinkedHashSet<>();
        for (JsonObject target : targets) {
            if (targetSite != null && !targetSite.isEmpty()
                    && !targetSite.equals(value(target, "siteId"))) continue;
            if (value(target, "occurrenceId").isEmpty()) continue;
            if ("TARGET_CHECK".equals(value(target, "kind"))) {
                targetChecks++;
                checkOutcomes.add(value(target, "outcome"));
            } else if ("TARGET_THROW".equals(value(target, "kind"))) {
                targetThrows++;
                thrownClasses.add(value(target, "exceptionClass"));
            }
        }
        Set<String> priorNodes = new HashSet<>();
        Set<String> priorEdges = new HashSet<>();
        if (before != null) {
            ClosureResult prior = before.closureResult(targetSite);
            for (String id : prior.nodes) priorNodes.add(before.nodeFamily(id));
            for (String id : prior.edges) {
                JsonObject edge = before.edges.get(id);
                if (edge != null) priorEdges.add(before.edgeFamily(edge));
            }
        }
        Set<String> closureEdges = exact.edges;
        Set<String> closureEdgeFamilies = new LinkedHashSet<>();
        Set<String> newEdgeFamilies = new HashSet<>();
        for (JsonObject edge : edges.values()) {
            if (closureEdges.contains(value(edge, "edgeId"))) {
                closureEdgeFamilies.add(edgeFamily(edge));
                if (!priorEdges.contains(edgeFamily(edge))) {
                    newEdgeFamilies.add(edgeFamily(edge));
                }
            }
        }
        Set<String> newNodeFamilies = new HashSet<>();
        Set<String> closureNodeFamilies = new LinkedHashSet<>();
        for (String id : closure) if (!priorNodes.contains(nodeFamily(id))) {
            newNodeFamilies.add(nodeFamily(id));
        }
        for (String id : closure) closureNodeFamilies.add(nodeFamily(id));
        Set<String> covered = new LinkedHashSet<>();
        for (Map.Entry<String, Long> entry : exact.cutoffs.entrySet()) {
            for (CoverageEvent event : coverageRows.getOrDefault(entry.getKey(),
                    Collections.emptyList())) {
                if (event.seq <= entry.getValue()) {
                    covered.add(event.site);
                }
            }
        }
        Set<String> closureDoors = new LinkedHashSet<>();
        for (Map.Entry<String, Long> entry : exact.cutoffs.entrySet()) {
            for (JsonObject event : doorRows.getOrDefault(entry.getKey(),
                    Collections.emptyList())) {
                if (number(event, "seq") <= entry.getValue()) {
                    closureDoors.add(value(event, "siteId"));
                }
            }
        }
        StaticScope.Result may = null;
        Set<String> mayObservedDoors = new LinkedHashSet<>();
        if (staticScope != null) {
            Set<String> closureRegions = new LinkedHashSet<>();
            for (String id : closure) closureRegions.add(
                    value(nodes.get(id), "regionId"));
            may = staticScope.mayReach(targetSite, closureRegions);
            for (Map.Entry<String, Set<String>> entry : doors.entrySet()) {
                if (!may.regions.contains(value(nodes.get(entry.getKey()), "regionId")))
                    continue;
                for (String site : entry.getValue()) {
                    if (may.doorSites.contains(site)) mayObservedDoors.add(site);
                }
            }
        }
        Set<String> previousCoverage = new HashSet<>();
        if (before != null) {
            ClosureResult prior = before.closureResult(targetSite);
            for (Map.Entry<String, Long> entry : prior.cutoffs.entrySet()) {
                for (CoverageEvent event : before.coverageRows.getOrDefault(entry.getKey(),
                        Collections.emptyList())) {
                    if (event.seq <= entry.getValue()) {
                        previousCoverage.add(event.site);
                    }
                }
            }
        }
        int newCoverage = 0;
        for (String site : covered) if (!previousCoverage.contains(site)) newCoverage++;
        JsonObject row = new JsonObject();
        row.addProperty("schemaVersion", 1);
        row.addProperty("targetSite", targetSite == null ? "" : targetSite);
        row.addProperty("targetReached", !closure.isEmpty());
        row.addProperty("targetChecks", targetChecks);
        row.addProperty("targetThrows", targetThrows);
        row.add("targetCheckOutcomes", new com.google.gson.Gson().toJsonTree(checkOutcomes));
        row.add("targetThrowClasses", new com.google.gson.Gson().toJsonTree(thrownClasses));
        row.addProperty("nodes", nodes.size());
        row.addProperty("edges", edges.size());
        row.addProperty("closureNodes", closure.size());
        row.addProperty("closureEdges", closureEdges.size());
        row.addProperty("newClosureNodes", newNodeFamilies.size());
        row.addProperty("newClosureEdges", newEdgeFamilies.size());
        row.addProperty("closureCoverageSites", covered.size());
        row.addProperty("newClosureCoverageSites", newCoverage);
        row.add("closureOccurrenceIds", new com.google.gson.Gson().toJsonTree(closure));
        row.add("closureOccurrenceCutoffs", new com.google.gson.Gson().toJsonTree(exact.cutoffs));
        row.add("closureEdgeIds", new com.google.gson.Gson().toJsonTree(closureEdges));
        row.add("closureNodeFamilies", new com.google.gson.Gson().toJsonTree(closureNodeFamilies));
        row.add("closureEdgeFamilies", new com.google.gson.Gson().toJsonTree(closureEdgeFamilies));
        row.add("closureCoverageSiteIds", new com.google.gson.Gson().toJsonTree(covered));
        row.add("closureDoorSiteIds", new com.google.gson.Gson().toJsonTree(closureDoors));
        if (may != null) {
            row.addProperty("staticScopeTargetFound", may.targetFound);
            row.add("staticMayRegionIds", new com.google.gson.Gson().toJsonTree(may.regions));
            row.add("staticMayDoorSiteIds", new com.google.gson.Gson().toJsonTree(may.doorSites));
            row.add("staticMayObservedDoorSiteIds", new com.google.gson.Gson().toJsonTree(mayObservedDoors));
            row.add("staticMayRelations", new com.google.gson.Gson().toJsonTree(may.relations));
        }
        row.add("gaps", new com.google.gson.Gson().toJsonTree(gaps));
        return row;
    }

    public void write(Path graphFile) throws IOException {
        List<String> rows = new ArrayList<>();
        for (JsonObject node : nodes.values()) rows.add(node.toString());
        for (JsonObject edge : edges.values()) rows.add(edge.toString());
        Path parent = graphFile.toAbsolutePath().getParent();
        if (parent != null) Files.createDirectories(parent);
        Files.write(graphFile, rows, StandardCharsets.UTF_8);
    }

    private String nodeFamily(String id) {
        JsonObject row = nodes.get(id);
        return row == null ? id : value(row, "node") + "\n"
                + value(row, "regionId");
    }

    private String edgeFamily(JsonObject edge) {
        return value(edge, "edge") + "\n" + value(edge, "port") + "\n"
                + nodeFamily(value(edge, "producerOccurrenceId")) + "\n"
                + nodeFamily(value(edge, "consumerOccurrenceId"));
    }

    private void gap(String kind) {
        gaps.merge(kind == null || kind.isEmpty() ? "UNKNOWN" : kind, 1,
                Integer::sum);
    }

    private static String value(JsonObject row, String field) {
        return row != null && row.has(field) && !row.get(field).isJsonNull()
                ? row.get(field).getAsString() : "";
    }

    private static long number(JsonObject row, String field) {
        try { return row.get(field).getAsLong(); }
        catch (RuntimeException invalid) { return -1; }
    }

    private static boolean same(JsonObject left, JsonObject right,
                                String... fields) {
        for (String field : fields) {
            String value = value(left, field);
            if (value.isEmpty() || !value.equals(value(right, field))) return false;
        }
        return true;
    }

    private static String digest(String input) {
        return edu.uva.liftlab.mallory.graphchecker.contract.Digest.digest(input, 16);
    }
}
