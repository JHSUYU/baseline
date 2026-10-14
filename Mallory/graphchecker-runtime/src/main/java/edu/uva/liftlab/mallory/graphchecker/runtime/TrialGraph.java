package edu.uva.liftlab.mallory.graphchecker.runtime;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import edu.uva.liftlab.mallory.graphchecker.contract.ExecutionIndex;
import edu.uva.liftlab.mallory.graphchecker.contract.OccurrenceAddress;

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
import java.util.TreeSet;
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
    private final Set<String> globalCoverageSiteIds = new TreeSet<>();
    private final Map<String, List<JsonObject>> doorRows = new LinkedHashMap<>();
    // The first strict pass expands and validates compact activation identities.
    // Later edge joins only need these validated strings, not another expansion
    // of every execution-index prefix in the trace.
    private final Map<String, String> activationOccurrences = new HashMap<>();
    private PriorSummary priorSummary;

    private static final class PriorSummary {
        final List<String> sites;
        final Set<String> nodes;
        final Set<String> edges;
        final Set<String> coverage;

        PriorSummary(List<String> sites, Set<String> nodes, Set<String> edges,
                     Set<String> coverage) {
            this.sites = sites;
            this.nodes = nodes;
            this.edges = edges;
            this.coverage = coverage;
        }
    }

    private TrialGraph() { }

    private static List<String> summaryStrings(JsonObject value, String key) {
        if (!value.has(key) || !value.get(key).isJsonArray()) {
            throw new IllegalArgumentException("healthy summary missing string array " + key);
        }
        List<String> strings = new ArrayList<>();
        for (JsonElement item : value.getAsJsonArray(key)) {
            if (!item.isJsonPrimitive() || !item.getAsJsonPrimitive().isString()
                    || item.getAsString().isEmpty()) {
                throw new IllegalArgumentException("invalid healthy summary " + key);
            }
            strings.add(item.getAsString());
        }
        if (new HashSet<>(strings).size() != strings.size()) {
            throw new IllegalArgumentException("duplicate healthy summary " + key);
        }
        return strings;
    }

    /** Only the healthy facts used for exact closure novelty in later trials. */
    public JsonObject healthySummary(List<String> targetSites) {
        if (targetSites == null || targetSites.isEmpty()
                || targetSites.contains(null) || targetSites.contains("")
                || new HashSet<>(targetSites).size() != targetSites.size()) {
            throw new IllegalArgumentException("target sites must be unique nonempty IDs");
        }
        ClosureResult closure = closureResult(new LinkedHashSet<>(targetSites));
        Set<String> nodeFamilies = new TreeSet<>();
        Set<String> edgeFamilies = new TreeSet<>();
        Set<String> coverageSites = new TreeSet<>();
        for (String id : closure.nodes) nodeFamilies.add(nodeFamily(id));
        for (String id : closure.edges) {
            JsonObject edge = edges.get(id);
            if (edge != null) edgeFamilies.add(edgeFamily(edge));
        }
        for (Map.Entry<String, Long> entry : closure.cutoffs.entrySet()) {
            for (CoverageEvent event : coverageRows.getOrDefault(entry.getKey(),
                    Collections.emptyList())) {
                if (event.seq <= entry.getValue()) coverageSites.add(event.site);
            }
        }
        JsonObject result = new JsonObject();
        result.addProperty("summaryVersion", 1);
        com.google.gson.Gson gson = new com.google.gson.Gson();
        result.add("targetSites", gson.toJsonTree(targetSites));
        result.add("nodeFamilies", gson.toJsonTree(nodeFamilies));
        result.add("edgeFamilies", gson.toJsonTree(edgeFamilies));
        result.add("coverageSites", gson.toJsonTree(coverageSites));
        return result;
    }

    /** Reads a validated summary as the prior input to {@link #feedback}. */
    public static TrialGraph readHealthySummary(Path path, List<String> targetSites)
            throws IOException {
        JsonObject value;
        try {
            value = new JsonParser().parse(new String(Files.readAllBytes(path),
                    StandardCharsets.UTF_8)).getAsJsonObject();
        } catch (RuntimeException invalid) {
            throw new IllegalArgumentException("invalid healthy summary JSON", invalid);
        }
        if (!value.has("summaryVersion") || value.get("summaryVersion").getAsInt() != 1) {
            throw new IllegalArgumentException("unsupported healthy summary version");
        }
        List<String> sites = summaryStrings(value, "targetSites");
        if (!sites.equals(targetSites)) {
            throw new IllegalArgumentException("healthy summary target sites differ");
        }
        TrialGraph graph = new TrialGraph();
        graph.priorSummary = new PriorSummary(sites,
                new HashSet<>(summaryStrings(value, "nodeFamilies")),
                new HashSet<>(summaryStrings(value, "edgeFamilies")),
                new HashSet<>(summaryStrings(value, "coverageSites")));
        return graph;
    }

    public static TrialGraph read(Path trace) throws IOException {
        TrialGraph graph = new TrialGraph();
        if (!Files.isRegularFile(trace)) {
            graph.gap("TRACE_MISSING");
            return graph;
        }
        graph.accept(trace);
        return graph;
    }

    private static final class ActivationStamp {
        final String occurrence;
        final String node;
        final String region;
        final long seq;

        ActivationStamp(JsonObject row) {
            occurrence = value(row, "occurrence");
            node = value(row, "node");
            region = value(row, "regionId");
            seq = number(row, "seq");
        }
    }

    private static OccurrenceAddress address(ActivationStamp stamp,
            Map<String, OccurrenceAddress> cache, String id) {
        if (stamp == null) return null;
        OccurrenceAddress known = cache.get(id);
        if (known != null) return known;
        try {
            OccurrenceAddress parsed = OccurrenceAddress.parse(stamp.occurrence);
            cache.put(id, parsed);
            return parsed;
        } catch (IllegalArgumentException invalid) {
            return null;
        }
    }

    private void eachRow(Path trace, boolean countInvalid,
                         Consumer<JsonObject> consumer) throws IOException {
        Map<String, ActivationStamp> activations = new HashMap<>();
        // Compact rows often refer to the same active region many times. The
        // bounded cache avoids repeatedly parsing long execution indices.
        Map<String, OccurrenceAddress> addressCache =
                new LinkedHashMap<String, OccurrenceAddress>(1024, 0.75f, true) {
                    @Override protected boolean removeEldestEntry(
                            Map.Entry<String, OccurrenceAddress> eldest) {
                        return size() > 1024;
                    }
                };
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
                OccurrenceAddress parentAddress = null;
                if ("ACTIVATION".equals(value(row, "parentOccurrenceRef"))) {
                    String parentId = value(row, "parentOccurrenceId");
                    ActivationStamp parent = activations.get(parentId);
                    parentAddress = address(parent, addressCache, parentId);
                    if (!("ACTIVATION".equals(value(row, "kind"))
                            || "REGION_COMPLETE".equals(value(row, "kind")))
                            || row.has("parentOccurrence") || parentAddress == null
                            || !parentId.equals(parentAddress.id())
                            || !parent.node.equals(value(row, "node"))
                            || parent.seq < 0 || parent.seq >= number(row, "seq")) {
                        throw new IllegalArgumentException(
                                "compact parent lacks exact prior activation "
                                        + parentId + " at seq " + value(row, "seq"));
                    }
                    row.addProperty("parentOccurrence", parent.occurrence);
                }
                if (row.has("indexSuffix")) {
                    if (!"ACTIVATION".equals(value(row, "kind"))
                            || row.has("occurrence")
                            || !"ACTIVATION".equals(value(row, "parentOccurrenceRef"))
                            || !row.has("parentOccurrence")) {
                        throw new IllegalArgumentException(
                                "invalid compact activation at seq " + value(row, "seq"));
                    }
                    try {
                        OccurrenceAddress parent = parentAddress;
                        String suffix = value(row, "indexSuffix");
                        if (suffix.isEmpty()
                                || !parent.index().hash().equals(
                                        value(row, "parentIndexHash"))
                                || !parent.node().render().equals(value(row, "node"))) {
                            throw new IllegalArgumentException("parent/index mismatch");
                        }
                        OccurrenceAddress child = OccurrenceAddress.of(parent.node(),
                                value(row, "regionId"), parent.context(),
                                ExecutionIndex.append(parent.index(),
                                        ExecutionIndex.parse(suffix)));
                        if (!child.id().equals(value(row, "occurrenceId"))) {
                            throw new IllegalArgumentException("child digest mismatch");
                        }
                        row.addProperty("occurrence", child.render());
                        addressCache.put(child.id(), child);
                    } catch (IllegalArgumentException invalid) {
                        throw new IllegalArgumentException(
                                "compact activation does not reconstruct exact identity "
                                        + value(row, "occurrenceId") + " at seq "
                                        + value(row, "seq"), invalid);
                    }
                }
                if ("ACTIVATION".equals(value(row, "kind"))) {
                    String id = value(row, "occurrenceId");
                    if (!id.isEmpty()) {
                        ActivationStamp previous = activations.get(id);
                        if (previous != null && (!previous.occurrence.equals(
                                value(row, "occurrence"))
                                || !previous.node.equals(value(row, "node"))
                                || !previous.region.equals(value(row, "regionId")))) {
                            throw new IllegalArgumentException(
                                    "conflicting activation for occurrence " + id);
                        }
                        // Identical duplicates preserve the prior streaming
                        // behavior: the latest publication is the anchor.
                        activations.put(id, new ActivationStamp(row));
                    }
                } else if ("ACTIVATION".equals(value(row, "occurrenceRef"))) {
                    String kind = value(row, "kind");
                    String id = value(row, "occurrenceId");
                    ActivationStamp activation = activations.get(id);
                    OccurrenceAddress address = address(activation, addressCache, id);
                    if (!("COVERAGE".equals(kind) || "FAULT_DOOR".equals(kind)
                            || "REGION_COMPLETE".equals(kind))
                            || row.has("occurrence") || address == null
                            || !id.equals(address.id())
                            || !activation.node.equals(
                                    address.node().render())
                            || !activation.region.equals(
                                    address.regionId())
                            || !value(row, "node").equals(activation.node)
                            || !value(row, "regionId").equals(activation.region)
                            || activation.seq < 0
                            || activation.seq >= number(row, "seq")) {
                        throw new IllegalArgumentException(
                                "compact trace occurrence lacks an exact prior activation "
                                        + id + " at seq " + value(row, "seq"));
                    }
                    row.addProperty("occurrence", activation.occurrence);
                }
                consumer.accept(row);
            }
        }
    }

    private void eachValidatedRowShallow(Path trace, Consumer<JsonObject> consumer)
            throws IOException {
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
                catch (RuntimeException invalid) { continue; }
                String kind = value(row, "kind");
                if (!("ATTACH".equals(kind) || "READ".equals(kind)
                        || "TASK_CLAIM".equals(kind) || "QUEUE_CONSUMED".equals(kind)
                        || "ACTIVATION".equals(kind) || "REGION_COMPLETE".equals(kind))) {
                    continue;
                }
                if (("ACTIVATION".equals(kind) || "REGION_COMPLETE".equals(kind))
                        && "ACTIVATION".equals(value(row, "parentOccurrenceRef"))) {
                    String parent = activationOccurrences.get(value(row,
                            "parentOccurrenceId"));
                    if (parent == null) {
                        throw new IllegalArgumentException(
                                "validated parent activation missing in shallow pass");
                    }
                    row.addProperty("parentOccurrence", parent);
                }
                if ("REGION_COMPLETE".equals(kind)
                        && "ACTIVATION".equals(value(row, "occurrenceRef"))) {
                    String child = activationOccurrences.get(value(row, "occurrenceId"));
                    if (child == null) {
                        throw new IllegalArgumentException(
                                "validated child activation missing in shallow pass");
                    }
                    row.addProperty("occurrence", child);
                }
                consumer.accept(row);
            }
        }
    }

    private void accept(Path trace) throws IOException {
        Map<String, List<JsonObject>> exports = new HashMap<>();
        Map<String, List<JsonObject>> writes = new HashMap<>();
        Map<String, List<JsonObject>> reads = new HashMap<>();
        Map<String, List<JsonObject>> taskSubmits = new HashMap<>();
        Map<String, List<JsonObject>> taskClaims = new HashMap<>();
        Map<String, List<JsonObject>> rootEntries = new LinkedHashMap<>();
        Map<String, List<JsonObject>> rootExits = new HashMap<>();
        eachRow(trace, true, row -> {
            String kind = value(row, "kind");
            if ("ACTIVATION".equals(kind)) {
                activationOccurrences.put(value(row, "occurrenceId"),
                        value(row, "occurrence"));
            }
            if ("ACTIVATION".equals(kind) || "SCOPE_ENTER".equals(kind)
                    || "TASK_SUBMIT".equals(kind)
                    || "TASK_CLAIM".equals(kind) || "SOURCE_SWITCH".equals(kind)) node(row);
            if ("TASK_SUBMIT".equals(kind)) {
                put(taskSubmits, value(row, "producerEndpointId"), row);
            }
            if ("TASK_CLAIM".equals(kind)
                    && !value(row, "producerEndpointId").isEmpty()) {
                put(taskClaims, value(row, "producerEndpointId"), row);
            }
            if ("SCOPE_ENTER".equals(kind) && "true".equals(value(row, "newRoot"))) {
                String key = scopeOrderKey(row);
                if (key.isEmpty()) gap("PROGRAM_ORDER_SOURCE_MISSING");
                else rootEntries.computeIfAbsent(key, unused -> new ArrayList<>()).add(row);
            }
            if ("SCOPE_EXIT".equals(kind) && "true".equals(value(row, "newRoot"))) {
                String id = value(row, "occurrenceId");
                if (!id.isEmpty()) rootExits.computeIfAbsent(id,
                        unused -> new ArrayList<>()).add(row);
            }
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
                // Global code coverage is useful even when no target occurs.
                // Keep it separate from attributed, cutoff-bounded closure
                // coverage; a static MAY relation cannot create a causal hit.
                if (!site.isEmpty()) globalCoverageSiteIds.add(site);
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
        eachValidatedRowShallow(trace, row -> {
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
            } else if ("TASK_CLAIM".equals(kind)
                    && !value(row, "producerEndpointId").isEmpty()) {
                String endpoint = value(row, "producerEndpointId");
                List<JsonObject> matched = taskSubmits.getOrDefault(endpoint,
                        Collections.emptyList());
                List<JsonObject> claims = taskClaims.getOrDefault(endpoint,
                        Collections.emptyList());
                if (matched.size() != 1) {
                    gap(matched.isEmpty() ? "TASK_SUBMIT_MISSING" :
                            "TASK_SUBMIT_AMBIGUOUS");
                    return;
                }
                if (claims.size() != 1) {
                    gap("TASK_CLAIM_AMBIGUOUS");
                    return;
                }
                JsonObject submit = matched.get(0);
                if (!same(row, submit, "siteId", "taskOrdinal", "sourceKey")
                        || !value(row, "producerOccurrenceId").equals(
                                value(submit, "occurrenceId"))
                        || !value(row, "node").equals(value(submit, "node"))
                        || number(submit, "seq") >= number(row, "seq")) {
                    gap("TASK_SUBMIT_MISMATCH");
                    return;
                }
                edge("HANDOFF", submit, row, "producerEndpointId",
                        "consumerEndpointId", value(row, "siteId") + ".TASK");
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
            if ("ACTIVATION".equals(kind)) addScopeEdge(row);
            if ("REGION_COMPLETE".equals(kind)) addCompletionEdge(row);
        });
        for (List<JsonObject> entries : rootEntries.values()) {
            JsonObject previous = null;
            for (JsonObject current : entries) {
                if (previous != null) {
                    List<JsonObject> exits = rootExits.getOrDefault(
                            value(previous, "occurrenceId"), Collections.emptyList());
                    if (exits.size() == 1 &&
                            same(exits.get(0), previous, "node", "threadKey", "token",
                                    "occurrenceId") &&
                            number(previous, "seq") < number(exits.get(0), "seq") &&
                            number(exits.get(0), "seq") < number(current, "seq")) {
                        JsonObject order = new JsonObject();
                        order.addProperty("kind", "EDGE");
                        order.addProperty("edge", "PROGRAM_ORDER");
                        order.addProperty("edgeId", digest("PROGRAM_ORDER" +
                                value(previous, "occurrenceId") +
                                value(current, "occurrenceId") +
                                number(exits.get(0), "seq")));
                        order.addProperty("producerOccurrenceId",
                                value(previous, "occurrenceId"));
                        order.addProperty("consumerOccurrenceId",
                                value(current, "occurrenceId"));
                        order.addProperty("producerEndpointId",
                                value(previous, "occurrenceId") + ":scope-exit");
                        order.addProperty("consumerEndpointId",
                                value(current, "occurrenceId") + ":scope-entry");
                        order.addProperty("port", value(current, "api"));
                        order.addProperty("producerSeq", number(exits.get(0), "seq"));
                        order.addProperty("consumerSeq", number(current, "seq"));
                        edges.put(value(order, "edgeId"), order);
                    } else {
                        gap("PROGRAM_ORDER_EXIT_UNPROVEN");
                    }
                }
                previous = current;
            }
        }
        activationOccurrences.clear();
    }

    private void addScopeEdge(JsonObject row) {
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
    }

    private void addCompletionEdge(JsonObject row) {
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
    }

    private static String scopeOrderKey(JsonObject row) {
        String node = value(row, "node");
        String thread = value(row, "threadKey");
        String source = value(row, "sourceKey");
        String api = value(row, "api");
        String id = value(row, "occurrenceId");
        String token = value(row, "token");
        return node.isEmpty() || thread.isEmpty() || source.isEmpty() ||
                api.isEmpty() || id.isEmpty() || token.isEmpty() ? "" :
                node + "\n" + thread + "\n" + source + "\n" + api;
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
        if (targetSite == null || targetSite.isEmpty()) {
            return closureResult(Collections.<String>emptySet());
        }
        return closureResult(Collections.singleton(targetSite));
    }

    private ClosureResult closureResult(Set<String> targetSites) {
        List<JsonObject> roots = new ArrayList<>();
        for (JsonObject target : targets) {
            if (targetSites.isEmpty() || targetSites.contains(value(target, "siteId"))) {
                roots.add(target);
            }
        }
        return closureResultForTargets(roots);
    }

    private ClosureResult closureResultForTargets(List<JsonObject> roots) {
        Map<String, Long> latest = new LinkedHashMap<>();
        Deque<String> pending = new ArrayDeque<>();
        Set<String> usedEdges = new LinkedHashSet<>();
        for (JsonObject target : roots) {
            String id = value(target, "occurrenceId");
            if (id.isEmpty()) continue;
            long cutoff = number(target, "seq");
            if (cutoff < 0) cutoff = Long.MAX_VALUE;
            if (cutoff > latest.getOrDefault(id, Long.MIN_VALUE)) {
                latest.put(id, cutoff);
                pending.add(id);
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
        return feedback(Collections.singletonList(targetSite), before, staticScope);
    }

    public JsonObject feedback(List<String> targetSites, TrialGraph before,
                               StaticScope staticScope) {
        if (targetSites == null || targetSites.isEmpty()) {
            throw new IllegalArgumentException("at least one target site is required");
        }
        Set<String> selected = new LinkedHashSet<>();
        for (String site : targetSites) {
            if (site == null || site.isEmpty() || !selected.add(site)) {
                throw new IllegalArgumentException("target sites must be unique nonempty IDs");
            }
        }
        String targetSite = targetSites.get(0);
        ClosureResult exact = closureResult(selected);
        Set<String> closure = exact.nodes;
        int targetChecks = 0;
        int targetThrows = 0;
        Set<String> thrownClasses = new LinkedHashSet<>();
        Set<String> checkOutcomes = new LinkedHashSet<>();
        Set<String> observedSites = new LinkedHashSet<>();
        Map<String, Set<String>> outcomesBySite = new LinkedHashMap<>();
        Map<String, Integer> checksBySite = new LinkedHashMap<>();
        Map<String, Integer> throwsBySite = new LinkedHashMap<>();
        for (String site : selected) {
            outcomesBySite.put(site, new LinkedHashSet<String>());
            checksBySite.put(site, 0);
            throwsBySite.put(site, 0);
        }
        for (JsonObject target : targets) {
            String site = value(target, "siteId");
            if (!selected.contains(site)) continue;
            if (value(target, "occurrenceId").isEmpty()) continue;
            observedSites.add(site);
            if ("TARGET_CHECK".equals(value(target, "kind"))) {
                targetChecks++;
                checkOutcomes.add(value(target, "outcome"));
                outcomesBySite.get(site).add(value(target, "outcome"));
                checksBySite.put(site, checksBySite.get(site) + 1);
            } else if ("TARGET_THROW".equals(value(target, "kind"))) {
                targetThrows++;
                thrownClasses.add(value(target, "exceptionClass"));
                throwsBySite.put(site, throwsBySite.get(site) + 1);
            }
        }
        Set<String> priorNodes = new HashSet<>();
        Set<String> priorEdges = new HashSet<>();
        if (before != null) {
            if (before.priorSummary != null) {
                if (!before.priorSummary.sites.equals(new ArrayList<>(selected))) {
                    throw new IllegalArgumentException("healthy summary target sites differ");
                }
                priorNodes.addAll(before.priorSummary.nodes);
                priorEdges.addAll(before.priorSummary.edges);
            } else {
                ClosureResult prior = before.closureResult(selected);
                for (String id : prior.nodes) priorNodes.add(before.nodeFamily(id));
                for (String id : prior.edges) {
                    JsonObject edge = before.edges.get(id);
                    if (edge != null) priorEdges.add(before.edgeFamily(edge));
                }
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
        Map<String, Boolean> staticFoundBySite = new LinkedHashMap<>();
        if (staticScope != null) {
            Set<String> mayRegions = new LinkedHashSet<>();
            Set<String> mayDoorSites = new LinkedHashSet<>();
            List<JsonObject> mayRelations = new ArrayList<>();
            Set<String> relationKeys = new LinkedHashSet<>();
            boolean allFound = true;
            for (String site : selected) {
                Set<String> closureRegions = new LinkedHashSet<>();
                for (String id : closureResult(site).nodes) {
                    JsonObject node = nodes.get(id);
                    if (node != null) closureRegions.add(value(node, "regionId"));
                }
                StaticScope.Result one = staticScope.mayReach(site, closureRegions);
                staticFoundBySite.put(site, one.targetFound);
                allFound &= one.targetFound;
                mayRegions.addAll(one.regions);
                mayDoorSites.addAll(one.doorSites);
                for (JsonObject relation : one.relations) {
                    if (relationKeys.add(relation.toString())) mayRelations.add(relation);
                }
            }
            may = new StaticScope.Result(allFound, mayRegions, mayDoorSites, mayRelations);
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
            if (before.priorSummary != null) {
                previousCoverage.addAll(before.priorSummary.coverage);
            } else {
                ClosureResult prior = before.closureResult(selected);
                for (Map.Entry<String, Long> entry : prior.cutoffs.entrySet()) {
                    for (CoverageEvent event : before.coverageRows.getOrDefault(entry.getKey(),
                            Collections.emptyList())) {
                        if (event.seq <= entry.getValue()) {
                            previousCoverage.add(event.site);
                        }
                    }
                }
            }
        }
        int newCoverage = 0;
        for (String site : covered) if (!previousCoverage.contains(site)) newCoverage++;
        Set<String> missingSites = new LinkedHashSet<>(selected);
        missingSites.removeAll(observedSites);
        JsonObject perTarget = new JsonObject();
        for (String site : selected) {
            ClosureResult oneClosure = closureResult(site);
            JsonObject one = new JsonObject();
            one.addProperty("targetReached", observedSites.contains(site));
            one.addProperty("targetChecks", checksBySite.get(site));
            one.addProperty("targetThrows", throwsBySite.get(site));
            one.add("targetCheckOutcomes", new com.google.gson.Gson().toJsonTree(
                    outcomesBySite.get(site)));
            one.add("closureOccurrenceIds", new com.google.gson.Gson().toJsonTree(
                    oneClosure.nodes));
            one.add("closureOccurrenceCutoffs", new com.google.gson.Gson().toJsonTree(
                    oneClosure.cutoffs));
            one.add("closureEdgeIds", new com.google.gson.Gson().toJsonTree(
                    oneClosure.edges));
            if (staticScope != null) {
                one.addProperty("staticScopeTargetFound", staticFoundBySite.get(site));
            }
            perTarget.add(site, one);
        }
        JsonObject row = new JsonObject();
        row.addProperty("schemaVersion", 1);
        row.addProperty("targetSite", targetSite == null ? "" : targetSite);
        row.add("configuredTargetSites", new com.google.gson.Gson().toJsonTree(selected));
        row.add("observedTargetSites", new com.google.gson.Gson().toJsonTree(observedSites));
        row.add("missingTargetSites", new com.google.gson.Gson().toJsonTree(missingSites));
        row.addProperty("allTargetSitesReached", missingSites.isEmpty());
        row.add("targetCheckOutcomesBySite", new com.google.gson.Gson().toJsonTree(
                outcomesBySite));
        row.add("perTargetClosures", perTarget);
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
        row.add("globalCoverageSiteIds", new com.google.gson.Gson().toJsonTree(
                globalCoverageSiteIds));
        row.add("closureOccurrenceIds", new com.google.gson.Gson().toJsonTree(closure));
        row.add("closureOccurrenceCutoffs", new com.google.gson.Gson().toJsonTree(exact.cutoffs));
        // Keep throw ancestry per event. A check in one request must not make
        // a later throw in an unrelated request look caused by that fault.
        com.google.gson.JsonArray throwClosures = new com.google.gson.JsonArray();
        for (JsonObject target : targets) {
            if (!"TARGET_THROW".equals(value(target, "kind"))
                    || value(target, "occurrenceId").isEmpty()) continue;
            JsonObject one = new JsonObject();
            one.addProperty("siteId", value(target, "siteId"));
            one.addProperty("exceptionClass", value(target, "exceptionClass"));
            one.addProperty("node", value(target, "node"));
            one.addProperty("occurrenceId", value(target, "occurrenceId"));
            one.addProperty("seq", number(target, "seq"));
            one.add("closureOccurrenceCutoffs", new com.google.gson.Gson().toJsonTree(
                    closureResultForTargets(Collections.singletonList(target)).cutoffs));
            throwClosures.add(one);
        }
        row.add("targetThrowClosures", throwClosures);
        row.add("closureEdgeIds", new com.google.gson.Gson().toJsonTree(closureEdges));
        row.add("closureNodeFamilies", new com.google.gson.Gson().toJsonTree(closureNodeFamilies));
        row.add("closureEdgeFamilies", new com.google.gson.Gson().toJsonTree(closureEdgeFamilies));
        row.add("closureCoverageSiteIds", new com.google.gson.Gson().toJsonTree(covered));
        row.add("closureDoorSiteIds", new com.google.gson.Gson().toJsonTree(closureDoors));
        if (may != null) {
            row.addProperty("staticScopeTargetFound", may.targetFound);
            row.add("staticScopeTargetFoundBySite", new com.google.gson.Gson().toJsonTree(
                    staticFoundBySite));
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
