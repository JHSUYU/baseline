package edu.uva.liftlab.graphchecker.runtime;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import edu.uva.liftlab.graphchecker.causynth.MapFields;
import edu.uva.liftlab.graphchecker.causynth.RuntimeSelectedRegionFinalizer;
import edu.uva.liftlab.graphchecker.causynth.StaticProgram;
import edu.uva.liftlab.graphchecker.plan.StaticScopeMap;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Mallory adapter around the source-built GraphChecker recorder. It selects
 * the earliest healthy occurrence which actually evaluated the inventory
 * check, using GraphChecker's own CLOSED trace reader and region activation
 * planner. A folded target region is addressed by its containing activation.
 * No ordinal or source-line guess is made.
 */
public final class MalloryTargetOccurrenceResolver {
    private MalloryTargetOccurrenceResolver() { }

    public static void main(String[] args) throws Exception {
        Map<String, String> options = options(args);
        Path traceDir = path(options, "--trace-dir");
        File skeletons = path(options, "--region-skeletons").toFile();
        File scope = path(options, "--static-scope-map").toFile();
        File graph = path(options, "--candidate-graph").toFile();
        Path output = path(options, "--output");
        String test = required(options, "--test");
        String check = options.get("--check-site-id");
        String throwSite = options.get("--throw-site-id");

        JsonObject receipt = resolve(traceDir, test, skeletons, scope, graph,
                check, throwSite);
        Files.createDirectories(output.toAbsolutePath().getParent());
        Path staged = Files.createTempFile(output.toAbsolutePath().getParent(),
                ".target-occurrence-", ".json");
        try {
            Files.write(staged, (receipt.toString() + "\n")
                    .getBytes(StandardCharsets.UTF_8));
            Files.move(staged, output, java.nio.file.StandardCopyOption
                    .REPLACE_EXISTING, java.nio.file.StandardCopyOption
                    .ATOMIC_MOVE);
        } finally {
            Files.deleteIfExists(staged);
        }
        System.out.println(receipt);
    }

    static JsonObject resolve(Path traceDir, String test, File skeletons,
                              File scopeFile, File graph, String check)
            throws Exception {
        return resolve(traceDir, test, skeletons, scopeFile, graph, check, null);
    }

