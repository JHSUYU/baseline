package edu.uva.liftlab.mallory.graphcheckerstatic;

import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Collections;
import java.util.Deque;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.function.Function;
import java.util.function.Predicate;

/**
 * A switchable port of GraphChecker's static region-skeleton selection.
 *
 * <p>Provenance: GraphChecker revision c4a90033c654737206466ed36ce837c5b3c12457,
 * causynth/{@code StaticProgram.closure, StaticProgram.invocationTarget,
 * SymbolicRegionPlanner.Anchors, failureRelevantState, forwardClosure,
 * declareCommunicationPorts}. The control flow and ordered closures below
 * follow those methods. Adaptations are an explicit input DTO in place of
 * StaticProgram's mutable fields, an explicit constant-field catalog in
 * place of Soot Scene, and a minimal region/port row contract.</p>
 */
public final class GraphCheckerRegionPlanner {
    public static final String STATE_WRITER_ENTRY = "STATE_WRITER_ENTRY";
    public static final String EXPLICIT_FAULT_ENTRY = "EXPLICIT_FAULT_ENTRY";
    public static final String FAILURE_TARGET_ENTRY = "FAILURE_TARGET_ENTRY";

    public static final class Input {
        public final Set<String> selectedMethods = new LinkedHashSet<>();
        public final List<Map<String, Object>> edges = new ArrayList<>();
        public final Map<String, String> executionContextAuthorities = new LinkedHashMap<>();
        public final List<Map<String, Object>> communicationCallSites = new ArrayList<>();
        public final List<List<String>> demandedDoorChains = new ArrayList<>();
        /** Names classified by GraphChecker LibraryCatalog.demandedMarker. */
        public final Set<String> demandedMarkerNames = new LinkedHashSet<>();
        public final Set<String> constantFields = new LinkedHashSet<>();
        public String targetMethod = "";
    }

    public static final class Result {
        public final List<Map<String, Object>> regions = new ArrayList<>();
        public final List<Map<String, Object>> gaps = new ArrayList<>();

        /** Port of RegionSkeletonInstrumentationSelection.regionRootsFromEnvironment. */
        public Map<String, String> regionRoots() {
            Map<String, String> roots = new LinkedHashMap<>();
            for (Map<String, Object> region : regions) {
                roots.putIfAbsent(text(region.get("rootMethod")), text(region.get("regionId")));
            }
            return roots;
        }

        /** Port of RegionSkeletonInstrumentationSelection.methodsFromEnvironment. */
        public Set<String> instrumentedMethods() {
            Set<String> methods = new LinkedHashSet<>();
            for (Map<String, Object> region : regions) methods.addAll(strings(region.get("methods")));
            return methods;
        }

        public List<String> regionsHolding(String method) {
            List<String> ids = new ArrayList<>();
            for (Map<String, Object> region : regions) {
                if (strings(region.get("methods")).contains(method)) ids.add(text(region.get("regionId")));
            }
            return ids;
        }
    }

    private GraphCheckerRegionPlanner() { }

    /** Port of SymbolicRegionPlanner.planSelectedSkeleton. */
    public static Result plan(Input input) {
        if (input == null) throw new IllegalArgumentException("input is null");
        Result result = new Result();
        Anchors anchors = new Anchors(input);
        anchors.root(result, anchors.authorities.keySet(), anchors.authorities::get,
                method -> false);
        anchors.root(result, communicationEndpoints(input),
                method -> "COMMUNICATION_ENTRY",
                method -> !result.regionsHolding(method).isEmpty());
        anchors.root(result, anchors.state, method -> STATE_WRITER_ENTRY,
                method -> false);
        fold(result, input.demandedDoorChains);
        declareCommunicationPorts(input, result);
        return result;
    }

