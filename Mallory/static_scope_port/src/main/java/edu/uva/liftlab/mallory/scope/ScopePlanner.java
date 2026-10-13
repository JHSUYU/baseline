package edu.uva.liftlab.mallory.scope;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import soot.ArrayType;
import soot.Body;
import soot.BodyTransformer;
import soot.Local;
import soot.PackManager;
import soot.RefType;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.SootMethodRef;
import soot.Transform;
import soot.Trap;
import soot.Type;
import soot.Unit;
import soot.Value;
import soot.ValueBox;
import soot.jimple.AssignStmt;
import soot.jimple.FieldRef;
import soot.jimple.IdentityStmt;
import soot.jimple.IfStmt;
import soot.jimple.InstanceFieldRef;
import soot.jimple.InstanceInvokeExpr;
import soot.jimple.InvokeExpr;
import soot.jimple.LookupSwitchStmt;
import soot.jimple.NewExpr;
import soot.jimple.ParameterRef;
import soot.jimple.StaticInvokeExpr;
import soot.jimple.Stmt;
import soot.jimple.TableSwitchStmt;
import soot.jimple.ThrowStmt;
import soot.options.Options;
import soot.tagkit.BytecodeOffsetTag;
import soot.tagkit.Tag;
import soot.toolkits.graph.BriefUnitGraph;
import soot.toolkits.graph.MHGDominatorsFinder;
import soot.toolkits.graph.MHGPostDominatorsFinder;
import soot.toolkits.scalar.SimpleLocalDefs;

import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.MessageDigest;
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
import java.util.regex.Pattern;
import java.util.stream.Stream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * GraphChecker-derived static scope for a declared coordination check.  This
 * emits MAY candidates; it never asserts that a field read saw a particular
 * write or that a receiver got a particular send.  Those are runtime facts.
 *
 * The worklist follows GraphChecker's seed backward rules: local definitions,
 * post-dominance guards, field-wide writer jumps, call return/formal/caller
 * jumps, and communication ports.  No per-check I/O declarations are needed.
 */
public final class ScopePlanner {
    private static final Gson JSON = new GsonBuilder().disableHtmlEscaping().create();
    private static final Set<String> MUTATORS = new HashSet<>(Arrays.asList(
            "put", "putAll", "remove", "clear", "add", "addAll", "set",
            "replace", "compute", "computeIfAbsent", "computeIfPresent",
            "merge", "offer", "poll"));
    private static final Set<String> IO_VERBS = new HashSet<>(Arrays.asList(
            "read", "readFully", "write", "writeBytes", "flush", "sync",
            "connect", "accept", "send", "receive", "close", "transferTo",
            "transferFrom", "force", "getInputStream", "getOutputStream",
            "createNewFile", "delete", "renameTo", "mkdir", "mkdirs",
            "exists", "list", "listFiles", "length", "getData", "setData"));
    // Constructor calls need a verifier fixture for their uninitialized
    // receiver. Add a signature here only after the generic weaver has
    // successfully woven and loaded it in an unchanged JUnit.
    private static final Set<String> VERIFIED_RESOURCE_CONSTRUCTORS =
            new HashSet<>(Collections.singletonList(
                    "<java.io.FileReader: void <init>(java.io.File)>"));

    private final Map<String, Method> methods = new LinkedHashMap<>();
    // Soot runs body packs on worker threads; captures must be thread-safe.
    private final Map<String, Body> jtpBodies = new java.util.concurrent.ConcurrentHashMap<>();
    private final Map<String, List<Site>> fieldWriters = new LinkedHashMap<>();
    private final Map<String, List<Site>> callersBySubSignature = new LinkedHashMap<>();
    private final List<Site> handoffCallsites = new ArrayList<>();
    private final Map<String, List<Site>> handoffCache = new HashMap<>();
    private final Map<String, List<Site>> protoSetterCallsites = new LinkedHashMap<>();
    private final Map<String, Port> derivedProtoPorts = new LinkedHashMap<>();
    private final Map<String, List<Site>> callersCache = new HashMap<>();
    private final Map<String, Set<String>> receiverAllocationsCache = new HashMap<>();
    private final Map<String, List<Method>> methodsBySubSignature = new LinkedHashMap<>();
    private final Map<String, Site> selected = new LinkedHashMap<>();
    private final Map<String, Set<String>> evidence = new LinkedHashMap<>();
    private final Deque<Site> queue = new ArrayDeque<>();
    private final Set<String> expanded = new HashSet<>();
    private final Set<String> selectedFields = new LinkedHashSet<>();
    private final Set<String> selectedFieldWriterSites = new HashSet<>();
    private final Set<String> analysisGaps = new LinkedHashSet<>();
    private final Set<String> materializedClasses = new HashSet<>();
    private final List<Port> ports = new ArrayList<>();
    private Set<String> rpcMessages;
    private JsonObject config;
    private JsonObject analysisConfig;
    private final List<Pattern> sourceOwnerClasses = new ArrayList<>();
    private final List<Pattern> ioDoorMappings = new ArrayList<>();
    private Site target;
    private Site fatalThrow;
    private final List<Site> checkSites = new ArrayList<>();