    static JsonObject resolve(Path traceDir, String test, File skeletons,
                              File scopeFile, File graph, String check,
                              String throwSite)
            throws Exception {
        Path traceFile = traceDir.resolve("runtime_trace.jsonl");
        Path scheduleFile = traceDir.resolve("schedule.jsonl");
        String traceHash = sha256(traceFile);
        String scheduleHash = sha256(scheduleFile);
        JsonObject traceManifest = CausynthTraceRecorder.requireClosedTrace(
                traceDir.resolve("streaming_trace_manifest.json").toFile());
        CausynthTraceRecorder.requireTracedOver(traceManifest, scopeFile,
                graph, skeletons);
        StaticScopeMap scope = StaticScopeMap.read(scopeFile.toPath());
        if (check == null || check.isEmpty() || "auto".equals(check)) {
            check = soleDeclaredTargetGuard(scope);
        }
        Boolean fatal = scope.fatalArm(check);
        if (fatal == null) {
            throw new IOException("no unique declared fatal arm for check "
                    + check);
        }
        String targetRegion = targetRegion(scope, check, throwSite);
        CausynthTraceRecorder.TraceData trace =
                CausynthTraceRecorder.readStateTrace(traceDir.toFile(), test);
        if (!traceHash.equals(sha256(traceFile))
                || !scheduleHash.equals(sha256(scheduleFile))) {
            throw new IOException("CLOSED trace changed while resolving target");
        }
        List<StaticProgram.RegionRow> candidates = StaticProgram.regionRows(
                MapFields.readRows(skeletons),
                RuntimeSelectedRegionFinalizer.SKELETON_KIND, skeletons);

        List<RuntimeRegionPlanner.MethodEvent> unfolded = new ArrayList<>();
        for (RuntimeRegionPlanner.MethodEvent method : trace.methods) {
            unfolded.add(method.unfolded());
        }
        RuntimeRegionPlanner.Result exercised =
                RuntimeRegionPlanner.planSkeletonGraph(candidates, unfolded,
                        Collections.emptyList(), Collections.emptyList(),
                        Collections.emptyList(), Collections.emptySet(),
                        Collections.emptyMap());
        if (exercised.runtimeInstances.isEmpty()) {
            throw new IOException("NO_REGION_ACTIVATION");
        }
        Path selected = Files.createTempFile("mallory-selected-skeletons-",
                ".jsonl");
        RuntimeRegionPlanner.Result activations;
        try {
            CausynthTraceRecorder.writeSelectedSkeletons(skeletons,
                    selected.toFile(), exercised.runtimeInstances);
            List<StaticProgram.RegionRow> selectedRows =
                    StaticProgram.regionRows(MapFields.readRows(
                            selected.toFile()),
                            RuntimeSelectedRegionFinalizer.SKELETON_KIND,
                            selected.toFile());
            activations = RuntimeRegionPlanner.planSkeletonGraph(selectedRows,
                    trace.methods, trace.execution, trace.fields,
                    trace.protocol, Collections.emptySet(),
                    Collections.emptyMap());
        } finally {
            Files.deleteIfExists(selected);
        }

        JsonArray reached = new JsonArray();
        Set<String> addresses = new LinkedHashSet<>();
        List<JsonObject> eligible = new ArrayList<>();
        Map<Long, RuntimeRegionPlanner.MethodEvent> methodByCall =
                new LinkedHashMap<>();
        for (RuntimeRegionPlanner.MethodEvent method : trace.methods) {
            methodByCall.put(method.callId, method);
        }
        for (RuntimeRegionPlanner.RuntimeEvent event : trace.execution) {
            if (!"BRANCH".equals(event.kind)
                    || !check.equals(event.siteId)
                    || event.outcome == null || event.callId <= 0L
                    || fatal.equals(event.outcome)) {
                continue;
            }
            List<Map<String, Object>> owners = owners(
                    activations.runtimeInstances, targetRegion, event.callId);
            if (owners.size() != 1) {
                throw new IOException("target branch event " + event.seq
                        + " has " + owners.size()
                        + " exact containing activations");
            }
            String address = String.valueOf(
                    owners.get(0).get("occurrenceAddress"));
            if (address.isEmpty() || "null".equals(address)) {
                throw new IOException("target branch event " + event.seq
                        + " has no recorded occurrence address");
            }
            JsonObject row = new JsonObject();
            row.addProperty("eventSeq", event.seq);
            row.addProperty("callId", event.callId);
            row.addProperty("observedOutcome", event.outcome);
            row.addProperty("occurrenceAddress", address);
            row.addProperty("activationRegionId", String.valueOf(
                    owners.get(0).get("regionId")));
            RuntimeRegionPlanner.MethodEvent method = methodByCall.get(
                    event.callId);
            if (method == null) throw new IOException("target branch event "
                    + event.seq + " has no exact method frame");
            row.addProperty("sourceRole", method.source == null ? ""
                    : method.source.role());
            row.addProperty("sourceKey", method.sourceKey);
            row.addProperty("threadName", method.threadName);
            row.addProperty("remoteParentSpanId", method.remoteParentSpanId);
            reached.add(row);
            eligible.add(row);
            addresses.add(address);
        }
        if (eligible.isEmpty()) {
            throw new IOException("TARGET_CHECK_NOT_OBSERVED: " + check);
        }
        JsonObject selectedEvent = selectOccurrence(eligible);
        JsonObject receipt = new JsonObject();
        receipt.addProperty("schemaVersion", 1);
        receipt.addProperty("kind", "MALLORY_OBSERVED_TARGET_OCCURRENCE");
        receipt.addProperty("test", test);
        receipt.addProperty("checkSiteId", check);
        receipt.addProperty("targetRegionId", targetRegion);
        if (throwSite != null && !throwSite.isEmpty()) {
            receipt.addProperty("throwSiteId", throwSite);
        }
        receipt.addProperty("fatalOutcome", fatal);
        receipt.addProperty("observationKind", "NONFATAL_BRANCH_OUTCOME");
        receipt.addProperty("selectionPolicy",
                "PREFER_REGISTERED_NON_CLIENT_SOURCE_THEN_EARLIEST");
        receipt.addProperty("selectedOccurrenceAddress",
                selectedEvent.get("occurrenceAddress").getAsString());
        receipt.addProperty("selectedEventSeq",
                selectedEvent.get("eventSeq").getAsLong());
        receipt.addProperty("selectedCallId",
                selectedEvent.get("callId").getAsLong());
        receipt.addProperty("reachedEventCount", reached.size());
        receipt.addProperty("distinctReachedOccurrenceCount",
                addresses.size());
        receipt.add("reachedEvents", reached);
        receipt.addProperty("traceManifestSha256", sha256(traceDir.resolve(
                "streaming_trace_manifest.json")));
        receipt.addProperty("runtimeTraceSha256", traceHash);
        receipt.addProperty("scheduleSha256", scheduleHash);
        receipt.addProperty("scopeMapSha256", sha256(scopeFile.toPath()));
        receipt.addProperty("candidateGraphSha256", sha256(graph.toPath()));
        receipt.addProperty("regionSkeletonsSha256", sha256(
                skeletons.toPath()));
        return receipt;
    }

