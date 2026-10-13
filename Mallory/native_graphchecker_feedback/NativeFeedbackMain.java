package edu.uva.liftlab.mallory.nativefeedback;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import edu.uva.liftlab.graphchecker.contract.ActivationRow;
import edu.uva.liftlab.graphchecker.contract.AttachRow;
import edu.uva.liftlab.graphchecker.contract.DecisionRow;
import edu.uva.liftlab.graphchecker.contract.Endpoint;
import edu.uva.liftlab.graphchecker.contract.ExportRow;
import edu.uva.liftlab.graphchecker.contract.GapRow;
import edu.uva.liftlab.graphchecker.contract.OccurrenceAddress;
import edu.uva.liftlab.graphchecker.contract.ReadRow;
import edu.uva.liftlab.graphchecker.contract.SessionReader;
import edu.uva.liftlab.graphchecker.contract.TargetRow;
import edu.uva.liftlab.graphchecker.contract.Task;
import edu.uva.liftlab.graphchecker.contract.WriteRow;
import edu.uva.liftlab.graphchecker.explore.Branches;
import edu.uva.liftlab.graphchecker.explore.ClosurePlanner;
import edu.uva.liftlab.graphchecker.explore.Corpus;
import edu.uva.liftlab.graphchecker.plan.StaticScopeMap;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Opt-in ingress from a real GraphChecker SessionReader into Mallory feedback.
 * The occurrence membership comes from the unmodified GraphChecker
 * Corpus/Branches/ClosurePlanner. Observed edge rows below are evidence
 * attached to that membership; they do not add planner members or infer
 * static candidates as runtime edges.
 */
public final class NativeFeedbackMain {
    private static final Gson JSON = new Gson();

    private NativeFeedbackMain() { }

    private static void requireSourceBuiltOriginalClasses() throws Exception {
        String expected = System.getProperty("mallory.native.expectedEngineJar", "");
        if (expected.isEmpty()) {
            throw new IllegalArgumentException("expected source-built engine JAR is unstated");
        }
        Path selected = Paths.get(expected).toRealPath();
        for (Class<?> original : new Class<?>[] {SessionReader.class,
                Corpus.class, Branches.class, ClosurePlanner.class,
                StaticScopeMap.class}) {
            Path loaded = Paths.get(original.getProtectionDomain()
                    .getCodeSource().getLocation().toURI()).toRealPath();
            if (!selected.equals(loaded)) {
                throw new IllegalStateException(original.getName()
                        + " loaded from " + loaded + " instead of " + selected);
            }
        }
    }

    private static Map<String, Object> row(Object... parts) {
        Map<String, Object> result = new LinkedHashMap<>();
        for (int i = 0; i < parts.length; i += 2) {
            result.put((String) parts[i], parts[i + 1]);
        }
        return result;
    }

    private static String locationKey(ReadRow read) {
        return read.location().kind() + "/" + read.location().owner()
                + "#" + read.location().slot();
    }

    private static String locationKey(WriteRow write) {
        return write.location().kind() + "/" + write.location().owner()
                + "#" + write.location().slot();
    }

    private static String writeKey(WriteRow write) {
        return write.sessionId() + "\n" + locationKey(write) + "\n"
                + write.version();
    }

    private static String readKey(ReadRow read) {
        return read.sessionId() + "\n" + locationKey(read) + "\n"
                + read.observedVersion();
    }

    private static String family(OccurrenceAddress occurrence) {
        return occurrence.node().node() + "\n" + occurrence.regionId();
    }

    private static void addEdge(List<Map<String, Object>> edges,
                                Set<String> closure, String type,
                                OccurrenceAddress producer,
                                OccurrenceAddress consumer,
                                String site, Map<String, Object> evidence) {
        if (!closure.contains(producer.id()) || !closure.contains(consumer.id())) {
            return;
        }
        Map<String, Object> edge = row("type", type,
                "producerOccurrenceId", producer.id(),
                "consumerOccurrenceId", consumer.id(),
                "producerOccurrence", producer.render(),
                "consumerOccurrence", consumer.render(),
                "site", site,
                "family", type + "\n" + site + "\n" + family(producer)
                        + "\n" + family(consumer),
                "evidence", evidence);
        edges.add(edge);
    }