    private ScopePlanner() {}

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            throw new IllegalArgumentException("usage: ScopePlanner case-or-scope.json output-directory");
        }
        JsonObject input = JsonParser.parseString(new String(
                Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8)).getAsJsonObject();
        ScopePlanner planner = new ScopePlanner();
        planner.plan(input, Paths.get(args[1]));
    }

    public static JsonObject analyze(JsonObject input) {
        ScopePlanner planner = new ScopePlanner();
        return planner.run(input);
    }

    public static JsonObject plan(JsonObject input, Path output) throws IOException {
        ScopePlanner planner = new ScopePlanner();
        JsonObject result = planner.run(input);
        Files.createDirectories(output);
        StringBuilder rows = new StringBuilder();
        for (JsonElement row : result.getAsJsonArray("scopeSites")) {
            rows.append(JSON.toJson(row)).append('\n');
        }
        Files.write(output.resolve("static_scope_map.jsonl"),
                rows.toString().getBytes(StandardCharsets.UTF_8));
        Files.write(output.resolve("weave_manifest.json"),
                new GsonBuilder().setPrettyPrinting().create().toJson(
                        result.getAsJsonObject("weaveManifest")).getBytes(StandardCharsets.UTF_8));
        Files.write(output.resolve("analysis.json"),
                new GsonBuilder().setPrettyPrinting().create().toJson(result)
                        .getBytes(StandardCharsets.UTF_8));
        return result;
    }

    private JsonObject run(JsonObject input) {
        long started = System.nanoTime();
        this.config = input;
        JsonObject analysis = object(input, "analysis");
        this.analysisConfig = analysis;
        for (String pattern : strings(analysis.get("source_owner_classes"))) {
            sourceOwnerClasses.add(Pattern.compile(pattern));
        }
        for (String pattern : strings(analysis.get("io_door_mappings"))) {
            ioDoorMappings.add(Pattern.compile(pattern));
        }
        List<String> dirs = strings(analysis.get("process_dirs"));
        if (dirs.isEmpty()) {
            String compiled = string(object(input, "mapping"), "compiled_artifact", "");
            if (!compiled.isEmpty()) dirs.add(compiled);
        }
        if (dirs.isEmpty()) throw new IllegalArgumentException("analysis.process_dirs is required");
        indexMaterializedClasses(dirs);
        List<String> dependencies = strings(analysis.get("classpath"));
        if (dependencies.isEmpty()) {
            throw new IllegalArgumentException("analysis.classpath must be the exact ordered "
                    + "dependency classpath supplied to WeaveMain");
        }
        List<String> classpath = new ArrayList<>(dirs);
        classpath.addAll(dependencies);
        soot.G.reset();
        Options.v().set_prepend_classpath(true);
        Options.v().set_allow_phantom_refs(true);
        Options.v().set_whole_program(false);
        // The runtime Soot weaver selects original units at jtp entry.
        // Analyse a cloned snapshot from that exact phase, never the
        // pre-pack retrieveActiveBody() unit order.
        Options.v().set_output_format(Options.output_format_class);
        Options.v().set_keep_line_number(true);
        Options.v().set_keep_offset(true);
        Options.v().set_process_dir(dirs);
        Options.v().set_soot_classpath(String.join(File.pathSeparator, classpath));
        Scene.v().loadNecessaryClasses();
        PackManager.v().getPack("jtp").add(new Transform("jtp.malloryStaticCapture",
                new BodyTransformer() {
                    @Override protected void internalTransform(Body body, String phase,
                                                               Map<String, String> options) {
                        jtpBodies.put(body.getMethod().getSignature(), (Body) body.clone());
                    }
                }));
        PackManager.v().runPacks();
        index();
        System.err.println("Mallory static scope indexed " + methods.size()
                + " application methods in " + elapsed(started) + " ms");
        target = resolveTarget(object(input, "target"));
        int checkLine = integer(object(input, "target"), "check_line", 0);
        if (target.unit instanceof ThrowStmt) {
            fatalThrow = target;
            for (Unit guard : target.owner.guardsOf(target.unit)) {
                Site check = target.owner.site(guard);
                if (checkLine > 0 && check.line != checkLine) continue;
                checkSites.add(check);
                mark(check, "declared_target_check");
            }
            if (checkLine > 0 && checkSites.isEmpty()) {
                throw new IllegalArgumentException("check_line did not name a controlling branch: "
                        + checkLine);
            }
        } else {
            fatalThrow = resolveControlledThrow(target, object(input, "target"));
        }
        // The healthy seed reaches a check branch, not its fatal throw. The
        // throw is an oracle probe, deliberately not a backward value seed:
        // exception construction is irrelevant to what makes the check fail.
        if (checkSites.isEmpty()) mark(target, "declared_target_fallback");
        while (!queue.isEmpty()) {
            Site site = queue.removeFirst();
            if (expanded.add(site.id)) expand(site);
        }
        System.err.println("Mallory static scope selected " + selected.size()
                + " candidate units and " + selectedFields.size()
                + " fields in " + elapsed(started) + " ms");
        selectFieldAccessesAndDoors();
        discoverPorts(analysis);
        return output();
    }

    private static long elapsed(long started) {
        return (System.nanoTime() - started) / 1_000_000L;
    }

    private void indexMaterializedClasses(List<String> dirs) {
        for (String entry : dirs) {
            Path path = Paths.get(entry);
            try {
                if (Files.isDirectory(path)) {
                    try (Stream<Path> files = Files.walk(path)) {
                        files.filter(file -> file.toString().endsWith(".class"))
                                .forEach(file -> materializedClasses.add(
                                        className(path.relativize(file).toString())));
                    }
                } else if (Files.isRegularFile(path) && entry.endsWith(".jar")) {
                    try (ZipFile archive = new ZipFile(path.toFile())) {
                        java.util.Enumeration<? extends ZipEntry> files = archive.entries();
                        while (files.hasMoreElements()) {
                            String name = files.nextElement().getName();
                            if (name.endsWith(".class")) {
                                materializedClasses.add(className(name));
                            }
                        }
                    }
                }
            } catch (IOException error) {
                throw new IllegalArgumentException("cannot inspect process_dir " + entry, error);
            }
        }
    }

    private static String className(String relativeClassFile) {
        return relativeClassFile.substring(0, relativeClassFile.length() - 6)
                .replace('/', '.').replace('\\', '.');
    }

    private void index() {
        List<SootClass> classes = new ArrayList<>();
        for (SootClass owner : Scene.v().getApplicationClasses()) classes.add(owner);
        classes.sort(Comparator.comparing(SootClass::getName));
        for (SootClass owner : classes) {
            // Protoc's generated message and builder bodies are transport
            // implementation, not application decisions.  Their public
            // return is conservatively dependent on receiver and arguments
            // at the caller.  Leaf getters carried by RPC also get an
            // explicit setter-to-getter port below, as in GraphChecker F3.
            if (generatedProtobufClass(owner)) continue;
            List<SootMethod> sorted = new ArrayList<>(owner.getMethods());
            sorted.sort(Comparator.comparing(SootMethod::getSignature));
            for (SootMethod sootMethod : sorted) {
                if (!sootMethod.isConcrete()) continue;
                try {
                    Body captured = jtpBodies.get(sootMethod.getSignature());
                    if (captured == null) {
                        analysisGaps.add("jtp_body_unavailable:" + sootMethod.getSignature());
                        continue;
                    }
                    Method method = new Method(sootMethod, captured);
                    methods.put(sootMethod.getSignature(), method);
                    methodsBySubSignature.computeIfAbsent(
                            sootMethod.getSubSignature(), x -> new ArrayList<>()).add(method);
                } catch (RuntimeException error) {
                    analysisGaps.add("body_unavailable:" + sootMethod.getSignature());
                }
            }
        }
        for (Method method : methods.values()) {
            for (Site site : method.sites) {
                Stmt stmt = (Stmt) site.unit;
                if (stmt instanceof AssignStmt
                        && ((AssignStmt) stmt).getLeftOp() instanceof FieldRef) {
                    FieldRef field = (FieldRef) ((AssignStmt) stmt).getLeftOp();
                    fieldWriters.computeIfAbsent(field.getFieldRef().getSignature(),
                            x -> new ArrayList<>()).add(site);
                }
                if (!stmt.containsInvokeExpr()) continue;
                InvokeExpr invoke = stmt.getInvokeExpr();
                callersBySubSignature.computeIfAbsent(
                        invoke.getMethodRef().getSubSignature().toString(),
                        x -> new ArrayList<>()).add(site);
                SootMethodRef ref = invoke.getMethodRef();
                if (isAsyncSubmission(ref)) handoffCallsites.add(site);
                if (ref.name().startsWith("set") && ref.name().length() > 3
                        && ref.parameterTypes().size() == 1
                        && ref.declaringClass().getName().endsWith("$Builder")) {
                    String message = ref.declaringClass().getName();
                    message = message.substring(0, message.length() - "$Builder".length());
                    protoSetterCallsites.computeIfAbsent(message + "."
                            + ref.name().substring(3), x -> new ArrayList<>()).add(site);
                }
                if (invoke instanceof InstanceInvokeExpr
                        && MUTATORS.contains(invoke.getMethodRef().name())) {
                    Value base = ((InstanceInvokeExpr) invoke).getBase();
                    for (String field : method.originFields(base, site.unit,
                            new HashSet<Unit>())) {
                        fieldWriters.computeIfAbsent(field, x -> new ArrayList<>()).add(site);
                    }
                }
            }
        }
    }

    private Site resolveTarget(JsonObject spec) {
        String clazz = string(spec, "class", string(spec, "clazz", ""));
        String methodName = string(spec, "method", "");
        String siteId = string(spec, "site_id", "");
        if (methodName.isEmpty() && siteId.startsWith("<")) {
            int end = siteId.indexOf('>');
            if (end > 0) methodName = siteId.substring(0, end + 1);
        }
        if (clazz.isEmpty() && methodName.startsWith("<")) {
            int colon = methodName.indexOf(':');
            if (colon > 1) clazz = methodName.substring(1, colon);
        }
        if (clazz.isEmpty()) {
            String function = string(spec, "function", "");
            int left = function.indexOf('(');
            int last = function.lastIndexOf('.', left < 0 ? function.length() : left);
            if (last > 0) clazz = function.substring(0, last);
            if (last > 0 && methodName.isEmpty()) methodName = function.substring(last + 1,
                    left < 0 ? function.length() : left);
        }
        int line = integer(spec, "line", integer(spec, "source_line", 0));
        int lineStart = integer(spec, "line_start", line);
        int lineEnd = integer(spec, "line_end", line);
        String exception = string(spec, "exception", string(spec, "exception_class", ""));
        String kind = string(spec, "kind", "THROW");
        if (clazz.isEmpty() || line <= 0) {
            throw new IllegalArgumentException("target class and source line are required");
        }
        List<Site> matches = new ArrayList<>();
        for (Method method : methods.values()) {
            if (!method.soot.getDeclaringClass().getName().equals(clazz)
                    && !method.soot.getDeclaringClass().getName().startsWith(clazz + "$")) continue;
            if (!methodName.isEmpty() && !methodName.equals(method.soot.getName())
                    && !methodName.equals(method.soot.getSignature())) continue;
            for (Site site : method.sites) {
                if (site.line < lineStart || site.line > lineEnd) continue;
                if ("THROW".equals(kind)) {
                    if (!(site.unit instanceof ThrowStmt)) continue;
                    String type = ((ThrowStmt) site.unit).getOp().getType().toString();
                    if (!exception.isEmpty() && !type.equals(exception)
                            && !type.endsWith("." + exception)
                            && !type.endsWith("$" + exception)) continue;
                } else if ("BRANCH".equals(kind)) {
                    if (!site.isBranch()) continue;
                } else throw new IllegalArgumentException("unknown target kind " + kind);
                matches.add(site);
            }
        }
        if (matches.size() != 1) {
            throw new IllegalArgumentException("target must resolve to one site; found="
                    + matches.size() + " class=" + clazz + " method=" + methodName
                    + " line=" + lineStart + ".." + lineEnd + " kind=" + kind);
        }
        return matches.get(0);
    }

    private Site resolveControlledThrow(Site check, JsonObject spec) {
        String exception = string(spec, "exception", string(spec, "exception_class", ""));
        int throwLine = integer(spec, "throw_line", 0);
        List<Site> matches = new ArrayList<>();
        for (Site candidate : check.owner.sites) {
            if (!(candidate.unit instanceof ThrowStmt)
                    || throwLine > 0 && candidate.line != throwLine
                    || !check.owner.guardsOf(candidate.unit).contains(check.unit)) continue;
            String type = ((ThrowStmt) candidate.unit).getOp().getType().toString();
            if (!exception.isEmpty() && !type.equals(exception)
                    && !type.endsWith("." + exception)
                    && !type.endsWith("$" + exception)) continue;
            matches.add(candidate);
        }
        if (matches.size() == 1) return matches.get(0);
        if (matches.size() > 1 || throwLine > 0) {
            throw new IllegalArgumentException("check branch must control one fatal throw; found="
                    + matches.size() + " check=" + check.id + " exception=" + exception
                    + " throw_line=" + throwLine);
        }
        analysisGaps.add("controlled_throw_unresolved:" + check.id + ":" + exception);
        return null;
    }

    private void expand(Site site) {
        Method method = site.owner;
        method.flow();
        Unit unit = site.unit;
        Set<String> why = evidence.getOrDefault(site.id, Collections.<String>emptySet());
        boolean dataDemand = site == target || checkSites.contains(site)
                || why.contains("local_reaching_definition")
                || why.contains("field_wide_writer_jump")
                || why.contains("control_postdom_may")
                || why.contains("call_return_jump");
        // An activation caller says whether an effect runs. Its unrelated
        // arguments are not all predecessors of that effect. Widen through
        // a formal only when the value demand reaches it (GraphChecker's
        // return-only versus effectful-formal distinction).
        if (dataDemand) {
            List<Value> uses = new ArrayList<>();
            boolean writerOnly = why.contains("field_wide_writer_jump")
                    && !why.contains("local_reaching_definition")
                    && !why.contains("control_postdom_may")
                    && !why.contains("call_return_jump");
            if (writerOnly && unit instanceof AssignStmt
                    && ((AssignStmt) unit).getLeftOp() instanceof FieldRef) {
                addValueUses(uses, ((AssignStmt) unit).getRightOp());
            } else if (writerOnly && ((Stmt) unit).containsInvokeExpr()) {
                for (Value argument : ((Stmt) unit).getInvokeExpr().getArgs()) {
                    addValueUses(uses, argument);
                }
            } else {
                for (ValueBox use : unit.getUseBoxes()) uses.add(use.getValue());
            }
            for (Value value : uses) {
                demandValue(method, unit, value);
            }
        }
        for (Unit guard : method.guardsOf(unit)) {
            mark(method.site(guard), "control_postdom_may");
        }
        Stmt stmt = (Stmt) unit;
        // A demanded identity is a formal value, not merely an activation.
        // Transfer that precise demand to each type-compatible callsite's
        // corresponding actual.  Demanding every argument of the call would
        // turn a single relevant parameter into unrelated application state.
        if (dataDemand && stmt instanceof IdentityStmt) {
            Value formal = ((IdentityStmt) stmt).getRightOp();
            if (formal instanceof ParameterRef || formal instanceof soot.jimple.ThisRef) {
                for (Site caller : callersOf(method.soot)) {
                    InvokeExpr invoke = ((Stmt) caller.unit).getInvokeExpr();
                    Value actual = null;
                    if (formal instanceof ParameterRef) {
                        int ordinal = ((ParameterRef) formal).getIndex();
                        if (ordinal < invoke.getArgCount()) actual = invoke.getArg(ordinal);
                    } else if (invoke instanceof InstanceInvokeExpr) {
                        actual = ((InstanceInvokeExpr) invoke).getBase();
                    }
                    if (actual == null) continue;
                    mark(caller, "formal_actual_jump");
                    for (ValueBox nested : actual.getUseBoxes()) {
                        demandValue(caller.owner, caller.unit, nested.getValue());
                    }
                    demandValue(caller.owner, caller.unit, actual);
                }
            }
        }
        // A formal reached only through one returned value is return-only:
        // its invocation already demanded that call's actual arguments.
        // The target and effectful field stores below widen to all callers.
        if (dataDemand && stmt instanceof AssignStmt && stmt.containsInvokeExpr()
                && (evidence.getOrDefault(site.id, Collections.<String>emptySet())
                    .contains("local_reaching_definition")
                    || evidence.getOrDefault(site.id, Collections.<String>emptySet())
                    .contains("call_return_jump"))) {
            deriveProtobufLeafPort(site, stmt.getInvokeExpr());
            for (Method callee : resolveCallees(site)) {
                for (Site ret : callee.sites) {
                    if (ret.unit instanceof soot.jimple.ReturnStmt) {
                        mark(ret, "call_return_jump");
                    }
                }
            }
        }
        if (site == target || checkSites.contains(site) || isFieldWriter(site)) {
            for (Site caller : callersOf(method.soot)) {
                mark(caller, "activation_jump");
            }
        }
        // A callback can run without a direct application call to run/call.
        // The scheduling call is an activation predecessor, while the actual
        // request identity still has to come from runtime handoff tracing.
        if (method.isCallback()) {
            for (Site submission : handoffsOf(method.soot)) {
                mark(submission, "async_handoff_jump");
            }
        }
        // Exceptional control predecessor: a selected handler may have been
        // reached by any call in a covering trap.  This is a MAY edge.
        for (Trap trap : method.body.getTraps()) {
            // Reaching a normal unit after a catch does not make every call
            // in the protected try a predecessor of that unit. The selected
            // unit must be inside the handler-controlled region: its handler
            // entry dominates it in the intraprocedural graph.
            if (!method.handlerDominates(trap.getHandlerUnit(), unit)) continue;
            int begin = method.indexOf(trap.getBeginUnit());
            int end = method.indexOf(trap.getEndUnit());
            for (int i = begin; i >= 0 && i < end; i++) {
                Site raised = method.sites.get(i);
                if (((Stmt) raised.unit).containsInvokeExpr()) {
                    mark(raised, "caught_call_may");
                }
            }
        }
    }

    private static void addValueUses(List<Value> into, Value value) {
        into.add(value);
        for (ValueBox nested : value.getUseBoxes()) into.add(nested.getValue());
    }

    private void demandValue(Method method, Unit at, Value value) {
        if (value instanceof Local) {
            method.flow();
            for (Unit def : method.defs.getDefsOfAt((Local) value, at)) {
                mark(method.site(def), "local_reaching_definition");
            }
        } else if (value instanceof FieldRef) {
            demandField((FieldRef) value, method, at);
        }
    }

    private void demandField(FieldRef read, Method reader, Unit at) {
        String signature = read.getFieldRef().getSignature();
        selectedFields.add(signature);
        List<Site> writers = fieldWriters.get(signature);
        if (writers == null || writers.isEmpty()) {
            analysisGaps.add("field_writer_unavailable:" + signature);
            return;
        }
        Set<String> readerObjects = read instanceof InstanceFieldRef
                ? reader.allocationOrigins(((InstanceFieldRef) read).getBase(), at,
                        new HashSet<Unit>()) : null;
        for (Site writer : writers) {
            if (readerObjects != null && writer.unit instanceof AssignStmt) {
                Value left = ((AssignStmt) writer.unit).getLeftOp();
                if (left instanceof InstanceFieldRef) {
                    Set<String> writerObjects = writer.owner.allocationOrigins(
                            ((InstanceFieldRef) left).getBase(), writer.unit,
                            new HashSet<Unit>());
                    if (writerObjects != null
                            && Collections.disjoint(readerObjects, writerObjects)) continue;
                }
            }
            selectedFieldWriterSites.add(writer.id);
            mark(writer, "field_wide_writer_jump");
        }
    }

    private boolean isFieldWriter(Site site) {
        return selectedFieldWriterSites.contains(site.id);
    }

    private List<Method> resolveCallees(Site caller) {
        InvokeExpr invoke = ((Stmt) caller.unit).getInvokeExpr();
        return resolveCallees(invoke.getMethodRef(),
                invoke instanceof InstanceInvokeExpr, caller);
    }

    private List<Method> resolveCallees(SootMethodRef reference, boolean virtual,
                                        Site caller) {
        List<Method> out = new ArrayList<>();
        Method exact = methods.get(reference.getSignature());
        if (exact != null) out.add(exact);
        if (!virtual) return out;
        String owner = reference.declaringClass().getName();
        // GraphChecker treats library containers and Object methods by
        // contracts; dispatching a Map.get/Object.toString call to every
        // application implementation turns one demand into the entire app.
        if (libraryDispatchOwner(owner) && !applicationCallbackOwner(owner)) return out;
        for (Method candidate : methodsBySubSignature.getOrDefault(
                reference.getSubSignature().toString(), Collections.<Method>emptyList())) {
            if (candidate != exact && subtypeOf(candidate.soot.getDeclaringClass(), owner)
                    && receiverMayDispatchTo(caller, candidate.soot.getDeclaringClass())) {
                out.add(candidate);
            }
        }
        return out;
    }

    private List<Site> callersOf(SootMethod demanded) {
        List<Site> cached = callersCache.get(demanded.getSignature());
        if (cached != null) return cached;
        List<Site> out = new ArrayList<>();
        for (Site caller : callersBySubSignature.getOrDefault(
                demanded.getSubSignature(), Collections.<Site>emptyList())) {
            InvokeExpr invoke = ((Stmt) caller.unit).getInvokeExpr();
            SootMethodRef ref = invoke.getMethodRef();
            if (ref.getSignature().equals(demanded.getSignature())
                    || invoke instanceof InstanceInvokeExpr
                    && (!libraryDispatchOwner(ref.declaringClass().getName())
                        || applicationCallbackOwner(ref.declaringClass().getName()))
                    && subtypeOf(demanded.getDeclaringClass(), ref.declaringClass().getName())
                    && receiverMayDispatchTo(caller, demanded.getDeclaringClass())) {
                out.add(caller);
            }
        }
        callersCache.put(demanded.getSignature(), out);
        return out;
    }

    private boolean receiverMayDispatchTo(Site caller, SootClass implementation) {
        if (caller == null) return true;
        InvokeExpr invoke = ((Stmt) caller.unit).getInvokeExpr();
        if (!(invoke instanceof InstanceInvokeExpr)) return true;
        Set<String> allocations;
        if (receiverAllocationsCache.containsKey(caller.id)) {
            allocations = receiverAllocationsCache.get(caller.id);
        } else {
            allocations = caller.owner.allocationTypes(
                    ((InstanceInvokeExpr) invoke).getBase(), caller.unit,
                    new HashSet<Unit>());
            receiverAllocationsCache.put(caller.id, allocations);
        }
        if (allocations == null) return true;
        for (String type : allocations) {
            if (!Scene.v().containsClass(type)) return true;
            if (subtypeOf(Scene.v().getSootClass(type),
                    implementation.getName())) return true;
        }
        return false;
    }

    private List<Site> handoffsOf(SootMethod callback) {
        List<Site> cached = handoffCache.get(callback.getSignature());
        if (cached != null) return cached;
        List<Site> found = new ArrayList<>();
        for (Site site : handoffCallsites) {
            InvokeExpr invoke = ((Stmt) site.unit).getInvokeExpr();
            for (Value argument : invoke.getArgs()) {
                String declared = argument.getType().toString();
                if (!subtypeOf(callback.getDeclaringClass(), declared)) continue;
                Set<String> allocations = site.owner.allocationTypes(argument,
                        site.unit, new HashSet<Unit>());
                if (allocations != null) {
                    boolean possible = false;
                    for (String type : allocations) {
                        if (!Scene.v().containsClass(type)
                                || subtypeOf(Scene.v().getSootClass(type),
                                        callback.getDeclaringClass().getName())) {
                            possible = true;
                            break;
                        }
                    }
                    if (!possible) continue;
                }
                found.add(site);
                break;
            }
        }
        handoffCache.put(callback.getSignature(), found);
        return found;
    }

    private void deriveProtobufLeafPort(Site consumer, InvokeExpr invoke) {
        SootMethodRef ref = invoke.getMethodRef();
        String name = ref.name();
        if (!name.startsWith("get") || name.length() <= 3
                || !ref.parameterTypes().isEmpty()
                || !wireLeafType(ref.returnType().toString())) return;
        String message = ref.declaringClass().getName();
        if (!rpcMessages().contains(message)) return;
        String field = name.substring(3);
        List<Site> setters = protoSetterCallsites.getOrDefault(message + "." + field,
                Collections.<Site>emptyList());
        if (setters.isEmpty()) return;
        String id = "auto:" + message + "." + field;
        Port port = derivedProtoPorts.get(id);
        if (port == null) {
            port = new Port(id, "PROTOBUF_FIELD", "");
            derivedProtoPorts.put(id, port);
            ports.add(port);
        }
        if (!port.consumers.contains(consumer)) port.consumers.add(consumer);
        for (Site setter : setters) {
            if (!port.producers.contains(setter)) port.producers.add(setter);
            mark(setter, "derived_protobuf_wire_source");
            InvokeExpr write = ((Stmt) setter.unit).getInvokeExpr();
            if (write.getArgCount() > 0) {
                Value actual = write.getArg(0);
                demandValue(setter.owner, setter.unit, actual);
                for (ValueBox nested : actual.getUseBoxes()) {
                    demandValue(setter.owner, setter.unit, nested.getValue());
                }
            }
        }
    }

    private Set<String> rpcMessages() {
        if (rpcMessages != null) return rpcMessages;
        Map<String, SootClass> classes = new HashMap<>();
        for (SootClass clazz : Scene.v().getClasses()) classes.put(clazz.getName(), clazz);
        Deque<String> pending = new ArrayDeque<>();
        for (SootClass clazz : classes.values()) {
            if (clazz.resolvingLevel() < SootClass.SIGNATURES) continue;
            for (SootMethod service : clazz.getMethods()) {
                if (service.getParameterCount() > 1 && service.getParameterType(0)
                        .toString().endsWith(".protobuf.RpcController")) {
                    pending.add(service.getParameterType(1).toString());
                    pending.add(service.getReturnType().toString());
                }
            }
        }
        Set<String> found = new LinkedHashSet<>();
        while (!pending.isEmpty()) {
            String name = pending.removeFirst();
            SootClass message = classes.get(name);
            if (message == null || message.resolvingLevel() < SootClass.SIGNATURES
                    || !generatedProtobufClass(message)
                    || !found.add(name)) continue;
            for (SootMethod method : message.getMethods()) {
                if (!method.isStatic()) pending.add(method.getReturnType().toString());
            }
        }
        rpcMessages = found;
        return found;
    }

    private static boolean generatedProtobufClass(SootClass clazz) {
        Deque<SootClass> pending = new ArrayDeque<>();
        Set<String> seen = new HashSet<>();
        pending.add(clazz);
        while (!pending.isEmpty()) {
            SootClass next = pending.removeFirst();
            String name = next.getName();
            if (!seen.add(name)) continue;
            if (name.contains(".protobuf.GeneratedMessage")) return true;
            if (next.hasSuperclass()) pending.add(next.getSuperclass());
            pending.addAll(next.getInterfaces());
        }
        return false;
    }

    private static boolean wireLeafType(String name) {
        return "boolean".equals(name) || "byte".equals(name)
                || "char".equals(name) || "short".equals(name)
                || "int".equals(name) || "long".equals(name)
                || "float".equals(name) || "double".equals(name)
                || "java.lang.String".equals(name);
    }

    private static boolean subtypeOf(SootClass candidate, String ancestor) {
        Deque<SootClass> pending = new ArrayDeque<>();
        Set<String> seen = new HashSet<>();
        pending.add(candidate);
        while (!pending.isEmpty()) {
            SootClass next = pending.removeFirst();
            if (!seen.add(next.getName())) continue;
            if (next.getName().equals(ancestor)) return true;
            if (next.hasSuperclass()) pending.add(next.getSuperclass());
            pending.addAll(next.getInterfaces());
        }
        return false;
    }

    private static boolean libraryDispatchOwner(String owner) {
        return owner.startsWith("java.") || owner.startsWith("javax.")
                || owner.startsWith("com.google.") || owner.startsWith("org.slf4j.")
                || owner.startsWith("org.apache.logging.");
    }

    private static boolean applicationCallbackOwner(String owner) {
        return "java.lang.Runnable".equals(owner)
                || "java.util.concurrent.Callable".equals(owner)
                || "java.util.concurrent.Executor".equals(owner)
                || "java.util.concurrent.ExecutorService".equals(owner)
                || owner.startsWith("java.util.function.");
    }

    private static boolean isCallbackMethod(SootMethod method) {
        String name = method.getName();
        if ("run".equals(name) && subtypeOf(method.getDeclaringClass(),
                "java.lang.Runnable")) return true;
        if ("call".equals(name) && subtypeOf(method.getDeclaringClass(),
                "java.util.concurrent.Callable")) return true;
        Deque<SootClass> pending = new ArrayDeque<>();
        Set<String> seen = new HashSet<>();
        pending.add(method.getDeclaringClass());
        while (!pending.isEmpty()) {
            SootClass next = pending.removeFirst();
            if (!seen.add(next.getName())) continue;
            if (next.getName().startsWith("java.util.function.")
                    && next.resolvingLevel() >= SootClass.SIGNATURES) {
                for (SootMethod declared : next.getMethods()) {
                    if (declared.getName().equals(name)
                            && declared.getParameterCount() == method.getParameterCount()) {
                        return true;
                    }
                }
            }
            if (next.hasSuperclass()) pending.add(next.getSuperclass());
            pending.addAll(next.getInterfaces());
        }
        return false;
    }

    private static boolean isAsyncSubmission(SootMethodRef ref) {
        String owner = ref.declaringClass().getName();
        String name = ref.name();
        boolean schedule = "execute".equals(name) || "submit".equals(name)
                || "java.lang.Thread".equals(owner) && "<init>".equals(name)
                || (owner.startsWith("java.util.concurrent.CompletableFuture")
                    || owner.startsWith("java.util.concurrent.CompletionStage"))
                    && (name.startsWith("then") || name.startsWith("whenComplete")
                        || name.startsWith("handle") || name.startsWith("exceptionally")
                        || name.startsWith("runAsync") || name.startsWith("supplyAsync"));
        if (!schedule) return false;
        for (Type parameter : ref.parameterTypes()) {
            String type = parameter.toString();
            if ("java.lang.Runnable".equals(type)
                    || "java.util.concurrent.Callable".equals(type)
                    || type.startsWith("java.util.function.")) return true;
        }
        return false;
    }

    private static boolean sootLambdaBootstrap(StaticInvokeExpr invoke) {
        SootMethodRef ref = invoke.getMethodRef();
        String owner = ref.declaringClass().getName();
        if (!"bootstrap$".equals(ref.name()) || !owner.contains("$lambda_")
                || !owner.matches(".*__\\d+$") || !(ref.returnType() instanceof RefType)
                || !Scene.v().containsClass(owner)) return false;
        return subtypeOf(Scene.v().getSootClass(owner), ref.returnType().toString());
    }

    private void mark(Site site, String reason) {
        if (site == null) return;
        boolean newReason = evidence.computeIfAbsent(site.id, x -> new LinkedHashSet<>())
                .add(reason);
        if (selected.putIfAbsent(site.id, site) == null) {
            queue.addLast(site);
            if (selected.size() % 5000 == 0) {
                System.err.println("Mallory static scope progress: " + selected.size()
                        + " candidate units, " + selectedFields.size() + " fields");
            }
        } else if (newReason && ("local_reaching_definition".equals(reason)
                || "field_wide_writer_jump".equals(reason)
                || "control_postdom_may".equals(reason)
                || "call_return_jump".equals(reason))
                && expanded.remove(site.id)) {
            queue.addLast(site);
        }
    }

    private void selectFieldAccessesAndDoors() {
        Set<Method> selectedMethods = new LinkedHashSet<>();
        for (Site site : selected.values()) selectedMethods.add(site.owner);
        for (Method method : selectedMethods) {
            for (Site site : method.sites) {
                Stmt stmt = (Stmt) site.unit;
                if (stmt instanceof AssignStmt) {
                    Value right = ((AssignStmt) stmt).getRightOp();
                    Value left = ((AssignStmt) stmt).getLeftOp();
                    if (right instanceof FieldRef) {
                        String field = ((FieldRef) right).getFieldRef().getSignature();
                        if (selectedFields.contains(field)) mark(site, "selected_field_read");
                    }
                    if (left instanceof FieldRef) {
                        String field = ((FieldRef) left).getFieldRef().getSignature();
                        if (selectedFields.contains(field)) mark(site, "selected_field_write");
                    }
                }
                if (stmt.containsInvokeExpr() && isInstrumentationHelper(site.owner)) {
                    if (isIoDoor(stmt.getInvokeExpr().getMethodRef())) {
                        analysisGaps.add("instrumentation_helper_door_excluded:" + site.id);
                    }
                } else if (stmt.containsInvokeExpr()
                        && isIoDoor(stmt.getInvokeExpr().getMethodRef())) {
                    mark(site, "selected_method_io_door");
                } else if (stmt.containsInvokeExpr()
                        && "<init>".equals(stmt.getInvokeExpr().getMethodRef().name())
                        && opensResourceInConstructor(stmt.getInvokeExpr().getMethodRef())
                        && !isIoDoor(stmt.getInvokeExpr().getMethodRef())) {
                    analysisGaps.add("resource_constructor_probe_unverified:" + site.id);
                }
            }
        }
        // The additions above are observation sites. They need not widen the
        // backward worklist; the target slice has already reached their method.
        queue.clear();
    }

    private boolean isIoDoor(SootMethodRef ref) {
        String owner = ref.declaringClass().getName();
        String name = ref.name();
        if (owner.endsWith("Exception")
                || owner.endsWith("Error") || owner.contains("ByteArray")
                || owner.contains("CharArray") || owner.contains("ByteBuffer")
                || owner.contains("ZxidUtils")) return false;
        if ("<init>".equals(name)) return verifiedConstructorDoors()
                && VERIFIED_RESOURCE_CONSTRUCTORS.contains(ref.getSignature())
                && opensResourceInConstructor(ref);
        if (name.startsWith("<")) return false;
        String signature = ref.getSignature();
        for (Pattern pattern : ioDoorMappings) {
            if (pattern.matcher(signature).find()) return true;
        }
        if (protobufRpc(ref)) return true;
        if (owner.startsWith("java.io.")) {
            return declaresIoFault(ref)
                    && (IO_VERBS.contains(name) || name.startsWith("read")
                        || name.startsWith("write") || "append".equals(name))
                    && (owner.contains("Stream")
                    || owner.contains("Reader") || owner.contains("Writer")
                    || owner.equals("java.io.DataInput")
                    || owner.equals("java.io.DataOutput")
                    || owner.equals("java.io.ObjectInput")
                    || owner.equals("java.io.ObjectOutput")
                    || owner.equals("java.io.RandomAccessFile")
                    || owner.equals("java.io.File")
                    || owner.equals("java.io.FileDescriptor"));
        }
        if (owner.equals("java.nio.file.Files")) {
            return declaresIoFault(ref) && (name.startsWith("read") || name.startsWith("write")
                    || name.startsWith("new") || name.startsWith("copy")
                    || name.startsWith("move") || name.startsWith("delete")
                    || name.startsWith("create"));
        }
        if (owner.startsWith("java.nio.channels.")) {
            return declaresIoFault(ref) && IO_VERBS.contains(name) && (owner.contains("FileChannel")
                    || owner.contains("SocketChannel")
                    || owner.contains("ServerSocketChannel")
                    || owner.contains("DatagramChannel"));
        }
        if (owner.startsWith("java.net.")) {
            return declaresIoFault(ref) && IO_VERBS.contains(name) && (owner.contains("Socket")
                    || owner.contains("Datagram")
                    || owner.contains("URLConnection"));
        }
        if (owner.startsWith("org.apache.hadoop.ipc.")) {
            return name.equals("call") || name.equals("sendRpcRequest")
                    || name.equals("receiveResponse")
                    || name.equals("receiveRpcRequest");
        }
        if (owner.startsWith("org.apache.hadoop.hbase.ipc.")) {
            return name.equals("call") || name.equals("sendRequest")
                    || name.equals("writeRequest") || name.equals("readResponse");
        }
        if (owner.equals("org.apache.zookeeper.ZooKeeper")
                || owner.equals("org.apache.solr.common.cloud.SolrZkClient")) {
            return Arrays.asList("getData", "setData", "create", "delete",
                    "exists", "getChildren", "multi", "sync").contains(name);
        }
        if (owner.equals("org.apache.zookeeper.server.persistence.FileTxnLog")) {
            return Arrays.asList("append", "commit", "rollLog").contains(name);
        }
        if (owner.equals("org.apache.zookeeper.server.persistence.FileSnap")) {
            return Arrays.asList("serialize", "deserialize").contains(name);
        }
        if (owner.equals("org.apache.zookeeper.server.quorum.Learner")) {
            return name.equals("writePacket") || name.equals("readPacket");
        }
        if (owner.equals("org.apache.solr.client.solrj.impl.HttpSolrClient")) {
            return name.equals("request") || name.equals("executeMethod");
        }
        return false;
    }

    private static boolean isInstrumentationHelper(Method method) {
        String clazz = method.soot.getDeclaringClass().getName();
        String simple = clazz.substring(clazz.lastIndexOf('.') + 1);
        return clazz.startsWith("edu.uva.liftlab.mallory.graphchecker.")
                || clazz.startsWith("edu.uva.liftlab.graphchecker.")
                || simple.startsWith("GraphChecker")
                || simple.startsWith("Mallory");
    }

    private static boolean opensResourceInConstructor(SootMethodRef ref) {
        if (!declaresIoFault(ref)) return false;
        SootClass clazz = ref.declaringClass();
        String owner = clazz.getName();
        if (owner.startsWith("java.io.")) {
            return subtypeOf(clazz, "java.io.InputStream")
                    || subtypeOf(clazz, "java.io.OutputStream")
                    || subtypeOf(clazz, "java.io.Reader")
                    || subtypeOf(clazz, "java.io.Writer")
                    || "java.io.RandomAccessFile".equals(owner);
        }
        if (owner.startsWith("java.net.")) {
            return subtypeOf(clazz, "java.net.Socket")
                    || subtypeOf(clazz, "java.net.ServerSocket")
                    || subtypeOf(clazz, "java.net.DatagramSocket");
        }
        return subtypeOf(clazz, "java.util.zip.ZipFile");
    }

    private boolean verifiedConstructorDoors() {
        return analysisConfig.has("constructor_io_doors_verified")
                && analysisConfig.get("constructor_io_doors_verified").getAsBoolean();
    }

    private static boolean declaresIoFault(SootMethodRef ref) {
        try {
            for (SootClass exception : ref.resolve().getExceptions()) {
                if (subtypeOf(exception, "java.io.IOException")) return true;
            }
        } catch (RuntimeException unresolved) {
            return false;
        }
        return false;
    }

    private String faultClassForDoor(SootMethodRef ref) {
        String override = string(analysisConfig, "io_fault_class", "");
        if (!override.isEmpty()) return override;
        if (protobufRpc(ref)) {
            try {
                for (SootClass exception : ref.resolve().getExceptions()) {
                    if (exception.getName().endsWith(".protobuf.ServiceException")) {
                        return exception.getName();
                    }
                }
            } catch (RuntimeException unresolved) {
                // The transport remains a candidate; the controller's
                // default IOException is recorded explicitly below.
            }
        }
        String owner = ref.declaringClass().getName();
        if (owner.equals("org.apache.zookeeper.ZooKeeper")
                || owner.equals("org.apache.solr.common.cloud.SolrZkClient")) {
            return "org.apache.zookeeper.KeeperException$ConnectionLossException";
        }
        return "java.io.IOException";
    }

    private void discoverPorts(JsonObject analysis) {
        // GraphChecker's protobuf RPC mapping rule: a service method with a
        // protobuf RpcController first argument carries its second argument
        // as request and its return as response.  All application callsites
        // and concrete server entries of that service are candidate captures.
        Set<Method> selectedMethods = new LinkedHashSet<>();
        for (Site site : selected.values()) selectedMethods.add(site.owner);
        Map<String, Port> requestPorts = new LinkedHashMap<>();
        Map<String, Port> responsePorts = new LinkedHashMap<>();
        for (Method method : methods.values()) {
            for (Site site : method.sites) {
                Stmt stmt = (Stmt) site.unit;
                if (!stmt.containsInvokeExpr()) continue;
                SootMethodRef ref = stmt.getInvokeExpr().getMethodRef();
                if (!protobufRpc(ref) || !selectedMethods.contains(method)) continue;
                String id = "protobuf:" + ref.getSignature();
                Port request = requestPorts.computeIfAbsent(id, key -> {
                    Port created = new Port(key + ":request", "RPC_REQUEST", ref.getSignature());
                    ports.add(created);
                    return created;
                });
                request.producers.add(site);
                for (Method receiver : resolveCallees(site)) {
                    Site param = receiver.parameter(1);
                    if (param != null && !request.consumers.contains(param)) request.consumers.add(param);
                }
                Port response = responsePorts.computeIfAbsent(id, key -> {
                    Port created = new Port(key + ":response", "RPC_RESPONSE", ref.getSignature());
                    ports.add(created);
                    return created;
                });
                for (Method sender : resolveCallees(site)) {
                    for (Site ret : sender.sites) {
                        if (ret.unit instanceof soot.jimple.ReturnStmt
                                && !response.producers.contains(ret)) response.producers.add(ret);
                    }
                }
                response.consumers.add(site);
            }
        }
        // A system-wide protocol map can describe HTTP, ZK or custom RPC
        // transports. Entries name API signatures or regexes, never a case's
        // fault point. Both halves remain MAY candidates until runtime IDs
        // pair the exact message.
        JsonArray mappings = array(analysis, "rpc_mappings");
        for (JsonElement element : mappings) {
            if (!element.isJsonObject()) continue;
            JsonObject map = element.getAsJsonObject();
            String id = string(map, "portId", "");
            if (id.isEmpty()) throw new IllegalArgumentException("rpc_mappings.portId required");
            Port port = new Port(id, string(map, "transport", "MAPPED_RPC"), "");
            Pattern send = Pattern.compile(string(map, "sendMethod", "^$"));
            Pattern receive = Pattern.compile(string(map, "receiveMethod", "^$"));
            for (Method method : methods.values()) {
                if (!selectedMethods.contains(method)) continue;
                for (Site site : method.sites) {
                    Stmt stmt = (Stmt) site.unit;
                    if (!stmt.containsInvokeExpr()) continue;
                    String sig = stmt.getInvokeExpr().getMethodRef().getSignature();
                    if (send.matcher(sig).find()) port.producers.add(site);
                    if (receive.matcher(sig).find()) port.consumers.add(site);
                }
            }
            if (!port.producers.isEmpty() || !port.consumers.isEmpty()) ports.add(port);
        }
    }

    private static boolean protobufRpc(SootMethodRef method) {
        return method.parameterTypes().size() >= 2 && method.parameterTypes().get(0)
                .toString().endsWith(".protobuf.RpcController");
    }

    private JsonObject output() {
        List<JsonObject> rows = new ArrayList<>();
        Set<String> rowKeys = new HashSet<>();
        List<Site> sorted = new ArrayList<>(selected.values());
        sorted.sort(Comparator.comparing(site -> site.id));
        Set<Method> selectedMethods = new LinkedHashSet<>();
        for (Site site : sorted) selectedMethods.add(site.owner);
        selectedMethods.add(target.owner);
        for (Method method : selectedMethods) {
            if (!method.sites.isEmpty()) add(rows, rowKeys,
                    row("REGION_SITE", method.sites.get(0), "", ""));
        }
        add(rows, rowKeys, row(target.unit instanceof ThrowStmt
                ? "THROW_SITE" : "TARGET_SITE", target, "", ""));
        if (fatalThrow != null && fatalThrow != target) {
            add(rows, rowKeys, row("THROW_SITE", fatalThrow, "", ""));
        }
        for (Site site : sorted) {
            if (checkSites.contains(site)) add(rows, rowKeys,
                    row("TARGET_SITE", site, "", ""));
            Stmt stmt = (Stmt) site.unit;
            if (stmt instanceof AssignStmt) {
                Value right = ((AssignStmt) stmt).getRightOp();
                Value left = ((AssignStmt) stmt).getLeftOp();
                if (right instanceof FieldRef) {
                    String field = ((FieldRef) right).getFieldRef().getSignature();
                    if (selectedFields.contains(field)) add(rows, rowKeys,
                            row("READ_SITE", site, field, ""));
                }
                if (left instanceof FieldRef) {
                    String field = ((FieldRef) left).getFieldRef().getSignature();
                    if (selectedFields.contains(field)) add(rows, rowKeys,
                            row("WRITE_SITE", site, field, ""));
                }
            }
            if (stmt.containsInvokeExpr()) {
                SootMethodRef ref = stmt.getInvokeExpr().getMethodRef();
                if (!isInstrumentationHelper(site.owner) && isIoDoor(ref)) add(rows, rowKeys,
                        row("DOOR_SITE", site, "", ref.getSignature()));
                if (stmt.getInvokeExpr() instanceof InstanceInvokeExpr
                        && MUTATORS.contains(ref.name())) {
                    Value base = ((InstanceInvokeExpr) stmt.getInvokeExpr()).getBase();
                    for (String field : site.owner.originFields(base, site.unit,
                            new HashSet<Unit>())) {
                        if (selectedFields.contains(field)) add(rows, rowKeys,
                                row("WRITE_SITE", site, field, ref.getSignature()));
                    }
                }
            }
        }
        for (Port port : ports) {
            for (Site producer : port.producers) add(rows, rowKeys,
                    row("EXPORT_SITE", producer, "", port.id));
            for (Site consumer : port.consumers) add(rows, rowKeys,
                    row("IMPORT_SITE", consumer, "", port.id));
        }
        rows.sort(Comparator.comparing(x -> x.get("role").getAsString() + "|"
                + x.get("siteId").getAsString() + "|"
                + string(x, "portId", string(x, "cell", ""))));
        JsonArray scope = new JsonArray();
        for (JsonObject row : rows) scope.add(row);
        JsonObject manifest = manifest(rows, selectedMethods);
        JsonObject result = new JsonObject();
        result.addProperty("schemaVersion", 1);
        result.addProperty("analysisKind", "graphchecker_derived_static_scope");
        result.addProperty("caseId", string(config, "case_id", ""));
        result.addProperty("sootDependencyClasspathSha256", sha256Full(
                String.join(File.pathSeparator,
                        strings(analysisConfig.get("classpath")))));
        result.addProperty("targetSiteId", checkSites.isEmpty()
                ? target.id : checkSites.get(0).id);
        result.addProperty("throwSiteId", fatalThrow == null ? "" : fatalThrow.id);
        result.add("scopeSites", scope);
        result.add("weaveManifest", manifest);
        JsonArray gaps = new JsonArray();
        for (String gap : analysisGaps) gaps.add(gap);
        result.add("analysisGaps", gaps);
        return result;
    }

    private JsonObject row(String role, Site site, String cell, String extra) {
        JsonObject out = new JsonObject();
        out.addProperty("schemaVersion", 1);
        out.addProperty("kind", "STATIC_SCOPE_SITE");
        out.addProperty("role", role);
        out.addProperty("regionId", site.owner.regionId);
        out.addProperty("siteId", site.id);
        out.addProperty("vmSite", site.owner.soot.getSignature());
        out.addProperty("clazz", site.owner.soot.getDeclaringClass().getName());
        out.addProperty("method", site.owner.soot.getName());
        out.addProperty("descriptor", descriptor(site.owner.soot));
        out.addProperty("line", site.line);
        out.addProperty("unitIndex", site.index);
        if (site.bci >= 0) out.addProperty("bytecodeOffset", site.bci);
        if (!cell.isEmpty()) {
            out.addProperty("cell", cell);
            out.addProperty("carrier", cell);
            out.addProperty("static", fieldStatic(site, cell));
        }
        if ("EXPORT_SITE".equals(role) || "IMPORT_SITE".equals(role)) out.addProperty("portId", extra);
        if ("DOOR_SITE".equals(role)) {
            out.addProperty("callee", extra);
            out.addProperty("exceptionClass", faultClassForDoor(
                    ((Stmt) site.unit).getInvokeExpr().getMethodRef()));
        }
        JsonArray guards = new JsonArray();
        for (Unit guard : site.owner.guardsOf(site.unit)) guards.add(site.owner.site(guard).id);
        out.add("guards", guards);
        JsonArray why = new JsonArray();
        for (String reason : evidence.getOrDefault(site.id, Collections.<String>emptySet())) why.add(reason);
        out.add("evidence", why);
        return out;
    }

    private static boolean fieldStatic(Site site, String signature) {
        for (ValueBox box : site.unit.getUseAndDefBoxes()) {
            if (box.getValue() instanceof FieldRef) {
                FieldRef ref = (FieldRef) box.getValue();
                if (ref.getFieldRef().getSignature().equals(signature)) {
                    return ref instanceof soot.jimple.StaticFieldRef;
                }
            }
        }
        return false;
    }

    private static void add(List<JsonObject> rows, Set<String> seen, JsonObject row) {
        String key = row.get("role").getAsString() + "|" + row.get("siteId").getAsString()
                + "|" + string(row, "cell", "") + "|" + string(row, "portId", "");
        if (seen.add(key)) rows.add(row);
    }

    private JsonObject manifest(List<JsonObject> rows, Set<Method> selectedMethods) {
        JsonObject out = new JsonObject();
        out.addProperty("schemaVersion", 1);
        out.addProperty("caseId", string(config, "case_id", ""));
        out.addProperty("sootDependencyClasspathSha256", sha256Full(
                String.join(File.pathSeparator,
                        strings(analysisConfig.get("classpath")))));
        JsonArray regions = new JsonArray();
        JsonArray frames = new JsonArray();
        JsonArray coverage = new JsonArray();
        List<Method> sorted = new ArrayList<>(selectedMethods);
        sorted.sort(Comparator.comparing(method -> method.soot.getSignature()));
        for (Method method : sorted) {
            String className = method.soot.getDeclaringClass().getName();
            if (!materializedClasses.contains(className)) {
                analysisGaps.add("unmaterialized_scope_class:" + className);
                continue;
            }
            JsonObject ref = methodRef(method);
            JsonObject region = ref.deepCopy();
            region.addProperty("regionId", method.regionId);
            region.addProperty("sourceOwner", sourceOwner(method));
            regions.add(region);
            frames.add(ref.deepCopy());
            for (Site site : method.sites) {
                if (!site.isBranch()) continue;
                JsonObject branch = ref.deepCopy();
                branch.addProperty("siteId", site.id);
                branch.addProperty("line", site.line);
                branch.addProperty("unitIndex", site.index);
                coverage.add(branch);
            }
        }
        out.add("regions", regions);
        out.add("frames", frames);
        out.add("coverage", coverage);
        JsonArray targets = new JsonArray();
        JsonArray doors = new JsonArray();
        JsonArray state = new JsonArray();
        JsonArray rpc = new JsonArray();
        for (JsonObject row : rows) {
            String role = row.get("role").getAsString();
            if (!materializedClasses.contains(row.get("clazz").getAsString())) {
                if ("TARGET_SITE".equals(role) || "THROW_SITE".equals(role)) {
                    throw new IllegalStateException("target class has no compiled bytecode: "
                            + row.get("clazz").getAsString());
                }
                continue;
            }
            JsonObject ref = new JsonObject();
            for (String key : Arrays.asList("clazz", "method", "descriptor", "line", "unitIndex", "siteId")) {
                ref.add(key, row.get(key));
            }
            if ("THROW_SITE".equals(role)) {
                ref.addProperty("kind", "THROW");
                Site oracle = fatalThrow;
                ref.addProperty("exceptionClass", ((ThrowStmt) oracle.unit)
                        .getOp().getType().toString());
                targets.add(ref);
            } else if ("TARGET_SITE".equals(role)) {
                ref.addProperty("kind", "BRANCH");
                targets.add(ref);
            } else if ("DOOR_SITE".equals(role)) {
                if (row.get("line").getAsInt() <= 0) {
                    analysisGaps.add("door_source_line_unavailable:" + row.get("siteId").getAsString());
                    continue;
                }
                ref.add("callee", row.get("callee"));
                ref.add("exceptionClass", row.get("exceptionClass"));
                doors.add(ref);
            } else if ("READ_SITE".equals(role) || "WRITE_SITE".equals(role)) {
                if (row.get("line").getAsInt() <= 0) {
                    analysisGaps.add("state_source_line_unavailable:" + row.get("siteId").getAsString());
                    continue;
                }
                ref.addProperty("access", "READ_SITE".equals(role) ? "READ" : "WRITE");
                ref.add("field", row.get("cell"));
                ref.add("staticField", row.get("static"));
                state.add(ref);
            }
        }
        for (Port port : ports) rpc.add(port.json());
        out.add("targets", targets);
        out.add("doors", doors);
        out.add("stateCandidates", state);
        out.add("rpcPorts", rpc);
        return out;
    }

    private String sourceOwner(Method method) {
        if (method.soot.isStatic()) return "CURRENT";
        String clazz = method.soot.getDeclaringClass().getName();
        for (Pattern pattern : sourceOwnerClasses) {
            if (pattern.matcher(clazz).matches()) return "THIS";
        }
        return "CURRENT";
    }

    private static JsonObject methodRef(Method method) {
        JsonObject out = new JsonObject();
        out.addProperty("clazz", method.soot.getDeclaringClass().getName());
        out.addProperty("method", method.soot.getName());
        out.addProperty("descriptor", descriptor(method.soot));
        return out;
    }

    private static String descriptor(SootMethod method) {
        StringBuilder out = new StringBuilder("(");
        for (Type type : method.getParameterTypes()) out.append(typeDescriptor(type));
        return out.append(')').append(typeDescriptor(method.getReturnType())).toString();
    }

    private static String typeDescriptor(Type type) {
        if (type instanceof ArrayType) {
            ArrayType array = (ArrayType) type;
            StringBuilder out = new StringBuilder();
            for (int i = 0; i < array.numDimensions; i++) out.append('[');
            return out.append(typeDescriptor(array.baseType)).toString();
        }
        if (type instanceof RefType) return "L" + type.toString().replace('.', '/') + ";";
        switch (type.toString()) {
            case "void": return "V";
            case "boolean": return "Z";
            case "byte": return "B";
            case "char": return "C";
            case "short": return "S";
            case "int": return "I";
            case "long": return "J";
            case "float": return "F";
            case "double": return "D";
            default: throw new IllegalArgumentException("unsupported descriptor type " + type);
        }
    }

    private static String digest(String text) {
        try {
            byte[] bytes = MessageDigest.getInstance("SHA-256")
                    .digest(text.getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder();
            for (int i = 0; i < 8; i++) hex.append(String.format("%02x", bytes[i] & 0xff));
            return hex.toString();
        } catch (Exception impossible) { throw new IllegalStateException(impossible); }
    }

    private static String sha256Full(String text) {
        try {
            byte[] bytes = MessageDigest.getInstance("SHA-256")
                    .digest(text.getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder();
            for (byte value : bytes) hex.append(String.format("%02x", value & 0xff));
            return hex.toString();
        } catch (Exception impossible) { throw new IllegalStateException(impossible); }
    }

    private static JsonObject object(JsonObject value, String key) {
        return value != null && value.has(key) && value.get(key).isJsonObject()
                ? value.getAsJsonObject(key) : new JsonObject();
    }
    private static JsonArray array(JsonObject value, String key) {
        return value != null && value.has(key) && value.get(key).isJsonArray()
                ? value.getAsJsonArray(key) : new JsonArray();
    }
    private static String string(JsonObject value, String key, String fallback) {
        return value != null && value.has(key) && !value.get(key).isJsonNull()
                ? value.get(key).getAsString() : fallback;
    }
    private static int integer(JsonObject value, String key, int fallback) {
        return value != null && value.has(key) && !value.get(key).isJsonNull()
                ? value.get(key).getAsInt() : fallback;
    }
    private static List<String> strings(JsonElement values) {
        List<String> out = new ArrayList<>();
        if (values != null && values.isJsonArray()) {
            for (JsonElement value : values.getAsJsonArray()) out.add(value.getAsString());
        }
        return out;
    }

    private static final class Port {
        final String id;
        final String transport;
        final String serviceMethod;
        final List<Site> producers = new ArrayList<>();
        final List<Site> consumers = new ArrayList<>();
        Port(String id, String transport, String serviceMethod) {
            this.id = id; this.transport = transport; this.serviceMethod = serviceMethod;
        }
        JsonObject json() {
            JsonObject out = new JsonObject();
            out.addProperty("portId", id);
            out.addProperty("transport", transport);
            if (!serviceMethod.isEmpty()) out.addProperty("serviceMethod", serviceMethod);
            JsonArray exports = new JsonArray();
            for (Site site : producers) exports.add(site.id);
            JsonArray imports = new JsonArray();
            for (Site site : consumers) imports.add(site.id);
            out.add("exports", exports);
            out.add("imports", imports);
            return out;
        }
    }

    private static final class Site {
        final Method owner;
        final Unit unit;
        final int index;
        final int line;
        final int bci;
        final String id;
        Site(Method owner, Unit unit, int index) {
            this.owner = owner; this.unit = unit; this.index = index;
            this.line = unit.getJavaSourceStartLineNumber();
            Tag tag = unit.getTag("BytecodeOffsetTag");
            this.bci = tag instanceof BytecodeOffsetTag
                    ? ((BytecodeOffsetTag) tag).getBytecodeOffset() : -1;
            this.id = owner.soot.getSignature() + "#u" + index;
        }
        boolean isBranch() {
            return unit instanceof IfStmt || unit instanceof LookupSwitchStmt
                    || unit instanceof TableSwitchStmt;
        }
    }

    private static final class Method {
        final SootMethod soot;
        final Body body;
        final List<Site> sites = new ArrayList<>();
        final Map<Unit, Site> byUnit = new HashMap<>();
        SimpleLocalDefs defs;
        BriefUnitGraph graph;
        MHGPostDominatorsFinder<Unit> postdom;
        MHGDominatorsFinder<Unit> dom;
        Boolean callback;
        final String regionId;
        Method(SootMethod soot, Body captured) {
            this.soot = soot;
            this.body = captured;
            this.regionId = "R." + digest(soot.getSignature());
            int index = 0;
            for (Unit unit : body.getUnits()) {
                Site site = new Site(this, unit, index++);
                sites.add(site);
                byUnit.put(unit, site);
            }
        }
        Site site(Unit unit) { return byUnit.get(unit); }
        int indexOf(Unit unit) { Site site = byUnit.get(unit); return site == null ? -1 : site.index; }
        boolean isCallback() {
            if (callback == null) callback = isCallbackMethod(soot);
            return callback;
        }
        void flow() {
            if (graph == null) {
                graph = new BriefUnitGraph(body);
                defs = new SimpleLocalDefs(graph);
                postdom = new MHGPostDominatorsFinder<>(graph);
                dom = new MHGDominatorsFinder<>(graph);
            }
        }
        boolean handlerDominates(Unit handler, Unit selected) {
            flow();
            return dom.getDominators(selected).contains(handler);
        }
        Site parameter(int ordinal) {
            for (Site site : sites) {
                if (site.unit instanceof IdentityStmt) {
                    Value right = ((IdentityStmt) site.unit).getRightOp();
                    if (right instanceof ParameterRef
                            && ((ParameterRef) right).getIndex() == ordinal) return site;
                }
            }
            return null;
        }
        // A complete set of intraprocedural new-expression origins. null
        // means unknown (formal, field, call return or cycle) and therefore
        // forbids filtering any writer. This only improves precision when
        // disjointness is proven; it cannot remove an unresolved alias.
        Set<String> allocationOrigins(Value value, Unit at, Set<Unit> seen) {
            if (!(value instanceof Local)) return null;
            flow();
            Set<String> origins = new LinkedHashSet<>();
            for (Unit def : defs.getDefsOfAt((Local) value, at)) {
                if (!seen.add(def) || !(def instanceof AssignStmt)) return null;
                Value source = ((AssignStmt) def).getRightOp();
                if (source instanceof NewExpr) {
                    origins.add(site(def).id);
                } else if (source instanceof Local) {
                    Set<String> nested = allocationOrigins(source, def, seen);
                    if (nested == null) return null;
                    origins.addAll(nested);
                } else {
                    return null;
                }
            }
            return origins.isEmpty() ? null : origins;
        }
        Set<String> allocationTypes(Value value, Unit at, Set<Unit> seen) {
            if (!(value instanceof Local)) return null;
            flow();
            Set<String> types = new LinkedHashSet<>();
            for (Unit def : defs.getDefsOfAt((Local) value, at)) {
                if (!seen.add(def) || !(def instanceof AssignStmt)) return null;
                Value source = ((AssignStmt) def).getRightOp();
                if (source instanceof NewExpr) {
                    types.add(source.getType().toString());
                } else if (source instanceof StaticInvokeExpr
                        && sootLambdaBootstrap((StaticInvokeExpr) source)) {
                    // Soot lowers invokedynamic to a synthetic lambda class
                    // with a bootstrap$ factory. The factory's declared
                    // return is only Callable/Function/etc., but its owner
                    // is the concrete implementation class. This is a
                    // proven allocation, unlike an arbitrary call result.
                    types.add(((StaticInvokeExpr) source).getMethodRef()
                            .declaringClass().getName());
                } else if (source instanceof Local) {
                    Set<String> nested = allocationTypes(source, def, seen);
                    if (nested == null) return null;
                    types.addAll(nested);
                } else {
                    return null;
                }
                seen.remove(def);
            }
            return types.isEmpty() ? null : types;
        }
        Set<String> originFields(Value value, Unit at, Set<Unit> seen) {
            flow();
            Set<String> found = new LinkedHashSet<>();
            if (value instanceof FieldRef) {
                found.add(((FieldRef) value).getFieldRef().getSignature());
            } else if (value instanceof Local) {
                for (Unit def : defs.getDefsOfAt((Local) value, at)) {
                    if (!seen.add(def)) continue;
                    if (def instanceof AssignStmt) found.addAll(originFields(
                            ((AssignStmt) def).getRightOp(), def, seen));
                    seen.remove(def);
                }
            }
            return found;
        }
        List<Unit> guardsOf(Unit unit) {
            flow();
            List<Unit> out = new ArrayList<>();
            for (Site branch : sites) {
                if (!branch.isBranch()) continue;
                if (postdom.getDominators(branch.unit).contains(unit)) continue;
                for (Unit successor : graph.getSuccsOf(branch.unit)) {
                    if (postdom.getDominators(successor).contains(unit)) {
                        out.add(branch.unit);
                        break;
                    }
                }
            }
            return out;
        }
        boolean reachable(Unit from, Unit to) {
            flow();
            if (from == to) return true;
            Deque<Unit> todo = new ArrayDeque<>();
            Set<Unit> seen = new HashSet<>();
            todo.add(from);
            while (!todo.isEmpty()) {
                Unit current = todo.removeFirst();
                if (!seen.add(current)) continue;
                for (Unit next : graph.getSuccsOf(current)) {
                    if (next == to) return true;
                    if (!seen.contains(next)) todo.add(next);
                }
            }
            return false;
        }
    }
}
