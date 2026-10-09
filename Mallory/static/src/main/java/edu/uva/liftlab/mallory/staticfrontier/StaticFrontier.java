package edu.uva.liftlab.mallory.staticfrontier;

import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import soot.Body;
import soot.Local;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.Trap;
import soot.Unit;
import soot.ValueBox;
import soot.jimple.AssignStmt;
import soot.jimple.FieldRef;
import soot.jimple.IfStmt;
import soot.jimple.InstanceInvokeExpr;
import soot.jimple.InvokeExpr;
import soot.jimple.LookupSwitchStmt;
import soot.jimple.ReturnStmt;
import soot.jimple.Stmt;
import soot.jimple.TableSwitchStmt;
import soot.jimple.ThrowStmt;
import soot.options.Options;
import soot.tagkit.BytecodeOffsetTag;
import soot.tagkit.Tag;
import soot.toolkits.graph.BriefUnitGraph;
import soot.toolkits.graph.MHGPostDominatorsFinder;
import soot.toolkits.scalar.SimpleLocalDefs;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * A deliberately conservative static frontier for a selected exception site.
 *
 * This is a new implementation. It does not infer runtime value versions,
 * message identities, or a precise causal closure. Every output row says why
 * the site was selected, and an incomplete analysis emits a gap rather than
 * silently treating its frontier as complete.
 */
public final class StaticFrontier {
    private final Map<String, MethodInfo> methods = new LinkedHashMap<>();
    private final Map<String, List<Site>> fieldWriters = new LinkedHashMap<>();
    private final Map<String, List<Site>> callers = new LinkedHashMap<>();
    private final Map<String, Site> selected = new LinkedHashMap<>();
    private final List<String> gaps = new ArrayList<>();
    private final Deque<Work> queue = new ArrayDeque<>();
    private final Set<String> expanded = new HashSet<>();
    private final Set<String> activeMethods = new LinkedHashSet<>();
    private int maxSites;
    private int maxCallDepth;
    private List<String> ioPatterns;
    private String sourceFile;

    private static final List<String> DEFAULT_IO = Arrays.asList(
            "java.io.", "java.nio.file.", "java.net.",
            "org.apache.hadoop.ipc.", "org.apache.hadoop.hdfs.protocol.",
            "org.apache.hadoop.hdfs.server.protocol.",
            "org.apache.hadoop.hbase.ipc.",
            "org.apache.zookeeper.server.quorum.",
            "org.apache.solr.client.solrj.");
    private static final Set<String> CONTAINER_MUTATORS = new HashSet<>(Arrays.asList(
            "put", "putAll", "remove", "clear", "add", "addAll", "set",
            "replace", "compute", "computeIfAbsent", "computeIfPresent",
            "merge", "offer", "poll"));