    /** Port of SymbolicRegionPlanner.Anchors, with GraphChecker edge keys retained. */
    private static final class Anchors {
        final Input input;
        final Set<String> selected = new LinkedHashSet<>();
        final Map<String, Set<String>> outgoing = new LinkedHashMap<>();
        final Map<String, String> authorities = new LinkedHashMap<>();
        final Set<String> failure = new LinkedHashSet<>();
        final Set<String> faults = new LinkedHashSet<>();
        final Set<String> communication;
        final Set<String> state = new LinkedHashSet<>();

        Anchors(Input input) {
            this.input = input;
            selected.addAll(input.selectedMethods);
            selected.remove("");
            communication = communicationEndpoints(input);
            communication.retainAll(selected);
            Set<String> demandedState = failureRelevantState(input.edges,
                    input.constantFields);
            for (String method : selected) outgoing.put(method, new LinkedHashSet<>());
            for (Map<String, Object> edge : input.edges) {
                String method = text(edge.get("method"));
                String transfer = text(edge.get("transferKind"));
                if (text(edge.get("toCell")).contains("#exception:")
                        && selected.contains(method)) failure.add(method);
                if (("HEAP_READ".equals(transfer) || "HEAP_WRITE".equals(transfer))
                        && selected.contains(method) && !constructor(method)
                        && demandedState.contains(stateDeclaration(edge, transfer))) {
                    state.add(method);
                }
                String callee = invocationTarget(edge);
                if (selected.contains(method) && selected.contains(callee)
                        && !method.equals(callee)) outgoing.get(method).add(callee);
            }
            authorities.putAll(input.executionContextAuthorities);
            if (!input.targetMethod.isEmpty())
                authorities.putIfAbsent(input.targetMethod, FAILURE_TARGET_ENTRY);
            for (Map<String, Object> edge : input.edges) {
                String method = text(edge.get("method"));
                if (selected.contains(method) && Boolean.TRUE.equals(
                        edge.get("explicitSymbolicFault"))
                        && !input.demandedMarkerNames.contains(
                                text(edge.get("symbolicName")))) {
                    faults.add(method);
                    authorities.putIfAbsent(method, EXPLICIT_FAULT_ENTRY);
                }
            }
        }

        void root(Result result, Collection<String> entries,
                  Function<String, String> authority, Predicate<String> skipped) {
            List<String> ordered = new ArrayList<>(entries);
            Collections.sort(ordered);
            for (String entry : ordered) {
                if (!selected.contains(entry) || hasSkeletonRoot(result, entry)
                        || skipped.test(entry)) continue;
                String kind = authority.apply(entry);
                if (constructor(entry) && !FAILURE_TARGET_ENTRY.equals(kind)) continue;
                addSkeleton(result, entry, kind);
            }
        }

        void addSkeleton(Result result, String root, String authority) {
            List<String> methods = forwardClosure(root, outgoing, authorities);
            List<String> failed = intersections(methods, failure);
            List<String> communicating = intersections(methods, communication);
            List<String> stateful = intersections(methods, state);
            boolean explicitFault = faults.contains(root);
            List<String> fault = explicitFault ? Collections.singletonList(root)
                    : Collections.emptyList();
            List<String> anchors = union(fault, failed, communicating, stateful);
            if (anchors.isEmpty()) return;
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("schemaVersion", 3);
            row.put("kind", "REGION_SKELETON");
            row.put("regionId", "REGION." + UUID.nameUUIDFromBytes(
                    (authority + "\n" + root).getBytes(StandardCharsets.UTF_8)));
            row.put("rootMethod", root);
            row.put("rootAuthority", authority);
            row.put("anchorMethod", anchors.get(0));
            row.put("anchorMethods", anchors);
            row.put("methods", methods);
            row.put("selection", !failed.isEmpty() ? "EXCEPTION_CONTEXT"
                    : explicitFault ? "EXPLICIT_FAULT_CONTEXT"
                    : !communicating.isEmpty() ? "COMMUNICATION_CONTEXT"
                    : "STATE_CONTEXT");
            result.regions.add(row);
        }
    }

