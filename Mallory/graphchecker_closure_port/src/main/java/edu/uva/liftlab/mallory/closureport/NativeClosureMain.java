package edu.uva.liftlab.mallory.closureport;

import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import edu.uva.liftlab.graphchecker.contract.ActivationRow;
import edu.uva.liftlab.graphchecker.contract.AttachRow;
import edu.uva.liftlab.graphchecker.contract.DecisionRow;
import edu.uva.liftlab.graphchecker.contract.Endpoint;
import edu.uva.liftlab.graphchecker.contract.ExecutionIndex;
import edu.uva.liftlab.graphchecker.contract.ExportRow;
import edu.uva.liftlab.graphchecker.contract.ExpressionTable;
import edu.uva.liftlab.graphchecker.contract.GapRow;
import edu.uva.liftlab.graphchecker.contract.LocationId;
import edu.uva.liftlab.graphchecker.contract.LocationKind;
import edu.uva.liftlab.graphchecker.contract.OccurrenceAddress;
import edu.uva.liftlab.graphchecker.contract.ReadRow;
import edu.uva.liftlab.graphchecker.contract.RootMintRow;
import edu.uva.liftlab.graphchecker.contract.RowCodec;
import edu.uva.liftlab.graphchecker.contract.SessionDir;
import edu.uva.liftlab.graphchecker.contract.SessionManifest;
import edu.uva.liftlab.graphchecker.contract.TargetRow;
import edu.uva.liftlab.graphchecker.contract.Task;
import edu.uva.liftlab.graphchecker.contract.WriteRow;
import edu.uva.liftlab.graphchecker.explore.Branches;
import edu.uva.liftlab.graphchecker.explore.ClosurePlanner;
import edu.uva.liftlab.graphchecker.explore.Corpus;
import edu.uva.liftlab.graphchecker.plan.StaticScopeMap;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.zip.GZIPInputStream;

/**
 * A narrow, fail-closed adapter from Mallory's observed JUnit rows to the
 * original GraphChecker seed-session contract.  It deliberately does not
 * invent values, symbolic terms, read versions, or producer endpoints that
 * the raw trace did not state in GraphChecker's contract.
 */
public final class NativeClosureMain {
    static final String UPSTREAM_COMMIT = "c4a90033c654737206466ed36ce837c5b3c12457";
    static final String UPSTREAM_JAR_SHA256 =
            "8897901dee05750e9aa456978091190337aa3762a813527fbd510ff8d3c38880";
    static final String UPSTREAM_FAT_JAR_SHA256 =
            "222f2d74236d432c6ad4001f5d9423b5bd9567084ad668089676ccf8de43e343";
    private static final String SESSION = "seed";

    private NativeClosureMain() { }

    static String string(JsonObject row, String field) {
        JsonElement value = row.get(field);
        return value == null || value.isJsonNull() ? "" : value.getAsString();
    }

    static long sequence(JsonObject row) {
        JsonElement value = row.get("seq");
        return value == null ? 0L : value.getAsLong();
    }