    private StaticFrontier() {}

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            throw new IllegalArgumentException("usage: StaticFrontier input.json output.json");
        }
        JsonObject input = JsonParser.parseString(new String(
                Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8))
                .getAsJsonObject();
        JsonObject result = analyze(input);
        Files.write(Paths.get(args[1]), new GsonBuilder().setPrettyPrinting()
                .create().toJson(result).getBytes(StandardCharsets.UTF_8));
    }

    public static JsonObject analyze(JsonObject config) {
        StaticFrontier analyzer = new StaticFrontier();
        return analyzer.run(config);
    }

    private JsonObject run(JsonObject config) {
        JsonObject target = requireObject(config, "target");
        JsonObject analysis = requireObject(config, "analysis");
        String targetClass = required(target, "class");
        String targetMethod = optional(target, "method", "");
        int targetLine = target.get("line").getAsInt();
        int targetLineStart = optionalInt(target, "line_start", targetLine);
        int targetLineEnd = optionalInt(target, "line_end", targetLine);
        String exception = optional(target, "exception", "");
        sourceFile = optional(target, "source_file", "");
        maxSites = optionalInt(analysis, "max_sites", 3000);
        maxCallDepth = optionalInt(analysis, "max_call_depth", 3);
        ioPatterns = strings(analysis.getAsJsonArray("io_patterns"));
        if (ioPatterns.isEmpty()) ioPatterns = DEFAULT_IO;
        List<String> processDirs = strings(analysis.getAsJsonArray("process_dirs"));
        List<String> classpath = strings(analysis.getAsJsonArray("classpath"));
        if (processDirs.isEmpty()) throw new IllegalArgumentException("analysis.process_dirs is required");
        if (targetLine <= 0 || targetLineStart <= 0 || targetLineEnd < targetLineStart
                || maxSites <= 0 || maxCallDepth < 0) {
            throw new IllegalArgumentException("invalid line or analysis limits");
        }

        soot.G.reset();
        Options.v().set_prepend_classpath(true);
        Options.v().set_allow_phantom_refs(true);
        Options.v().set_whole_program(false);
        Options.v().set_output_format(Options.output_format_none);
        Options.v().set_keep_line_number(true);
        Options.v().set_keep_offset(true);
        Options.v().set_process_dir(processDirs);
        Options.v().set_soot_classpath(String.join(java.io.File.pathSeparator, classpath));
        Scene.v().loadNecessaryClasses();
        if (!Scene.v().containsClass(targetClass)) {
            Scene.v().loadClassAndSupport(targetClass).setApplicationClass();
        }
        index();
        Site anchor = resolveTarget(targetClass, targetMethod,
                targetLineStart, targetLineEnd, exception);
        mark(anchor, "target", "declared_target", 0, 0);
        while (!queue.isEmpty()) {
            Work work = queue.removeFirst();
            if (!expanded.add(work.site.id + "/" + work.callDepth)) continue;
            expand(work);
        }
        addIoDoors();
        List<Site> ordered = new ArrayList<>(selected.values());
        ordered.sort(Comparator.comparingInt((Site s) -> s.distance)
                .thenComparing(s -> s.id));
        JsonObject result = new JsonObject();
        result.addProperty("schema_version", 1);
        result.addProperty("case_id", optional(config, "case_id", ""));
        result.addProperty("analysis_kind", "conservative_static_frontier");
        JsonObject resolved = new JsonObject();
        resolved.addProperty("class", targetClass);
        resolved.addProperty("method", anchor.method.getSignature());
        resolved.addProperty("line", anchor.line);
        resolved.addProperty("site_id", anchor.id);
        if (!sourceFile.isEmpty()) resolved.addProperty("source_file", sourceFile);
        result.add("target", resolved);
        JsonArray rows = new JsonArray();
        for (Site site : ordered) rows.add(site.toJson());
        result.add("frontier", rows);
        for (Site site : ordered) {
            if ("jimple_index".equals(site.identityKind)) {
                gaps.add("jimple_only_site_ids_require_runtime_bytecode_mapping");
                break;
            }
        }
        JsonArray missing = new JsonArray();
        for (String gap : new LinkedHashSet<>(gaps)) missing.add(gap);
        result.add("gaps", missing);
        return result;
    }

    private void index() {
        List<SootClass> classes = new ArrayList<>();
        for (SootClass owner : Scene.v().getApplicationClasses()) classes.add(owner);
        classes.sort(Comparator.comparing(SootClass::getName));
        for (SootClass owner : classes) {
            for (SootMethod method : owner.getMethods()) {
                if (!method.isConcrete()) continue;
                try {
                    methods.put(method.getSignature(), new MethodInfo(method));
                } catch (RuntimeException error) {
                    gaps.add("body_unavailable:" + method.getSignature());
                }
            }
        }
        for (MethodInfo info : methods.values()) {
            for (Unit unit : info.units) {
                Stmt stmt = (Stmt) unit;
                Site site = info.site(unit);
                if (stmt instanceof AssignStmt && ((AssignStmt) stmt).getLeftOp() instanceof FieldRef) {
                    String key = ((FieldRef) ((AssignStmt) stmt).getLeftOp())
                            .getFieldRef().getSignature();
                    fieldWriters.computeIfAbsent(key, k -> new ArrayList<>()).add(site);
                }
                if (stmt.containsInvokeExpr()) {
                    String callee = stmt.getInvokeExpr().getMethodRef().getSignature();
                    callers.computeIfAbsent(callee, k -> new ArrayList<>()).add(site);
                    if (stmt.getInvokeExpr() instanceof InstanceInvokeExpr
                            && CONTAINER_MUTATORS.contains(stmt.getInvokeExpr()
                            .getMethodRef().name())) {
                        soot.Value base = ((InstanceInvokeExpr) stmt.getInvokeExpr()).getBase();
                        for (String field : info.originFields(base, unit, 3)) {
                            fieldWriters.computeIfAbsent(field, k -> new ArrayList<>()).add(site);
                        }
                    }
                }
            }
        }
    }

    private Site resolveTarget(String className, String declaredMethod,
                               int lineStart, int lineEnd, String exception) {
        List<Site> found = new ArrayList<>();
        for (MethodInfo info : methods.values()) {
            if (!info.method.getDeclaringClass().getName().equals(className)
                    && !info.method.getDeclaringClass().getName().startsWith(className + "$")) continue;
            if (!declaredMethod.isEmpty() && !declaredMethod.equals(info.method.getName())
                    && !declaredMethod.equals(info.method.getSignature())) continue;
            for (Unit unit : info.units) {
                if (!(unit instanceof ThrowStmt)
                        || unit.getJavaSourceStartLineNumber() < lineStart
                        || unit.getJavaSourceStartLineNumber() > lineEnd) continue;
                String thrown = ((ThrowStmt) unit).getOp().getType().toString();
                if (!exception.isEmpty() && !thrown.equals(exception)
                        && !thrown.endsWith("." + exception)
                        && !thrown.endsWith("$" + exception)
                        && !thrown.replace('$', '.').equals(exception)) continue;
                found.add(info.site(unit));
            }
        }
        if (found.size() != 1) {
            throw new IllegalArgumentException("target must resolve to exactly one throw; found="
                    + found.size() + " class=" + className + " method=" + declaredMethod
                    + " line_range=" + lineStart + ".." + lineEnd
                    + " exception=" + exception);
        }
        return found.get(0);
    }

    private void expand(Work work) {
        Site site = work.site;
        MethodInfo info = methods.get(site.method.getSignature());
        if (info == null) return;
        activeMethods.add(site.method.getSignature());
        Unit unit = site.unit;
        int distance = site.distance + 1;
        for (ValueBox use : unit.getUseBoxes()) {
            if (use.getValue() instanceof Local) {
                for (Unit def : info.defs.getDefsOfAt((Local) use.getValue(), unit)) {
                    mark(info.site(def), "data_def", "local_reaching_definition", distance, work.callDepth);
                }
            } else if (use.getValue() instanceof FieldRef) {
                String field = ((FieldRef) use.getValue()).getFieldRef().getSignature();
                List<Site> writers = fieldWriters.get(field);
                if (writers == null || writers.isEmpty()) gaps.add("field_writer_not_found:" + field);
                else for (Site writer : writers) {
                    mark(writer, "field_write", "field_name_may_writer", distance, work.callDepth);
                }
            }
        }
        for (Unit branch : info.guardsOf(unit)) {
            mark(info.site(branch), "branch", "control_postdom_may", distance, work.callDepth);
        }
        Stmt stmt = (Stmt) unit;
        if (stmt.containsInvokeExpr()) {
            String callee = stmt.getInvokeExpr().getMethodRef().getSignature();
            MethodInfo target = methods.get(callee);
            if (stmt.getInvokeExpr() instanceof InstanceInvokeExpr) {
                gaps.add("virtual_dispatch_may_be_incomplete:" + callee);
            }
            if (target == null) gaps.add("callee_body_unavailable:" + callee);
            else if (work.callDepth < maxCallDepth) {
                for (Unit ret : target.units) {
                    if (ret instanceof ReturnStmt) {
                        mark(target.site(ret), "callee_return", "call_return_may",
                                distance, work.callDepth + 1);
                    }
                }
            } else gaps.add("call_depth_cut:" + callee);
        }
        // Callers may decide whether this target occurrence exists. The call
        // relation is exact only for statically dispatched calls.
        if (work.callDepth < maxCallDepth) {
            for (Site caller : callers.getOrDefault(site.method.getSignature(), Collections.emptyList())) {
                mark(caller, "caller", "activation_call_may", distance,
                        work.callDepth + 1);
            }
        }
        // A caught fault can choose an alternate path. A BriefUnitGraph
        // excludes exceptional edges, so explicitly state those trap doors.
        for (Trap trap : info.body.getTraps()) {
            if (info.indexOf(trap.getHandlerUnit()) > info.indexOf(unit)) continue;
            mark(info.site(trap.getHandlerUnit()), "exception_handler",
                    "handler_reachability_may", distance, work.callDepth);
            int begin = info.indexOf(trap.getBeginUnit());
            int end = info.indexOf(trap.getEndUnit());
            for (int i = begin; i >= 0 && i < end; i++) {
                Unit guarded = info.units.get(i);
                if (((Stmt) guarded).containsInvokeExpr()) {
                    mark(info.site(guarded), "exception_door",
                            "caught_call_may", distance, work.callDepth);
                }
            }
        }
    }

    private void addIoDoors() {
        for (String signature : activeMethods) {
            MethodInfo info = methods.get(signature);
            for (Unit unit : info.units) {
                Stmt stmt = (Stmt) unit;
                if (!stmt.containsInvokeExpr()) continue;
                String callee = stmt.getInvokeExpr().getMethodRef().getSignature();
                boolean matches = false;
                for (String pattern : ioPatterns) if (callee.contains(pattern)) { matches = true; break; }
                if (matches) mark(info.site(unit), "io_door", "io_api_match_in_selected_method",
                        1, 0);
            }
        }
    }

    private void mark(Site site, String kind, String evidence, int distance, int callDepth) {
        if (selected.size() >= maxSites && !selected.containsKey(site.id)) {
            gaps.add("site_budget_cut:" + maxSites);
            return;
        }
        Site existing = selected.get(site.id);
        if (existing == null) {
            site.kind = kind;
            site.distance = distance;
            selected.put(site.id, site);
            queue.addLast(new Work(site, callDepth));
        } else if (distance < existing.distance) {
            existing.distance = distance;
        }
        selected.get(site.id).evidence.add(evidence);
    }

    private static final class Work {
        final Site site;
        final int callDepth;
        Work(Site site, int callDepth) { this.site = site; this.callDepth = callDepth; }
    }

    private static final class Site {
        final SootMethod method;
        final Unit unit;
        final String id;
        final int line;
        final String identityKind;
        String kind;
        int distance;
        final Set<String> evidence = new LinkedHashSet<>();
        Site(SootMethod method, Unit unit, int index) {
            this.method = method;
            this.unit = unit;
            this.line = unit.getJavaSourceStartLineNumber();
            Tag tag = unit.getTag("BytecodeOffsetTag");
            if (tag instanceof BytecodeOffsetTag) {
                this.identityKind = "bytecode_offset";
                this.id = method.getSignature() + "@bci" + ((BytecodeOffsetTag) tag).getBytecodeOffset();
            } else {
                this.identityKind = "jimple_index";
                this.id = method.getSignature() + "@jimple" + index;
            }
        }
        JsonObject toJson() {
            JsonObject row = new JsonObject();
            row.addProperty("site_id", id);
            row.addProperty("identity_kind", identityKind);
            row.addProperty("class", method.getDeclaringClass().getName());
            row.addProperty("method", method.getSignature());
            row.addProperty("line", line);
            row.addProperty("kind", kind);
            row.addProperty("distance", distance);
            JsonArray reasons = new JsonArray();
            for (String reason : evidence) reasons.add(reason);
            row.add("evidence", reasons);
            return row;
        }
    }

    private static final class MethodInfo {
        final SootMethod method;
        final Body body;
        final List<Unit> units;
        final SimpleLocalDefs defs;
        final BriefUnitGraph graph;
        final MHGPostDominatorsFinder<Unit> postdom;
        final Map<Unit, Site> sites = new HashMap<>();
        MethodInfo(SootMethod method) {
            this.method = method;
            this.body = method.retrieveActiveBody();
            this.units = new ArrayList<>();
            for (Unit unit : body.getUnits()) units.add(unit);
            this.graph = new BriefUnitGraph(body);
            this.defs = new SimpleLocalDefs(graph);
            this.postdom = new MHGPostDominatorsFinder<>(graph);
        }
        int indexOf(Unit unit) { return units.indexOf(unit); }
        Site site(Unit unit) {
            return sites.computeIfAbsent(unit, key -> new Site(method, key,
                    indexOf(key)));
        }
        Set<String> originFields(soot.Value value, Unit at, int depth) {
            Set<String> found = new LinkedHashSet<>();
            if (value instanceof FieldRef) {
                found.add(((FieldRef) value).getFieldRef().getSignature());
            } else if (value instanceof Local && depth > 0) {
                for (Unit def : defs.getDefsOfAt((Local) value, at)) {
                    if (def instanceof AssignStmt) {
                        found.addAll(originFields(((AssignStmt) def).getRightOp(), def, depth - 1));
                    }
                }
            }
            return found;
        }
        List<Unit> guardsOf(Unit site) {
            List<Unit> result = new ArrayList<>();
            for (Unit branch : units) {
                if (!(branch instanceof IfStmt) && !(branch instanceof LookupSwitchStmt)
                        && !(branch instanceof TableSwitchStmt)) continue;
                if (postdom.getDominators(branch).contains(site)) continue;
                for (Unit successor : graph.getSuccsOf(branch)) {
                    if (postdom.getDominators(successor).contains(site)) {
                        result.add(branch);
                        break;
                    }
                }
            }
            return result;
        }
    }

    private static JsonObject requireObject(JsonObject parent, String field) {
        if (!parent.has(field) || !parent.get(field).isJsonObject())
            throw new IllegalArgumentException(field + " object is required");
        return parent.getAsJsonObject(field);
    }
    private static String required(JsonObject obj, String field) {
        String value = optional(obj, field, "");
        if (value.isEmpty()) throw new IllegalArgumentException(field + " is required");
        return value;
    }
    private static String optional(JsonObject obj, String field, String fallback) {
        return obj.has(field) && !obj.get(field).isJsonNull()
                ? obj.get(field).getAsString() : fallback;
    }
    private static int optionalInt(JsonObject obj, String field, int fallback) {
        return obj.has(field) ? obj.get(field).getAsInt() : fallback;
    }
    private static List<String> strings(JsonArray values) {
        List<String> result = new ArrayList<>();
        if (values != null) values.forEach(value -> result.add(value.getAsString()));
        return result;
    }
}