    private static Map<String, Object> gap(GapRow item) {
        return row("kind", item.kind().name(), "class", item.cls().name(),
                "subject", item.subject(), "detail", item.detail());
    }

    private static Map<String, Object> targetEvidence(TargetRow target) {
        return row("seq", target.seq(), "siteId", target.anchorSiteId(),
                "occurrenceId", target.occurrence().id(),
                "occurrence", target.occurrence().render(),
                "reachedAnchor", target.reachedAnchor(),
                "observedFatal", target.observedFatal(),
                "phiTerm", target.phiTerm());
    }

    private static SessionReader readSession(Path iteration) throws Exception {
        List<SessionReader> sessions = SessionReader.readAll(iteration,
                Collections.<SessionReader>emptyList());
        if (sessions.size() != 1) {
            throw new IllegalArgumentException("one trial must contain exactly one native session; got "
                    + sessions.size());
        }
        SessionReader session = sessions.get(0);
        if (!session.incomplete().isEmpty() || session.manifest() == null) {
            throw new IllegalArgumentException("incomplete native session: "
                    + session.incomplete());
        }
        return session;
    }

    private static Map<String, Object> analyze(SessionReader session,
                                                Corpus corpus, StaticScopeMap scope,
                                                String site, String expected,
                                                int maxTasks) throws Exception {
        Set<OccurrenceAddress> matching = new LinkedHashSet<>();
        List<Map<String, Object>> targetRows = new ArrayList<>();
        for (TargetRow target : session.targets()) {
            if (!site.equals(target.anchorSiteId())) continue;
            if (!expected.equals("-") && !expected.equals(target.occurrence().id())) {
                continue;
            }
            matching.add(target.occurrence());
            targetRows.add(targetEvidence(target));
        }
        if (matching.size() != 1) {
            throw new IllegalArgumentException("target site/occurrence must resolve to exactly one "
                    + "native occurrence; found " + matching.size());
        }
        OccurrenceAddress anchor = matching.iterator().next();
        List<GapRow> branchGaps = new ArrayList<>();
        Branches branches = Branches.of(corpus,
                Collections.singletonList(anchor), branchGaps);
        ClosurePlanner.Plan plan = ClosurePlanner.plan(corpus, anchor,
                maxTasks, scope, branches);
        Set<String> closure = new LinkedHashSet<>();
        Map<String, String> familyById = new LinkedHashMap<>();
        List<Map<String, Object>> members = new ArrayList<>();
        for (Task task : plan.tasks) {
            OccurrenceAddress occurrence = task.focused();
            if (closure.add(occurrence.id())) {
                familyById.put(occurrence.id(), family(occurrence));
                members.add(row("occurrenceId", occurrence.id(),
                        "occurrence", occurrence.render(),
                        "node", occurrence.node().render(),
                        "regionId", occurrence.regionId(),
                        "family", family(occurrence),
                        "why", plan.why.get(task.taskId()),
                        "flipSites", plan.flipSites.get(task.taskId())));
            }
        }
        if (!closure.contains(anchor.id())) {
            throw new IllegalStateException("native closure omitted exact target occurrence");
        }
        Set<String> activated = new HashSet<>();
        for (ActivationRow activation : session.activations()) {
            activated.add(activation.occurrence().id());
        }
        List<Map<String, Object>> edges = new ArrayList<>();
        Map<String, List<ExportRow>> exports = new HashMap<>();
        for (ExportRow export : session.exports()) {
            exports.computeIfAbsent(export.endpoint().id(), ignored ->
                    new ArrayList<ExportRow>()).add(export);
        }
        for (AttachRow attach : session.attaches()) {
            Endpoint producer = attach.producer();
            if (producer == null || !activated.contains(producer.occurrence().id())
                    || !activated.contains(attach.endpoint().occurrence().id())) {
                continue;
            }
            // The attach's explicit pairing, plus its recorded export, is
            // the native WIRE evidence. Port similarity alone is insufficient.
            List<ExportRow> paired = exports.getOrDefault(producer.id(),
                    Collections.<ExportRow>emptyList());
            // The endpoint is exact, but repeated exports at that endpoint
            // leave the particular value ambiguous without further evidence.
            if (paired.size() != 1) continue;
            ExportRow export = paired.get(0);
            addEdge(edges, closure, "WIRE", producer.occurrence(),
                    attach.endpoint().occurrence(), attach.endpoint().site(),
                    row("exportSeq", export.seq(), "attachSeq", attach.seq(),
                            "producerEndpointId", producer.id(),
                            "consumerEndpointId", attach.endpoint().id(),
                            "correlationId", attach.correlationId(),
                            "pairedBy", attach.pairedBy()));
        }
        // An activation's explicit anchorProducer is a control/message-start
        // fact in the original ActivationRow contract, distinct from a WIRE
        // value handoff. No guessed thread-order edges are emitted.
        for (ActivationRow activation : session.activations()) {
            Endpoint producer = activation.anchorProducer();
            if (producer == null || !activated.contains(producer.occurrence().id())
                    || !producer.id().equals(
                        activation.occurrence().context() instanceof
                            edu.uva.liftlab.graphchecker.contract.CausalContext.Anchor
                        ? ((edu.uva.liftlab.graphchecker.contract.CausalContext.Anchor)
                            activation.occurrence().context()).producerEndpointId()
                        : "")) {
                continue;
            }
            addEdge(edges, closure, "MESSAGE_START", producer.occurrence(),
                    activation.occurrence(), producer.site(),
                    row("anchorProducerEndpointId", producer.id(),
                            "activationTaskId", activation.taskId()));
        }
        Map<String, List<WriteRow>> writes = new HashMap<>();
        for (WriteRow write : session.writes()) {
            if (!write.initial()) {
                writes.computeIfAbsent(writeKey(write), ignored ->
                        new ArrayList<WriteRow>()).add(write);
            }
        }
        for (ReadRow read : session.reads()) {
            if (read.observedVersion() == ReadRow.UNKNOWN_VERSION) continue;
            List<WriteRow> candidates = writes.getOrDefault(readKey(read),
                    Collections.<WriteRow>emptyList());
            if (candidates.size() != 1) continue;
            WriteRow write = candidates.get(0);
            // A shared heap location is local to one process. A version name
            // from another process is never enough to claim a state edge.
            if (!write.endpoint().occurrence().node().equals(
                    read.endpoint().occurrence().node())
                    || write.seq() > read.seq()) continue;
            addEdge(edges, closure, "STATE", write.endpoint().occurrence(),
                    read.endpoint().occurrence(), read.endpoint().site(),
                    row("writeSeq", write.seq(), "readSeq", read.seq(),
                            "location", locationKey(read),
                            "observedVersion", read.observedVersion(),
                            "writerEndpointId", write.endpoint().id(),
                            "readerEndpointId", read.endpoint().id()));
        }
        edges.sort(Comparator.comparing((Map<String, Object> edge) ->
                (String) edge.get("type")).thenComparing(edge ->
                (String) edge.get("producerOccurrenceId")).thenComparing(edge ->
                (String) edge.get("consumerOccurrenceId")));
        Set<String> coverage = new LinkedHashSet<>();
        List<Map<String, Object>> decisions = new ArrayList<>();
        for (DecisionRow decision : session.decisions()) {
            if (!closure.contains(decision.occurrence().id())) continue;
            String key = decision.siteId() + "\n" + decision.outcome();
            coverage.add(key);
            decisions.add(row("occurrenceId", decision.occurrence().id(),
                    "seq", decision.seq(), "siteId", decision.siteId(),
                    "ordinal", decision.ordinal(), "outcome", decision.outcome(),
                    "term", decision.term()));
        }
        List<Map<String, Object>> gaps = new ArrayList<>();
        for (GapRow item : session.gaps()) gaps.add(gap(item));
        for (GapRow item : branchGaps) gaps.add(gap(item));
        for (GapRow item : plan.gaps) gaps.add(gap(item));
        List<String> waiting = new ArrayList<>();
        for (OccurrenceAddress occurrence : plan.waiting) {
            waiting.add(occurrence.id());
        }
        List<String> exposed = new ArrayList<>();
        for (OccurrenceAddress occurrence : plan.exposed.keySet()) {
            exposed.add(occurrence.id());
        }
        return row("schemaVersion", 1,
                "method", "original-graphchecker-corpus-closureplanner",
                "sessionId", session.sessionId(),
                "targetSiteId", site,
                "targetOccurrenceId", anchor.id(),
                "targetOccurrence", anchor.render(),
                "targetNodeName", anchor.node().node(),
                "targetRegionId", anchor.regionId(),
                "targetFamily", site + "\n" + family(anchor),
                "targetRows", targetRows,
                "closureMembers", members,
                "observedEdgesWithinClosure", edges,
                "branchObservationsWithinClosure", decisions,
                "branchCoverage", new ArrayList<>(coverage),
                "gaps", gaps,
                "truncated", new ArrayList<>(plan.truncated),
                "waiting", waiting,
                "exposed", exposed,
                "scopeMapStated", scope.stated());
    }