    /** Prefer an observed server-side invocation over setup in the test
     * client. This uses GraphChecker source registration, never a class-name
     * or case-specific occurrence ordinal. Preserve every candidate above.
     */
    static JsonObject selectOccurrence(List<JsonObject> eligible) {
        JsonObject best = null;
        for (JsonObject row : eligible) {
            if (best == null || occurrenceRank(row) < occurrenceRank(best)
                    || occurrenceRank(row) == occurrenceRank(best)
                    && row.get("eventSeq").getAsLong()
                            < best.get("eventSeq").getAsLong()) best = row;
        }
        return best;
    }

    private static int occurrenceRank(JsonObject row) {
        String role = row.get("sourceRole").getAsString();
        return role.isEmpty() || "CLIENT".equals(role) || "TEST".equals(role)
                ? 1 : 0;
    }

    static List<Map<String, Object>> owners(
            List<Map<String, Object>> activations, String targetRegion,
            long callId) {
        List<Map<String, Object>> found = new ArrayList<>();
        for (Map<String, Object> activation : activations) {
            if (!targetRegion.equals(activation.get("regionId"))) {
                Object folded = activation.get("foldedRegionIds");
                if (!(folded instanceof List<?>)
                        || !((List<?>) folded).contains(targetRegion)) {
                    continue;
                }
            }
            if (MapFields.longValues(activation.get("callIds"))
                    .contains(callId)) {
                found.add(activation);
            }
        }
        return found;
    }

    private static String targetRegion(StaticScopeMap scope, String check,
                                       String throwSite)
            throws IOException {
        Set<String> regions = new LinkedHashSet<>();
        for (StaticScopeMap.Site target : scope.targetSites()) {
            if ((throwSite == null || throwSite.isEmpty()
                    || throwSite.equals(target.siteId))
                    && target.guards.contains(check)
                    && !target.regionId.isEmpty()) {
                regions.add(target.regionId);
            }
        }
        if (regions.size() != 1) {
            throw new IOException("check " + check + " maps to "
                    + regions.size() + " target regions");
        }
        return regions.iterator().next();
    }

    /** The static target map itself chooses a guard when it names exactly one. */
    private static String soleDeclaredTargetGuard(StaticScopeMap scope)
            throws IOException {
        Set<String> guards = new LinkedHashSet<>();
        for (StaticScopeMap.Site target : scope.targetSites()) {
            guards.addAll(target.guards);
        }
        if (guards.size() != 1) {
            throw new IOException("target scope declares " + guards.size()
                    + " controlling guards; exact check site is required");
        }
        return guards.iterator().next();
    }

    private static String sha256(Path path) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = Files.newInputStream(path)) {
            byte[] buffer = new byte[65536];
            int count;
            while ((count = input.read(buffer)) >= 0) {
                digest.update(buffer, 0, count);
            }
        }
        byte[] hash = digest.digest();
        StringBuilder result = new StringBuilder();
        for (byte value : hash) result.append(String.format("%02x", value & 255));
        return result.toString();
    }

    private static Map<String, String> options(String[] args) {
        if (args.length % 2 != 0) throw new IllegalArgumentException(
                "expected --name value pairs");
        Map<String, String> result = new LinkedHashMap<>();
        for (int i = 0; i < args.length; i += 2) {
            if (!args[i].startsWith("--")
                    || result.put(args[i], args[i + 1]) != null) {
                throw new IllegalArgumentException("invalid option "
                        + args[i]);
            }
        }
        return result;
    }

    private static String required(Map<String, String> options,
                                   String name) {
        String value = options.get(name);
        if (value == null || value.isEmpty()) {
            throw new IllegalArgumentException("missing " + name);
        }
        return value;
    }

    private static Path path(Map<String, String> options, String name) {
        return new File(required(options, name)).toPath();
    }
}