    /** A demanded door's chain joins its site's region; it never creates a root. */
    private static void fold(Result result, List<List<String>> doorChains) {
        for (List<String> chain : doorChains) {
            if (chain.isEmpty()) continue;
            for (Map<String, Object> region : result.regions) {
                List<String> methods = strings(region.get("methods"));
                if (!methods.contains(chain.get(0))) continue;
                Set<String> held = new java.util.TreeSet<>(methods);
                held.addAll(chain);
                region.put("methods", new ArrayList<>(held));
            }
        }
    }

    /** Port of SymbolicRegionPlanner.declareCommunicationPorts and endpoint sides. */
    private static void declareCommunicationPorts(Input input, Result result) {
        for (Map<String, Object> region : result.regions) {
            Map<String, Map<String, Object>> ports = new LinkedHashMap<>();
            for (Map<String, Object> flow : input.communicationCallSites) {
                declareWireEndpoint(result, region, flow, rows(flow.get("producers")),
                        "OUT", ports);
                declareWireEndpoint(result, region, flow, rows(flow.get("consumers")),
                        "IN", ports);
            }
            if (!ports.isEmpty()) region.put("communicationPorts",
                    new ArrayList<>(ports.values()));
        }
        for (Map<String, Object> flow : input.communicationCallSites) {
            for (String side : new String[]{"producers", "consumers"}) {
                for (Map<String, Object> capture : rows(flow.get(side))) {
                    String method = text(capture.get("definitionMethod"));
                    if (!result.regionsHolding(method).isEmpty()) continue;
                    Map<String, Object> gap = new LinkedHashMap<>();
                    gap.put("kind", "COMMUNICATION_REQUEST_PORT_UNRESOLVED");
                    gap.put("reason", "NO_REGION_HOLDS_WIRE_CAPTURE");
                    gap.put("method", method);
                    gap.put("portId", text(flow.get("portId")));
                    result.gaps.add(gap);
                }
            }
        }
    }

    private static void declareWireEndpoint(Result result, Map<String, Object> region,
                                            Map<String, Object> flow,
                                            List<Map<String, Object>> captures,
                                            String side,
                                            Map<String, Map<String, Object>> ports) {
        for (Map<String, Object> capture : captures) {
            String method = text(capture.get("definitionMethod"));
            if (!strings(region.get("methods")).contains(method)) continue;
            String portId = text(flow.get("portId"));
            if (portId.isEmpty()) continue;
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("portId", portId);
            row.put("regionPortSide", side);
            row.put("sourceKind", "COMMUNICATION_SITE_PORT");
            row.put("dependencyRole", "VALUE_FRONTIER");
            for (String key : new String[]{"name", "javaType", "exchangeSiteKey"})
                row.put(key, flow.get(key));
            row.put("handoffLeafPath", portId);
            row.putAll(capture);
            String key = side + "\n" + portId + "\n"
                    + text(capture.get("callSiteId")) + "\n"
                    + text(capture.get("outputCaptureKind")) + "\n"
                    + text(capture.get("argumentIndex"));
            ports.putIfAbsent(key, row);
        }
    }

    private static boolean hasSkeletonRoot(Result result, String method) {
        for (Map<String, Object> region : result.regions)
            if (method.equals(text(region.get("rootMethod")))) return true;
        return false;
    }

    private static Set<String> communicationEndpoints(Input input) {
        Set<String> entries = new LinkedHashSet<>();
        for (Map<String, Object> site : input.communicationCallSites) {
            for (String side : new String[]{"producers", "consumers"})
                for (Map<String, Object> capture : rows(site.get(side)))
                    entries.add(text(capture.get("definitionMethod")));
        }
        entries.remove("");
        return entries;
    }

    private static List<String> forwardClosure(String root,
            Map<String, Set<String>> outgoing, Map<String, String> authorities) {
        List<String> result = new ArrayList<>(closure(Collections.singletonList(root), method -> {
            List<String> next = new ArrayList<>(outgoing.getOrDefault(method,
                    Collections.emptySet()));
            Collections.sort(next);
            next.removeIf(candidate -> !root.equals(candidate)
                    && authorities.containsKey(candidate));
            return next;
        }));
        Collections.sort(result);
        return result;
    }