    private static Map<String, Object> analyze(Path iteration, Path scopePath,
                                                String site, String expected,
                                                int maxTasks) throws Exception {
        SessionReader session = readSession(iteration);
        Corpus corpus = Corpus.read(iteration, null);
        StaticScopeMap scope = scopePath == null ? StaticScopeMap.empty()
                : StaticScopeMap.read(scopePath);
        return analyze(session, corpus, scope, site, expected, maxTasks);
    }

    private static void write(Path output, Object result) throws Exception {
        if (output.toAbsolutePath().getParent() != null) {
            Files.createDirectories(output.toAbsolutePath().getParent());
        }
        Files.write(output, (JSON.toJson(result) + "\n").getBytes(
                StandardCharsets.UTF_8));
    }

    private static List<Map<String, Object>> listTargets(Path iteration,
                                                          String site) throws Exception {
        return listTargets(readSession(iteration), site);
    }

    private static List<Map<String, Object>> listTargets(SessionReader session,
                                                          String site) {
        Map<String, Map<String, Object>> found = new LinkedHashMap<>();
        for (TargetRow target : session.targets()) {
            if (!site.equals(target.anchorSiteId())) continue;
            OccurrenceAddress occurrence = target.occurrence();
            found.putIfAbsent(occurrence.id(), row(
                    "occurrenceId", occurrence.id(),
                    "occurrence", occurrence.render(),
                    "nodeName", occurrence.node().node(),
                    "node", occurrence.node().render(),
                    "regionId", occurrence.regionId(),
                    "targetFamily", site + "\n" + family(occurrence)));
        }
        List<Map<String, Object>> result = new ArrayList<>(found.values());
        result.sort(Comparator.comparing(item -> (String) item.get("occurrenceId")));
        return result;
    }