    static String sha256(Path path) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = Files.newInputStream(path)) {
            byte[] bytes = new byte[65536];
            for (int size; (size = input.read(bytes)) != -1;) {
                digest.update(bytes, 0, size);
            }
        }
        StringBuilder hex = new StringBuilder();
        for (byte value : digest.digest()) {
            hex.append(String.format("%02x", value & 255));
        }
        return hex.toString();
    }

    static final class Adapted {
        final List<ActivationRow> activations = new ArrayList<>();
        final List<TargetRow> targets = new ArrayList<>();
        final List<WriteRow> writes = new ArrayList<>();
        final List<ReadRow> reads = new ArrayList<>();
        final List<JsonObject> rawWrites = new ArrayList<>();
        final List<JsonObject> rawReads = new ArrayList<>();
        final List<JsonObject> rawExports = new ArrayList<>();
        final List<JsonObject> rawAttaches = new ArrayList<>();
        final List<JsonObject> rawActivations = new ArrayList<>();
        final List<JsonObject> rawCompletions = new ArrayList<>();
        final List<JsonObject> rawFaults = new ArrayList<>();
        final List<JsonObject> rawTargetChecks = new ArrayList<>();
        final Map<String, Integer> refusedStateRows = new LinkedHashMap<>();
        final Map<String, OccurrenceAddress> targetOccurrences = new LinkedHashMap<>();
        final Map<String, Integer> sourceCounts = new LinkedHashMap<>();
        final Map<String, Integer> mappedCounts = new LinkedHashMap<>();
        final Map<String, JsonObject> activationByOccurrence = new LinkedHashMap<>();

        void count(Map<String, Integer> counts, String kind) {
            counts.put(kind, counts.containsKey(kind) ? counts.get(kind) + 1 : 1);
        }

        void take(JsonObject row, String targetSite) {
            String kind = string(row, "kind");
            if ("ACTIVATION".equals(kind)) {
                // A compact runtime event may refer only to an activation
                // already published in this same ordered trace.
                exactOccurrence(row);
                String id = string(row, "occurrenceId");
                JsonObject previous = activationByOccurrence.get(id);
                if (previous != null && (!string(previous, "occurrence").equals(
                        string(row, "occurrence"))
                        || !string(previous, "node").equals(string(row, "node"))
                        || !string(previous, "regionId").equals(
                                string(row, "regionId")))) {
                    throw new IllegalArgumentException(
                            "conflicting activation for occurrence " + id);
                }
                activationByOccurrence.put(id, row);
            } else if ("ACTIVATION".equals(string(row, "occurrenceRef"))) {
                JsonObject activation = activationByOccurrence.get(
                        string(row, "occurrenceId"));
                OccurrenceAddress address = activation == null ? null
                        : exactOccurrence(activation);
                if (!("COVERAGE".equals(kind) || "FAULT_DOOR".equals(kind)
                        || "REGION_COMPLETE".equals(kind))
                        || row.has("occurrence") || address == null
                        || !string(activation, "node").equals(
                                address.node().render())
                        || !string(activation, "regionId").equals(
                                address.regionId())
                        || !string(row, "node").equals(string(activation, "node"))
                        || !string(row, "regionId").equals(
                                string(activation, "regionId"))
                        || sequence(activation) >= sequence(row)) {
                    throw new IllegalArgumentException(
                            "compact trace occurrence lacks an exact prior activation "
                                    + string(row, "occurrenceId") + " at seq "
                                    + sequence(row));
                }
                row.addProperty("occurrence", string(activation, "occurrence"));
            }
            count(sourceCounts, kind);
            if ("ACTIVATION".equals(kind)) {
                OccurrenceAddress occurrence = exactOccurrence(row);
                rawActivations.add(row);
                activations.add(ActivationRow.of(SESSION, occurrence,
                        "observed-" + string(row, "occurrenceId"), false,
                        true, string(row, "threadKey")));
                count(mappedCounts, kind);
            } else if (("TARGET_CHECK".equals(kind) || "TARGET_THROW".equals(kind))
                    && targetSite.equals(string(row, "siteId"))) {
                OccurrenceAddress occurrence = exactOccurrence(row);
                boolean fatal = "TARGET_THROW".equals(kind);
                String phi = fatal || "TRUE".equalsIgnoreCase(string(row, "outcome"))
                        ? "true" : "false";
                targets.add(TargetRow.of(SESSION, sequence(row), occurrence,
                        targetSite, phi, fatal, true));
                targetOccurrences.put(occurrence.id(), occurrence);
                rawTargetChecks.add(row);
                count(mappedCounts, kind);
            } else if ("WRITE".equals(kind)) {
                rawWrites.add(row);
            } else if ("READ".equals(kind)) {
                rawReads.add(row);
            } else if ("EXPORT".equals(kind)) {
                rawExports.add(row);
            } else if ("ATTACH".equals(kind)) {
                rawAttaches.add(row);
            } else if ("REGION_COMPLETE".equals(kind)) {
                rawCompletions.add(row);
            } else if ("FAULT_APPLIED".equals(kind)) {
                rawFaults.add(row);
            }
        }

        /** Exact WIRE identity pairs; payload symbols are deliberately absent. */
        JsonArray observedWirePairs() {
            Map<String, List<JsonObject>> senders = new LinkedHashMap<>();
            for (JsonObject row : rawExports) {
                senders.computeIfAbsent(string(row, "producerEndpointId"),
                        unused -> new ArrayList<>()).add(row);
            }
            JsonArray pairs = new JsonArray();
            for (JsonObject attach : rawAttaches) {
                List<JsonObject> matches = senders.getOrDefault(
                        string(attach, "producerEndpointId"), Collections.emptyList());
                if (matches.size() != 1) continue;
                JsonObject export = matches.get(0);
                if (!string(export, "transport").equals(string(attach, "transport"))
                        || !string(export, "correlationId").equals(
                        string(attach, "correlationId"))
                        || !string(export, "attemptId").equals(
                        string(attach, "attemptId"))
                        || !string(export, "half").equals(string(attach, "half"))
                        || sequence(export) >= sequence(attach)) continue;
                try {
                    Endpoint consumer = exactEndpoint(string(attach, "consumer"),
                            string(attach, "consumerEndpointId"));
                    if (!consumer.occurrence().id().equals(
                            string(attach, "occurrenceId"))) continue;
                    if (!string(export, "occurrenceId").equals(
                            string(attach, "producerOccurrenceId"))) continue;
                    JsonObject edge = new JsonObject();
                    edge.addProperty("producerEndpointId",
                            string(export, "producerEndpointId"));
                    edge.addProperty("consumerEndpointId", consumer.id());
                    edge.addProperty("fromOccurrenceId",
                            string(export, "occurrenceId"));
                    edge.addProperty("toOccurrenceId", consumer.occurrence().id());
                    edge.addProperty("sendSeq", sequence(export));
                    edge.addProperty("receiveSeq", sequence(attach));
                    edge.addProperty("evidence", "exact endpoint and transport tuple; payload unknown");
                    pairs.add(edge);
                } catch (IllegalArgumentException invalid) {
                    // The row is not an exact GraphChecker endpoint.
                }
            }
            return pairs;
        }

        /**
         * A separate happens-before extension, never presented as a native
         * value-demand closure edge.  Only the immediately previous completed
         * invocation of the same region on the same node/thread qualifies.
         */
        JsonArray observedFaultPredecessors() {
            Map<String, JsonObject> completionByOccurrence = new LinkedHashMap<>();
            for (JsonObject row : rawCompletions) {
                completionByOccurrence.put(string(row, "occurrenceId"), row);
            }
            Map<String, JsonObject> faultByOccurrence = new LinkedHashMap<>();
            for (JsonObject row : rawFaults) {
                faultByOccurrence.put(string(row, "occurrenceId"), row);
            }
            JsonArray edges = new JsonArray();
            for (JsonObject target : rawTargetChecks) {
                JsonObject entered = null;
                for (JsonObject activation : rawActivations) {
                    if (string(activation, "occurrenceId").equals(
                            string(target, "occurrenceId"))) entered = activation;
                }
                if (entered == null) continue;
                JsonObject previous = null;
                for (JsonObject activation : rawActivations) {
                    if (sequence(activation) >= sequence(entered)
                            || !string(activation, "regionId").equals(
                            string(entered, "regionId"))
                            || !string(activation, "node").equals(string(entered, "node"))
                            || !string(activation, "threadKey").equals(
                            string(entered, "threadKey"))) continue;
                    if (previous == null || sequence(activation) > sequence(previous)) {
                        previous = activation;
                    }
                }
                if (previous == null) continue;
                String predecessorId = string(previous, "occurrenceId");
                JsonObject fault = faultByOccurrence.get(predecessorId);
                JsonObject completed = completionByOccurrence.get(predecessorId);
                if (fault == null || completed == null
                        || sequence(previous) > sequence(fault)
                        || sequence(fault) >= sequence(completed)
                        || sequence(completed) >= sequence(entered)) continue;
                JsonObject edge = new JsonObject();
                edge.addProperty("kind", "PROGRAM_ORDER_FAULT_PREDECESSOR");
                edge.addProperty("fromOccurrenceId", predecessorId);
                edge.addProperty("toOccurrenceId", string(target, "occurrenceId"));
                edge.addProperty("faultSiteId", string(fault, "siteId"));
                edge.addProperty("faultSeq", sequence(fault));
                edge.addProperty("completionSeq", sequence(completed));
                edge.addProperty("targetEntrySeq", sequence(entered));
                edge.addProperty("targetCheckSeq", sequence(target));
                edges.add(edge);
            }
            return edges;
        }

        /**
         * Preserve an observed resource version as a monotone integer for
         * GraphChecker.  A read is admitted only if its exact writer endpoint
         * AND its opaque version name point to one actual WRITE row.  This
         * remaps names, never guesses an unobserved write or file payload.
         */
        void mapExactResourceVersions() {
            rawWrites.sort(Comparator.comparingLong(NativeClosureMain::sequence));
            Map<String, Long> ordinalByResource = new LinkedHashMap<>();
            Map<String, List<WriteRow>> byExactPair = new LinkedHashMap<>();
            for (JsonObject raw : rawWrites) {
                String opaque = string(raw, "locationVersion");
                String resource = resourceKey(opaque);
                if (resource.isEmpty()) {
                    count(refusedStateRows, "WRITE_RESOURCE_SHAPE_UNKNOWN");
                    continue;
                }
                try {
                    Endpoint endpoint = exactEndpoint(string(raw, "writer"),
                            string(raw, "writerEndpointId"));
                    if (!endpoint.occurrence().id().equals(string(raw, "occurrenceId"))) {
                        throw new IllegalArgumentException("writer occurrence mismatch");
                    }
                    long version = ordinalByResource.getOrDefault(resource, 0L) + 1L;
                    ordinalByResource.put(resource, version);
                    WriteRow row = WriteRow.of(SESSION, sequence(raw), endpoint,
                            resourceLocation(resource), version, "", "[B");
                    writes.add(row);
                    byExactPair.computeIfAbsent(opaque + "\u0000" + endpoint.id(),
                            unused -> new ArrayList<>()).add(row);
                    count(mappedCounts, "WRITE");
                } catch (IllegalArgumentException invalid) {
                    count(refusedStateRows, "WRITE_ENDPOINT_UNVERIFIED");
                }
            }
            for (JsonObject raw : rawReads) {
                String opaque = string(raw, "locationVersion");
                String resource = resourceKey(opaque);
                if (resource.isEmpty()) {
                    count(refusedStateRows, "READ_RESOURCE_SHAPE_UNKNOWN");
                    continue;
                }
                List<WriteRow> writers = byExactPair.getOrDefault(
                        opaque + "\u0000" + string(raw, "writerEndpointId"),
                        Collections.emptyList());
                if (writers.size() != 1 || writers.get(0).seq() >= sequence(raw)) {
                    count(refusedStateRows, "READ_WRITER_NOT_UNIQUE_OR_LATE");
                    continue;
                }
                try {
                    Endpoint endpoint = exactEndpoint(string(raw, "reader"),
                            string(raw, "readerEndpointId"));
                    if (!endpoint.occurrence().id().equals(string(raw, "occurrenceId"))) {
                        throw new IllegalArgumentException("reader occurrence mismatch");
                    }
                    WriteRow writer = writers.get(0);
                    if (!writer.location().equals(resourceLocation(resource))) {
                        throw new IllegalArgumentException("reader resource mismatch");
                    }
                    // The file bytes themselves are not present.  This is a
                    // fresh abstract read symbol, never a claimed payload.
                    String symbol = "M_RESOURCE_READ_" + endpoint.id()
                            + "_" + sequence(raw);
                    reads.add(ReadRow.of(SESSION, sequence(raw), endpoint,
                            writer.location(), writer.version(), symbol, "[B", null));
                    count(mappedCounts, "READ");
                } catch (IllegalArgumentException invalid) {
                    count(refusedStateRows, "READ_ENDPOINT_UNVERIFIED");
                }
            }
        }

        void write(Path iteration) throws IOException {
            SessionDir dir = SessionDir.of(iteration, SESSION).create();
            RowCodec.writeAll(dir.activations(), activations, RowCodec::writeActivation);
            RowCodec.writeAll(dir.targets(), targets, RowCodec::writeTarget);
            RowCodec.writeAll(dir.decisions(), Collections.<DecisionRow>emptyList(),
                    RowCodec::writeDecision);
            RowCodec.writeAll(dir.exports(), Collections.<ExportRow>emptyList(),
                    RowCodec::writeExport);
            RowCodec.writeAll(dir.attaches(), Collections.<AttachRow>emptyList(),
                    RowCodec::writeAttach);
            RowCodec.writeAll(dir.writes(), writes,
                    RowCodec::writeWrite);
            RowCodec.writeAll(dir.reads(), reads,
                    RowCodec::writeRead);
            RowCodec.writeAll(dir.roots(), Collections.<RootMintRow>emptyList(),
                    RowCodec::writeRootMint);
            RowCodec.writeAll(dir.gaps(), Collections.<GapRow>emptyList(),
                    RowCodec::writeGap);
            RowCodec.writeExpressions(dir.expressions(), ExpressionTable.empty());
            RowCodec.writeManifest(dir.manifest(), SessionManifest.of(SESSION,
                    SessionManifest.Role.SEED, Collections.<String>emptyList()));
        }
    }

    /** Scheme and path before the first version separator, if explicit. */
    static String resourceKey(String opaqueVersion) {
        int newline = opaqueVersion.indexOf('\n');
        int separator = opaqueVersion.indexOf('|', newline + 1);
        if (newline <= 0 || separator <= newline + 1
                || separator == opaqueVersion.length() - 1) return "";
        return opaqueVersion.substring(0, separator);
    }

    static LocationId resourceLocation(String resource) {
        int newline = resource.indexOf('\n');
        return LocationId.of(LocationKind.MAP, resource.substring(0, newline),
                resource.substring(newline + 1));
    }

    /** The raw endpoint spelling is the GraphChecker contract render. */
    static Endpoint exactEndpoint(String rendered, String statedId) {
        int attemptAt = rendered.lastIndexOf("/att:");
        int indexAt = rendered.lastIndexOf("/sidx:", attemptAt);
        int siteAt = rendered.lastIndexOf("/site:", indexAt);
        if (siteAt < 0 || indexAt < 0 || attemptAt < 0) {
            throw new IllegalArgumentException("not a GraphChecker endpoint render");
        }
        Endpoint endpoint = Endpoint.of(OccurrenceAddress.parse(
                        rendered.substring(0, siteAt)),
                rendered.substring(siteAt + 6, indexAt),
                ExecutionIndex.parse(rendered.substring(indexAt + 6, attemptAt)),
                Integer.parseInt(rendered.substring(attemptAt + 5)));
        if (!endpoint.id().equals(statedId)) {
            throw new IllegalArgumentException("endpoint digest mismatch");
        }
        return endpoint;
    }

    static OccurrenceAddress exactOccurrence(JsonObject row) {
        OccurrenceAddress occurrence = OccurrenceAddress.parse(string(row, "occurrence"));
        if (!occurrence.id().equals(string(row, "occurrenceId"))) {
            throw new IllegalArgumentException("trace occurrence identity disagrees with "
                    + "GraphChecker contract at seq " + sequence(row));
        }
        return occurrence;
    }

    static Adapted adapt(Path trace, String targetSite) throws Exception {
        Adapted adapted = new Adapted();
        InputStream stream = Files.newInputStream(trace);
        if (trace.toString().endsWith(".gz")) stream = new GZIPInputStream(stream);
        try (BufferedReader input = new BufferedReader(
                new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            for (String line; (line = input.readLine()) != null;) {
                if (!line.trim().isEmpty()) {
                    adapted.take(new JsonParser().parse(line).getAsJsonObject(), targetSite);
                }
            }
        }
        if (adapted.targets.isEmpty()) {
            throw new IllegalArgumentException("target site did not occur: " + targetSite);
        }
        adapted.mapExactResourceVersions();
        return adapted;
    }

    static JsonObject run(Path trace, Path staticMap, String targetSite,
                          Path iteration, Path malloryFeedback) throws Exception {
        Path nativeCode = Paths.get(ClosurePlanner.class.getProtectionDomain()
                .getCodeSource().getLocation().toURI());
        Path adapterCode = Paths.get(NativeClosureMain.class.getProtectionDomain()
                .getCodeSource().getLocation().toURI());
        if (!nativeCode.equals(adapterCode)) {
            throw new IllegalStateException("ClosurePlanner was loaded from the dependency "
                    + "jar rather than this module's copied original source");
        }
        Path dependencyJar = Paths.get(StaticScopeMap.class.getProtectionDomain()
                .getCodeSource().getLocation().toURI());
        String dependencySha = sha256(dependencyJar);
        if (!UPSTREAM_JAR_SHA256.equals(dependencySha)
                && !UPSTREAM_FAT_JAR_SHA256.equals(dependencySha)) {
            throw new IllegalStateException("GraphChecker dependency jar hash differs "
                    + "from pinned commit build: " + dependencySha);
        }
        Adapted adapted = adapt(trace, targetSite);
        adapted.write(iteration);
        Corpus corpus = Corpus.read(iteration, null);
        StaticScopeMap scope = StaticScopeMap.read(staticMap);
        JsonObject result = new JsonObject();
        result.addProperty("sourceCommit", UPSTREAM_COMMIT);
        result.addProperty("upstreamDependencyJarSha256", dependencySha);
        result.addProperty("nativeClosureCodeSource", nativeCode.toString());
        result.addProperty("traceSha256", sha256(trace));
        result.addProperty("staticMapSha256", sha256(staticMap));
        result.addProperty("targetSite", targetSite);
        result.addProperty("nativeClosureClass", ClosurePlanner.class.getName());
        result.addProperty("nativeCorpusClass", Corpus.class.getName());
        result.addProperty("adaptedSession", iteration.toString());
        result.add("sourceEventCounts", new Gson().toJsonTree(adapted.sourceCounts));
        result.add("mappedEventCounts", new Gson().toJsonTree(adapted.mappedCounts));
        result.add("refusedStateRows", new Gson().toJsonTree(adapted.refusedStateRows));
        result.addProperty("resourceValueSemantics", "version identity only; file payload unknown");
        result.add("observedWirePairs", adapted.observedWirePairs());
        JsonArray faultPredecessors = adapted.observedFaultPredecessors();
        result.add("programOrderFaultEdges", faultPredecessors);
        JsonArray perTarget = new JsonArray();
        Set<String> nativeUnion = new LinkedHashSet<>();
        for (OccurrenceAddress anchor : adapted.targetOccurrences.values()) {
            ClosurePlanner.Plan plan = ClosurePlanner.plan(corpus, anchor,
                    ClosurePlanner.DEFAULT_MAX_TASKS, scope,
                    Branches.of(corpus, Collections.singletonList(anchor),
                            new ArrayList<GapRow>()));
            JsonObject one = new JsonObject();
            one.addProperty("anchorOccurrenceId", anchor.id());
            one.addProperty("anchorOccurrence", anchor.render());
            JsonArray members = new JsonArray();
            for (Task task : plan.tasks) {
                String id = task.focused().id();
                members.add(id);
                nativeUnion.add(id);
            }
            one.add("closureOccurrenceIds", members);
            one.add("why", new Gson().toJsonTree(plan.why));
            one.add("flipSites", new Gson().toJsonTree(plan.flipSites));
            one.addProperty("nativeGaps", plan.gaps.size());
            one.addProperty("truncated", plan.truncated.size());
            if (plan.concrete != null) {
                one.addProperty("concreteDecidedPaths", plan.concrete.decided);
                one.addProperty("concretePredicateReads", plan.concrete.reads.size());
            }
            perTarget.add(one);
        }
        result.add("nativeTargets", perTarget);
        result.add("nativeClosureOccurrenceIds", new Gson().toJsonTree(nativeUnion));
        Set<String> extended = new LinkedHashSet<>(nativeUnion);
        for (JsonElement item : faultPredecessors) {
            JsonObject edge = item.getAsJsonObject();
            if (nativeUnion.contains(edge.get("toOccurrenceId").getAsString())) {
                extended.add(edge.get("fromOccurrenceId").getAsString());
            }
        }
        result.add("nativePlusProgramOrderOccurrenceIds",
                new Gson().toJsonTree(extended));
        if (malloryFeedback != null) {
            JsonObject feedback = new JsonParser().parse(new String(
                    Files.readAllBytes(malloryFeedback), StandardCharsets.UTF_8))
                    .getAsJsonObject();
            Set<String> old = new LinkedHashSet<>();
            for (JsonElement item : feedback.getAsJsonArray("closureOccurrenceIds")) {
                old.add(item.getAsString());
            }
            Set<String> onlyNative = new LinkedHashSet<>(nativeUnion);
            onlyNative.removeAll(old);
            Set<String> onlyMallory = new LinkedHashSet<>(old);
            onlyMallory.removeAll(nativeUnion);
            result.add("malloryClosureOccurrenceIds", new Gson().toJsonTree(old));
            result.add("onlyNativeOccurrenceIds", new Gson().toJsonTree(onlyNative));
            result.add("onlyMalloryOccurrenceIds", new Gson().toJsonTree(onlyMallory));
        }
        return result;
    }

    /** trace(.gz) static_scope_map.jsonl targetSite output.json [Mallory feedback.json] */
    public static void main(String[] args) throws Exception {
        if (args.length != 4 && args.length != 5) {
            throw new IllegalArgumentException("usage: trace staticMap targetSite output "
                    + "[malloryFeedback]");
        }
        Path trace = Paths.get(args[0]);
        Path scope = Paths.get(args[1]);
        Path output = Paths.get(args[3]);
        Path parent = output.toAbsolutePath().getParent();
        Files.createDirectories(parent);
        Path iteration = Files.createTempDirectory(parent, "native-iteration-");
        JsonObject result = run(trace, scope, args[2], iteration,
                args.length == 5 ? Paths.get(args[4]) : null);
        Files.write(output, (new Gson().toJson(result) + "\n")
                .getBytes(StandardCharsets.UTF_8));
    }
}