    /** Port of StaticProgram.closure: FIFO, once per node, null is early stop. */
    static <T> Set<T> closure(Collection<? extends T> seeds,
                              Function<T, Collection<T>> adjacency) {
        Set<T> visited = new LinkedHashSet<>();
        Deque<T> work = new ArrayDeque<>(seeds);
        while (!work.isEmpty()) {
            T node = work.removeFirst();
            if (!visited.add(node)) continue;
            Collection<T> next = adjacency.apply(node);
            if (next == null) break;
            work.addAll(next);
        }
        return visited;
    }

    /** Port of SymbolicRegionPlanner.failureRelevantState. */
    static Set<String> failureRelevantState(Collection<Map<String, Object>> edges,
                                            Set<String> constantFields) {
        Map<String, List<Map<String, Object>>> incoming = new LinkedHashMap<>();
        List<String> seeds = new ArrayList<>();
        for (Map<String, Object> edge : edges) {
            String target = text(edge.get("toCell"));
            if (!target.isEmpty()) incoming.computeIfAbsent(target,
                    ignored -> new ArrayList<>()).add(edge);
            if (target.contains("#exception:")) seeds.add(target);
        }
        Set<String> demanded = new LinkedHashSet<>();
        closure(seeds, cell -> {
            List<String> next = new ArrayList<>();
            for (Map<String, Object> edge : incoming.getOrDefault(cell,
                    Collections.emptyList())) {
                String source = text(edge.get("fromCell"));
                if ("HEAP_READ".equals(text(edge.get("transferKind")))
                        && declaredField(source) && !constantFields.contains(source))
                    demanded.add(source);
                if (!source.isEmpty()) next.add(source);
            }
            return next;
        });
        return demanded;
    }

    private static String stateDeclaration(Map<String, Object> edge, String transfer) {
        String cell = text(edge.get("HEAP_READ".equals(transfer)
                ? "fromCell" : "toCell"));
        return declaredField(cell) ? cell : "";
    }

    private static boolean declaredField(String cell) {
        return cell.startsWith("<") && cell.endsWith(">")
                && cell.contains(":") && !cell.contains("(");
    }

    private static String invocationTarget(Map<String, Object> edge) {
        if ("DYNAMIC_DISPATCH".equals(text(edge.get("transferKind")))
                && "dispatch_activation".equals(text(edge.get("kind")))) {
            String activation = text(edge.get("toCell"));
            if (activation.endsWith(".activation"))
                return activation.substring(0,
                        activation.length() - ".activation".length());
        }
        return text(edge.get("invoke"));
    }

    private static boolean constructor(String method) {
        return method != null && (method.contains(" <init>(")
                || method.contains(" <clinit>("));
    }

    private static List<String> intersections(List<String> ordered, Set<String> candidates) {
        List<String> result = new ArrayList<>();
        for (String value : ordered) if (candidates.contains(value)) result.add(value);
        return result;
    }

    @SafeVarargs
    private static List<String> union(List<String>... groups) {
        Set<String> unique = new LinkedHashSet<>();
        for (List<String> group : groups) unique.addAll(group);
        return new ArrayList<>(unique);
    }

    private static String text(Object value) { return value == null ? "" : String.valueOf(value); }

    private static List<String> strings(Object value) {
        List<String> result = new ArrayList<>();
        if (value instanceof Collection<?>) for (Object item : (Collection<?>) value)
            if (!text(item).isEmpty()) result.add(text(item));
        return result;
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> rows(Object value) {
        List<Map<String, Object>> result = new ArrayList<>();
        if (value instanceof Collection<?>) for (Object item : (Collection<?>) value)
            if (item instanceof Map<?, ?>) result.add((Map<String, Object>) item);
        return result;
    }
}