    private static Map<String, Object> analyzeTargetSet(Path iteration,
            Path scopePath, String site, int maxTasks, Path actorsPath)
            throws Exception {
        SessionReader session = readSession(iteration);
        List<Map<String, Object>> listed = listTargets(session, site);
        Set<String> reached = new LinkedHashSet<>();
        List<Map<String, Object>> unreachedRows = new ArrayList<>();
        for (TargetRow target : session.targets()) {
            if (!site.equals(target.anchorSiteId())) continue;
            if (target.reachedAnchor()) {
                reached.add(target.occurrence().id());
            } else {
                unreachedRows.add(targetEvidence(target));
            }
        }
        Set<String> actors = null;
        if (actorsPath != null) {
            String[] names = JSON.fromJson(new String(Files.readAllBytes(actorsPath),
                    StandardCharsets.UTF_8), String[].class);
            if (names == null) throw new IllegalArgumentException("actor names must be an array");
            actors = new LinkedHashSet<>();
            for (String name : names) {
                if (name == null || name.isEmpty()) {
                    throw new IllegalArgumentException("actor name is empty");
                }
                actors.add(name);
            }
        }
        List<Map<String, Object>> selected = new ArrayList<>();
        boolean actorRowsSeen = false;
        Set<String> actorOccurrenceIds = new HashSet<>();
        for (Map<String, Object> item : listed) {
            if (actors != null && !actors.contains(item.get("nodeName"))) continue;
            actorRowsSeen = true;
            actorOccurrenceIds.add((String) item.get("occurrenceId"));
            if (reached.contains(item.get("occurrenceId"))) {
                selected.add(item);
            }
        }
        if (actors != null) {
            List<Map<String, Object>> actorRows = new ArrayList<>();
            for (Map<String, Object> target : unreachedRows) {
                if (actorOccurrenceIds.contains(target.get("occurrenceId"))) {
                    actorRows.add(target);
                }
            }
            unreachedRows = actorRows;
        }
        if (selected.isEmpty()) {
            return row("schemaVersion", 1, "targetSiteId", site,
                    "targets", selected, "perTargetOccurrences",
                    Collections.emptyList(), "siteTargetRowsSeen", actorRowsSeen,
                    "unreachedTargetRows", unreachedRows);
        }
        Corpus corpus = Corpus.read(iteration, null);
        StaticScopeMap scope = scopePath == null ? StaticScopeMap.empty()
                : StaticScopeMap.read(scopePath);
        List<Map<String, Object>> plans = new ArrayList<>();
        for (Map<String, Object> item : selected) {
            Map<String, Object> plan = analyze(session, corpus, scope, site,
                    (String) item.get("occurrenceId"), maxTasks);
            if (!item.get("targetFamily").equals(plan.get("targetFamily"))) {
                throw new IllegalStateException("native target family changed during analysis");
            }
            plans.add(plan);
        }
        return row("schemaVersion", 1, "targetSiteId", site,
                "targets", selected, "perTargetOccurrences", plans,
                "siteTargetRowsSeen", actorRowsSeen,
                "unreachedTargetRows", unreachedRows);
    }

    public static void main(String[] args) throws Exception {
        if (args.length == 7 && "--target-set".equals(args[0])) {
            requireSourceBuiltOriginalClasses();
            Path scope = "-".equals(args[2]) ? null : Paths.get(args[2]);
            if (scope != null && !Files.isRegularFile(scope)) {
                throw new IllegalArgumentException("scope map missing: " + scope);
            }
            int maxTasks = Integer.parseInt(args[4]);
            if (maxTasks <= 0) {
                throw new IllegalArgumentException("MAX_TASKS must be positive");
            }
            Path actors = "-".equals(args[5]) ? null : Paths.get(args[5]);
            write(Paths.get(args[6]), analyzeTargetSet(Paths.get(args[1]),
                    scope, args[3], maxTasks, actors));
            return;
        }
        if (args.length == 4 && "--list-targets".equals(args[0])) {
            requireSourceBuiltOriginalClasses();
            write(Paths.get(args[3]), row("schemaVersion", 1,
                    "targetSiteId", args[2],
                    "targets", listTargets(Paths.get(args[1]), args[2])));
            return;
        }
        if (args.length != 6) {
            throw new IllegalArgumentException("usage: NativeFeedbackMain ITERATION "
                    + "SCOPE_MAP_OR_DASH TARGET_SITE EXACT_OCCURRENCE_ID_OR_DASH "
                    + "MAX_TASKS OUTPUT_JSON");
        }
        requireSourceBuiltOriginalClasses();
        Path iteration = Paths.get(args[0]);
        Path scope = "-".equals(args[1]) ? null : Paths.get(args[1]);
        if (scope != null && !Files.isRegularFile(scope)) {
            throw new IllegalArgumentException("scope map missing: " + scope);
        }
        int maxTasks = Integer.parseInt(args[4]);
        if (maxTasks <= 0) throw new IllegalArgumentException("MAX_TASKS must be positive");
        Map<String, Object> result = analyze(iteration, scope, args[2],
                args[3], maxTasks);
        write(Paths.get(args[5]), result);
    }
}
