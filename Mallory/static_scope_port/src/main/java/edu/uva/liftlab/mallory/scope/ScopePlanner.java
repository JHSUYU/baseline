package edu.uva.liftlab.mallory.scope;

import edu.uva.liftlab.mallory.graphcheckerstatic.GraphCheckerRegionPlanner;
import edu.uva.liftlab.graphchecker.MalloryLambdaClassNames;
import edu.uva.liftlab.graphchecker.MallorySharedInitializationSplitter;
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
import soot.PhaseOptions;
import soot.RefType;
import soot.Scene;
import soot.SceneTransformer;
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
import soot.util.Chain;
import soot.tagkit.BytecodeOffsetTag;
import soot.tagkit.Tag;
import soot.toolkits.graph.BriefUnitGraph;
import soot.toolkits.graph.MHGDominatorsFinder;
import soot.toolkits.graph.MHGPostDominatorsFinder;
import soot.toolkits.scalar.SimpleLocalDefs;

import java.io.File;
import java.io.IOException;
import java.io.Writer;
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
    private static final Gson PRETTY_JSON = new GsonBuilder().setPrettyPrinting().create();
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
    // A compound source-level check may lower to several Jimple branches.
    // One branch anchors runtime identity; all branches remain in the static
    // failure demand rooted at the unique throw.
    private final List<Site> compoundCheckSites = new ArrayList<>();

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
        writeJsonLines(output.resolve("static_scope_map.jsonl"),
                result.getAsJsonArray("scopeSites"));
        writePrettyJson(output.resolve("weave_manifest.json"),
                result.getAsJsonObject("weaveManifest"));
        // A large static result is already resident as a JsonObject.  Gson's
        // String-returning toJson overload creates another complete copy and
        // Files.write then creates a UTF-8 byte[] copy.  Stream directly to
        // the file so serialization has bounded additional heap use.
        writePrettyJson(output.resolve("analysis.json"), result);
        if (result.has("graphCheckerRegionPort")) {
            JsonObject port = result.getAsJsonObject("graphCheckerRegionPort");
            writeJsonLines(output.resolve("graphchecker_static_scope_map.jsonl"),
                    port.getAsJsonArray("staticScopeSites"));
            writePrettyJson(output.resolve("graphchecker_region_skeletons.json"),
                    port.get("regions"));
            writePrettyJson(output.resolve("graphchecker_weave_manifest.json"),
                    port.get("weaveManifest"));
            writePrettyJson(output.resolve("graphchecker_static_facts.json"),
                    port.get("facts"));
        }
        return result;
    }

    static void writeJsonLines(Path path, JsonArray rows) throws IOException {
        try (Writer writer = Files.newBufferedWriter(path, StandardCharsets.UTF_8)) {
            for (JsonElement row : rows) {
                JSON.toJson(row, writer);
                writer.write('\n');
            }
        }
    }

    static void writePrettyJson(Path path, JsonElement value) throws IOException {
        try (Writer writer = Files.newBufferedWriter(path, StandardCharsets.UTF_8)) {
            PRETTY_JSON.toJson(value, writer);
        }
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
        boolean originalSeed = analysis.has("original_graphchecker_seed")
                && analysis.get("original_graphchecker_seed").getAsBoolean();
        soot.G.reset();
        Options.v().set_prepend_classpath(true);
        Options.v().set_allow_phantom_refs(true);
        Options.v().set_whole_program(originalSeed);
        // Legacy bytecode weaving selects jtp-entry units; the original
        // GraphChecker pipeline selects wjtp units. Capture each mode's
        // active body at the phase where its corresponding weaver reads it.
        Options.v().set_output_format(Options.output_format_class);
        Options.v().set_keep_line_number(true);
        Options.v().set_keep_offset(!originalSeed);
        if (originalSeed) {
            // Match the original GraphCheckerMain scene before any Jimple
            // body materializes. A selected WRITE_SITE must keep its exact
            // original unit index in the later concolic weave.
            Options.v().set_num_threads(1);
            MallorySharedInitializationSplitter.install();
            PhaseOptions.v().setPhaseOption("jb.lns", "sort-locals:true");
            PhaseOptions.v().setPhaseOption("cg", "off");
            graphCheckerBasicClasses();
        }
        Options.v().set_process_dir(dirs);
        Options.v().set_soot_classpath(String.join(File.pathSeparator, classpath));
        Scene.v().loadNecessaryClasses();
        if (originalSeed) orderSceneClassesByName();
        // The original GraphChecker installs this factory after class loading
        // and before the first body is materialized.  Static region/site IDs
        // must use the same content-derived names as its weaver.
        MalloryLambdaClassNames.install();
        if (originalSeed) {
            // GraphCheckerTransformer runs in wjtp and reads active Jimple
            // bodies there.  jtp can rewrite their unit order afterwards;
            // capturing at jtp made a static #u48 refer to a different unit
            // when GraphChecker's concolic weave later read #u48 in wjtp.
            PackManager.v().getPack("wjtp").add(new Transform("wjtp.malloryStaticCapture",
                    new SceneTransformer() {
                        @Override protected void internalTransform(String phase,
                                                                   Map<String, String> options) {
                            List<SootClass> owners = new ArrayList<>(Scene.v().getApplicationClasses());
                            owners.sort(Comparator.comparing(SootClass::getName));
                            for (SootClass owner : owners) {
                                List<SootMethod> sorted = new ArrayList<>(owner.getMethods());
                                sorted.sort(Comparator.comparing(SootMethod::getSignature));
                                for (SootMethod method : sorted) {
                                    if (!method.isConcrete()) continue;
                                    try {
                                        jtpBodies.put(method.getSignature(),
                                                (Body) method.retrieveActiveBody().clone());
                                    } catch (RuntimeException unavailable) {
                                        analysisGaps.add("wjtp_body_unavailable:"
                                                + method.getSignature());
                                    }
                                }
                            }
                        }
                    }));
        } else {
            PackManager.v().getPack("jtp").add(new Transform("jtp.malloryStaticCapture",
                    new BodyTransformer() {
                        @Override protected void internalTransform(Body body, String phase,
                                                                   Map<String, String> options) {
                            jtpBodies.put(body.getMethod().getSignature(), (Body) body.clone());
                        }
                    }));
        }
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
        if (analysis.has("original_graphchecker_seed")
                && analysis.get("original_graphchecker_seed").getAsBoolean()) {
            return originalGraphCheckerSeed(dirs, analysis);
        }
        // The healthy seed reaches a check branch, not its fatal throw. The
        // throw is an oracle probe, deliberately not a backward value seed:
        // exception construction is irrelevant to what makes the check fail.
        if (checkSites.isEmpty()) mark(target, "declared_target_fallback");
        for (Site check : compoundCheckSites) {
            if (check != target) mark(check, "compound_target_control");
        }
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

    private static void graphCheckerBasicClasses() {
        Class<?>[] basics = {java.io.PrintStream.class, System.class,
                Thread.class, Throwable.class};
        for (Class<?> basic : basics) {
            Scene.v().addBasicClass(basic.getCanonicalName(),
                    SootClass.SIGNATURES);
            for (Class<?> inner : basic.getDeclaredClasses()) {
                Scene.v().addBasicClass(inner.getName(),
                        SootClass.SIGNATURES);
            }
        }
        Scene.v().addBasicClass(
                "edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder",
                SootClass.SIGNATURES);
        Scene.v().addBasicClass("java.lang.Object[]", SootClass.HIERARCHY);
        Scene.v().addBasicClass("java.lang.String[]", SootClass.HIERARCHY);
    }

    private static void orderSceneClassesByName() {
        Scene scene = Scene.v();
        for (Chain<SootClass> chain : Arrays.asList(scene.getClasses(),
                scene.getApplicationClasses(), scene.getLibraryClasses(),
                scene.getPhantomClasses())) {
            List<SootClass> named = new ArrayList<>(chain);
            named.sort(Comparator.comparing(SootClass::getName));
            chain.clear();
            chain.addAll(named);
        }
    }

    /**
     * Experimental exact GraphChecker engine path. The optional bridge lives
     * in the ORIGINAL GraphChecker package so it can call the package-private
     * SeedBackwardStaticAnalyzer and CausynthPipeline collaborators directly.
     * No legacy Mallory backward worklist is run on this path.
     */
    private JsonObject originalGraphCheckerSeed(List<String> dirs, JsonObject analysis) {
        if (fatalThrow == null) throw new IllegalArgumentException(
                "original GraphChecker seed requires one explicit fatal throw");
        // GraphChecker's original analyzer reads retrieveActiveBody() in
        // wjtp. Restore those exact wjtp snapshots after runPacks() so later
        // jtp transforms cannot change their unit indices on this opt-in path.
        for (SootClass owner : Scene.v().getApplicationClasses()) {
            for (SootMethod method : owner.getMethods()) {
                Body captured = jtpBodies.get(method.getSignature());
                if (captured != null) method.setActiveBody((Body) captured.clone());
            }
        }
        String directory = string(analysis, "original_engine_output_dir", "");
        if (directory.isEmpty()) throw new IllegalArgumentException(
                "analysis.original_engine_output_dir is required");
        String loopBound = string(analysis, "original_loop_default_bound", "");
        if (!loopBound.matches("[1-9][0-9]*")) throw new IllegalArgumentException(
                "analysis.original_loop_default_bound must explicitly name GraphChecker's loop bound");
        String previousLoopBound = System.getProperty("causynth.loop.default.bound");
        System.setProperty("causynth.loop.default.bound", loopBound);
        JsonObject original;
        try {
            Class<?> bridge = Class.forName("edu.uva.liftlab.graphchecker.causynth."
                    + "MalloryOriginalSeedBridge");
            if (fatalThrow.unit instanceof ThrowStmt) {
                original = (JsonObject) bridge.getMethod("analyze", List.class, Path.class,
                        String.class, int.class, String.class).invoke(null,
                        dirs, Paths.get(directory), fatalThrow.owner.soot
                                .getDeclaringClass().getName(),
                        originalExceptionConstructionLine(fatalThrow),
                        ((ThrowStmt) fatalThrow.unit).getOp().getType().toString());
            } else {
                original = (JsonObject) bridge.getMethod("analyzeCallThrow", List.class,
                        Path.class, String.class, int.class, String.class,
                        String.class).invoke(null, dirs, Paths.get(directory),
                        fatalThrow.owner.soot.getSignature(), fatalThrow.index,
                        ((Stmt) fatalThrow.unit).getInvokeExpr().getMethodRef()
                                .getSignature(),
                        string(object(config, "target"), "exception", ""));
            }
        } catch (ReflectiveOperationException error) {
            Throwable cause = error instanceof java.lang.reflect.InvocationTargetException
                    ? ((java.lang.reflect.InvocationTargetException) error).getCause() : error;
            throw new IllegalStateException("original GraphChecker engine unavailable or failed", cause);
        } finally {
            if (previousLoopBound == null) System.clearProperty("causynth.loop.default.bound");
            else System.setProperty("causynth.loop.default.bound", previousLoopBound);
        }
        Set<Method> held = new LinkedHashSet<>();
        Map<String, String> firstRegionByMethod = new LinkedHashMap<>();
        for (JsonElement name : original.getAsJsonArray("traceMethods")) {
            Method method = methods.get(name.getAsString());
            if (method != null && materializedClasses.contains(
                    method.soot.getDeclaringClass().getName())) held.add(method);
        }
        for (JsonElement item : original.getAsJsonArray("regions")) {
            JsonObject region = item.getAsJsonObject();
            for (JsonElement name : region.getAsJsonArray("methods")) {
                firstRegionByMethod.putIfAbsent(name.getAsString(),
                        string(region, "regionId", ""));
                Method method = methods.get(name.getAsString());
                if (method != null && materializedClasses.contains(
                        method.soot.getDeclaringClass().getName())) held.add(method);
            }
        }
        held.add(target.owner);
        List<JsonObject> rows = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        String originalTargetRegion = "";
        Set<String> originalFatalGuards = new LinkedHashSet<>();
        for (JsonElement item : original.getAsJsonArray("staticScopeSites")) {
            JsonObject source = item.getAsJsonObject();
            if ("TARGET_SITE".equals(string(source, "role", ""))
                    && fatalThrow.id.equals(string(source, "siteId", ""))) {
                originalTargetRegion = string(source, "regionId", "");
                if (source.has("guards")) {
                    for (JsonElement guard : source.getAsJsonArray("guards")) {
                        originalFatalGuards.add(guard.getAsString());
                    }
                }
                if (source.has("chain")) {
                    for (JsonElement guard : source.getAsJsonArray("chain")) {
                        originalFatalGuards.add(string(guard.getAsJsonObject(), "siteId", ""));
                    }
                }
                break;
            }
        }
        if (originalTargetRegion.isEmpty()) throw new IllegalStateException(
                "original GraphChecker target has no selected region: " + fatalThrow.id);
        for (Site control : compoundCheckSites) {
            if (!originalFatalGuards.contains(control.id)) throw new IllegalStateException(
                    "original GraphChecker target omits compound guard: " + control.id);
        }
        // The inventory may name the throw as its target. Runtime feedback
        // must anchor the controlling check, which is reached in the healthy
        // run, rather than the exceptional throw that healthy execution skips.
        List<Site> anchors = checkSites.isEmpty()
                ? Collections.singletonList(target) : checkSites;
        for (Site check : anchors) {
            JsonObject checkRow = row("TARGET_SITE", check, "", "");
            checkRow.addProperty("regionId", originalTargetRegion);
            addOriginal(rows, seen, checkRow);
        }
        JsonObject throwRow = row("THROW_SITE", fatalThrow, "", "");
        throwRow.addProperty("regionId", originalTargetRegion);
        addOriginal(rows, seen, throwRow);
        for (JsonElement item : original.getAsJsonArray("staticScopeSites")) {
            JsonObject source = item.getAsJsonObject();
            String role = string(source, "role", "");
            String id = string(source, "siteId", "");
            Site site = exactSite(id);
            if (site == null) {
                if (!id.isEmpty()) analysisGaps.add("original_graphchecker_site_unmapped:" + id);
                continue;
            }
            if (!materializedClasses.contains(site.owner.soot.getDeclaringClass().getName()))
                continue;
            if ("TARGET_SITE".equals(role) || "ROOT_SITE".equals(role)
                    || "DECLARED_SITE".equals(role)) continue;
            if ("READ_SITE".equals(role) || "WRITE_SITE".equals(role)) {
                String cell = string(source, "cell", "");
                if (!cell.isEmpty()) {
                    JsonObject mapped = row(role, site, cell, "");
                    mapped.addProperty("regionId", string(source, "regionId", ""));
                    addOriginal(rows, seen, mapped);
                }
            } else if ("EXPORT_SITE".equals(role)) {
                JsonObject mapped = row(role, site, "", string(source, "portId", ""));
                mapped.addProperty("regionId", string(source, "regionId", ""));
                addOriginal(rows, seen, mapped);
            }
        }
        for (JsonElement item : original.getAsJsonArray("demandedDoors")) {
            JsonObject source = item.getAsJsonObject();
            String id = string(source, "siteId", "");
            Site site = exactSite(id);
            if (site == null || !((Stmt) site.unit).containsInvokeExpr()) {
                analysisGaps.add("original_graphchecker_door_unmapped:" + id);
                continue;
            }
            SootMethodRef ref = ((Stmt) site.unit).getInvokeExpr().getMethodRef();
            if (isInstrumentationHelper(site.owner) || !isIoDoor(ref)) {
                analysisGaps.add("original_graphchecker_door_uninjectable:" + id);
                continue;
            }
            JsonObject door = row("DOOR_SITE", site, "", ref.getSignature());
            String region = firstRegionByMethod.getOrDefault(
                    site.owner.soot.getSignature(), "");
            if (!region.isEmpty()) door.addProperty("regionId", region);
            addOriginal(rows, seen, door);
        }
        // GraphChecker's demanded doors are value-slice facts.  A fault
        // campaign also needs I/O boundaries along the selected execution
        // regions: an RPC failure can change a later value without the I/O
        // call itself being a data dependency of the target.  This opt-in
        // expansion stays inside GraphChecker's trace/region methods and is
        // explicitly a static MAY set, not an observed causal edge.
        int supplementalDoors = 0;
        if (analysis.has("original_typed_io_frontier")
                && analysis.get("original_typed_io_frontier").getAsBoolean()) {
            for (Method method : held) {
                if (isInstrumentationHelper(method)) continue;
                for (Site site : method.sites) {
                    Stmt stmt = (Stmt) site.unit;
                    if (!stmt.containsInvokeExpr()) continue;
                    SootMethodRef ref = stmt.getInvokeExpr().getMethodRef();
                    if (!isIoDoor(ref)) continue;
                    JsonObject door = row("DOOR_SITE", site, "", ref.getSignature());
                    String region = firstRegionByMethod.getOrDefault(
                            method.soot.getSignature(), "");
                    if (!region.isEmpty()) door.addProperty("regionId", region);
                    door.addProperty("selectionSource", "ORIGINAL_SELECTED_METHOD_IO_FRONTIER");
                    door.addProperty("staticMayOnly", true);
                    int before = rows.size();
                    addOriginal(rows, seen, door);
                    if (rows.size() != before) supplementalDoors++;
                }
            }
        }
        Map<String, Port> originalPorts = new LinkedHashMap<>();
        int parameterPortAnchors = 0;
        int returnPortAnchors = 0;
        for (JsonElement item : original.getAsJsonArray("regions")) {
            JsonObject region = item.getAsJsonObject();
            JsonArray catalog = region.has("communicationPorts")
                    ? region.getAsJsonArray("communicationPorts") : new JsonArray();
            for (JsonElement endpoint : catalog) {
                JsonObject capture = endpoint.getAsJsonObject();
                String portId = string(capture, "portId", "");
                String side = string(capture, "regionPortSide", "");
                String siteId = string(capture, "callSiteId", "");
                if (exactSite(siteId) == null) {
                    String method = string(capture, "definitionMethod", "");
                    int index = integer(capture, "definitionUnitIndex", -1);
                    if (index >= 0) siteId = method + "#u" + index;
                }
                List<Site> sites = new ArrayList<>();
                Site exact = exactSite(siteId);
                boolean parameterAnchor = false;
                boolean returnAnchor = false;
                String captureKind = string(capture, "outputCaptureKind", "");
                if ("METHOD_RETURN".equals(captureKind)) {
                    // A METHOD_RETURN declares the entire method result even
                    // if a catalog happens to nominate one individual exit.
                    sites.addAll(originalReturnSites(capture));
                    returnAnchor = !sites.isEmpty();
                } else if (exact != null) {
                    sites.add(exact);
                } else if ("METHOD_PARAMETER".equals(captureKind)) {
                    Site parameter = originalParameterSite(capture);
                    if (parameter != null) sites.add(parameter);
                    parameterAnchor = !sites.isEmpty();
                }
                if (portId.isEmpty() || sites.isEmpty()) {
                    analysisGaps.add("original_graphchecker_port_unmapped:" + portId + ":" + siteId);
                    continue;
                }
                Port port = originalPorts.computeIfAbsent(portId,
                        id -> new Port(id, string(capture, "transport", "RPC"), ""));
                for (Site site : sites) {
                    if ("OUT".equals(side)) {
                        port.producers.add(site);
                    } else if ("IN".equals(side)) {
                        port.consumers.add(site);
                    } else continue;
                    JsonObject mapped = row("OUT".equals(side) ? "EXPORT_SITE" : "IMPORT_SITE",
                            site, "", portId);
                    mapped.addProperty("regionId", string(region, "regionId", ""));
                    if (parameterAnchor) {
                        mapped.addProperty("selectionSource", "ORIGINAL_METHOD_PARAMETER_CAPTURE");
                        mapped.addProperty("captureArgumentIndex",
                                integer(capture, "argumentIndex", -1));
                        parameterPortAnchors++;
                    } else if (returnAnchor) {
                        mapped.addProperty("selectionSource", "ORIGINAL_METHOD_RETURN_CAPTURE");
                        returnPortAnchors++;
                    }
                    addOriginal(rows, seen, mapped);
                }
            }
        }
        ports.addAll(originalPorts.values());
        JsonObject manifest = manifest(rows, held);
        JsonArray originalRoots = new JsonArray();
        Set<String> rootKeys = new HashSet<>();
        for (JsonElement item : original.getAsJsonArray("regions")) {
            JsonObject region = item.getAsJsonObject();
            Method method = methods.get(string(region, "rootMethod", ""));
            if (method == null || !materializedClasses.contains(
                    method.soot.getDeclaringClass().getName())) continue;
            String key = string(region, "regionId", "") + "|" + method.soot.getSignature();
            if (!rootKeys.add(key)) continue;
            JsonObject ref = methodRef(method);
            ref.addProperty("regionId", string(region, "regionId", ""));
            ref.addProperty("sourceOwner", sourceOwner(method));
            originalRoots.add(ref);
        }
        manifest.add("regions", originalRoots);
        JsonArray scope = new JsonArray();
        for (JsonObject row : rows) scope.add(row);
        JsonObject result = new JsonObject();
        result.addProperty("schemaVersion", 1);
        result.addProperty("analysisKind", "original_graphchecker_seed_backward");
        result.addProperty("caseId", string(config, "case_id", ""));
        result.addProperty("targetSiteId", anchors.get(0).id);
        result.addProperty("throwSiteId", fatalThrow.id);
        addCompoundCheckGroup(result);
        result.addProperty("sootDependencyClasspathSha256", sha256Full(
                String.join(File.pathSeparator, strings(analysisConfig.get("classpath")))));
        result.add("scopeSites", scope);
        result.add("weaveManifest", manifest);
        result.add("originalGraphChecker", original);
        JsonObject translation = new JsonObject();
        translation.addProperty("supplementalTypedIoDoors", supplementalDoors);
        translation.addProperty("methodParameterPortAnchors", parameterPortAnchors);
        translation.addProperty("methodReturnPortAnchors", returnPortAnchors);
        result.add("scopeTranslation", translation);
        JsonArray gaps = new JsonArray();
        for (String gap : analysisGaps) gaps.add(gap);
        result.add("analysisGaps", gaps);
        return result;
    }

    private Site exactSite(String id) {
        int cut = id.lastIndexOf("#u");
        if (cut <= 0) return null;
        Method method = methods.get(id.substring(0, cut));
        if (method == null) return null;
        try {
            int index = Integer.parseInt(id.substring(cut + 2));
            return index < 0 || index >= method.sites.size()
                    ? null : method.sites.get(index);
        } catch (NumberFormatException ignored) {
            return null;
        }
    }

    /** Map a wire catalog formal capture to its exact original Jimple identity. */
    private Site originalParameterSite(JsonObject capture) {
        Method method = methods.get(string(capture, "definitionMethod", ""));
        int parameter = integer(capture, "argumentIndex", -1);
        if (method == null || parameter < 0
                || parameter >= method.soot.getParameterCount()) return null;
        int index = originalParameterUnitIndex(method.body, parameter);
        return index < 0 ? null : method.sites.get(index);
    }

    /** Map a method-level wire return capture to every exact value-return unit. */
    private List<Site> originalReturnSites(JsonObject capture) {
        Method method = methods.get(string(capture, "definitionMethod", ""));
        if (method == null) return Collections.emptyList();
        List<Site> result = new ArrayList<>();
        for (int index : originalReturnUnitIndices(method.body,
                string(capture, "javaType", ""))) {
            result.add(method.sites.get(index));
        }
        return result;
    }

    static List<Integer> originalReturnUnitIndices(Body body, String javaType) {
        if (body == null || javaType.isEmpty()
                || !javaType.equals(body.getMethod().getReturnType().toString())) {
            return Collections.emptyList();
        }
        List<Integer> result = new ArrayList<>();
        int index = 0;
        for (Unit unit : body.getUnits()) {
            if (unit instanceof soot.jimple.ReturnStmt) result.add(index);
            index++;
        }
        return result;
    }

    static int originalParameterUnitIndex(Body body, int parameter) {
        if (parameter < 0) return -1;
        int index = 0;
        for (Unit unit : body.getUnits()) {
            if (!(unit instanceof IdentityStmt)) { index++; continue; }
            Value right = ((IdentityStmt) unit).getRightOp();
            if (right instanceof ParameterRef
                    && ((ParameterRef) right).getIndex() == parameter) return index;
            index++;
        }
        return -1;
    }

    /** GraphChecker declares the NEW's source line, while Mallory's oracle is THROW. */
    private int originalExceptionConstructionLine(Site thrown) {
        Method method = thrown.owner;
        method.flow();
        Value operand = ((ThrowStmt) thrown.unit).getOp();
        if (!(operand instanceof Local)) throw new IllegalStateException(
                "fatal throw has no local exception allocation: " + thrown.id);
        List<Unit> definitions = method.defs.getDefsOfAt((Local) operand, thrown.unit);
        List<Site> allocations = new ArrayList<>();
        for (Unit definition : definitions) {
            if (definition instanceof AssignStmt
                    && ((AssignStmt) definition).getRightOp() instanceof NewExpr) {
                allocations.add(method.site(definition));
            }
        }
        if (allocations.size() != 1 || allocations.get(0).line <= 0) {
            throw new IllegalStateException("GraphChecker needs one attributed NEW for "
                    + thrown.id + "; found " + allocations.size());
        }
        return allocations.get(0).line;
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
        if (matches.size() == 1) return matches.get(0);
        if (matches.size() > 1 && "BRANCH".equals(kind)
                && integer(spec, "throw_line", 0) > 0 && !exception.isEmpty()) {
            return resolveCompoundCheck(matches, spec);
        }
        throw new IllegalArgumentException("target must resolve to one site; found="
                + matches.size() + " class=" + clazz + " method=" + methodName
                + " line=" + lineStart + ".." + lineEnd + " kind=" + kind);
    }

    /**
     * A Java short-circuit check can have several branches on one source
     * line. The unique throw remains the GraphChecker demand seed, so its
     * guards are all retained in the backward closure. For runtime identity
     * choose the deepest guard that dominates that throw: every fatal path
     * executes it, and a healthy trace must still prove its nonfatal arm.
     * Parallel fatal paths, multiple throws, and missing dominance refuse.
     */
    private Site resolveCompoundCheck(List<Site> lineBranches, JsonObject spec) {
        Map<Site, List<Site>> byThrow = new LinkedHashMap<>();
        for (Site branch : lineBranches) {
            branch.owner.flow();
            for (Site candidate : branch.owner.sites) {
                if (!matchesFatalThrow(candidate, spec)) continue;
                Set<Unit> controls = transitiveGuards(candidate);
                if (controls.contains(branch.unit)) {
                    byThrow.computeIfAbsent(candidate, unused -> new ArrayList<>()).add(branch);
                }
            }
        }
        if (byThrow.size() != 1) throw new IllegalArgumentException(
                "compound target must control one exact fatal throw; found="
                        + byThrow.size());
        Map.Entry<Site, List<Site>> entry = byThrow.entrySet().iterator().next();
        Site thrown = entry.getKey();
        List<Site> controls = entry.getValue();
        if (controls.size() < 2) throw new IllegalArgumentException(
                "same-line branches do not form one compound fatal check: " + thrown.id);
        List<Unit> throwDominators = thrown.owner.dom.getDominators(thrown.unit);
        List<Unit> directGuards = thrown.owner.guardsOf(thrown.unit);
        List<Site> dominantControls = new ArrayList<>();
        for (Site check : controls) {
            if (throwDominators.contains(check.unit) && directGuards.contains(check.unit)) {
                dominantControls.add(check);
            }
        }
        List<Site> nearest = new ArrayList<>();
        for (Site check : dominantControls) {
            List<Unit> checkDominators = check.owner.dom.getDominators(check.unit);
            boolean belowAllOthers = true;
            for (Site other : dominantControls) {
                if (other != check && !checkDominators.contains(other.unit)) {
                    belowAllOthers = false;
                    break;
                }
            }
            if (belowAllOthers) nearest.add(check);
        }
        if (nearest.size() != 1) throw new IllegalArgumentException(
                "compound fatal check has no unique always-executed anchor; found="
                        + nearest.size() + " throw=" + thrown.id);
        controls.sort(Comparator.comparingInt(site -> site.index));
        compoundCheckSites.addAll(controls);
        return nearest.get(0);
    }

    private Set<Unit> transitiveGuards(Site site) {
        Set<Unit> controls = new LinkedHashSet<>();
        Deque<Unit> pending = new ArrayDeque<>(site.owner.guardsOf(site.unit));
        while (!pending.isEmpty()) {
            Unit guard = pending.removeFirst();
            if (controls.add(guard)) pending.addAll(site.owner.guardsOf(guard));
        }
        return controls;
    }

    private boolean matchesFatalThrow(Site candidate, JsonObject spec) {
        if (!(candidate.unit instanceof ThrowStmt)) return false;
        int throwLine = integer(spec, "throw_line", 0);
        if (throwLine > 0 && candidate.line != throwLine) return false;
        String exception = string(spec, "exception", string(spec, "exception_class", ""));
        String type = ((ThrowStmt) candidate.unit).getOp().getType().toString();
        return exception.isEmpty() || type.equals(exception)
                || type.endsWith("." + exception) || type.endsWith("$" + exception);
    }

    private void addCompoundCheckGroup(JsonObject result) {
        if (compoundCheckSites.isEmpty()) return;
        JsonArray controls = new JsonArray();
        for (Site check : compoundCheckSites) controls.add(check.id);
        result.add("targetCheckGroupSiteIds", controls);
    }

    private Site resolveControlledThrow(Site check, JsonObject spec) {
        String declaredId = string(spec, "site_id", "");
        List<Site> matches = new ArrayList<>();
        for (Site candidate : check.owner.sites) {
            if ((!declaredId.isEmpty() && !candidate.id.equals(declaredId))
                    || !matchesFatalThrow(candidate, spec)
                    || !(compoundCheckSites.isEmpty()
                         ? check.owner.guardsOf(candidate.unit).contains(check.unit)
                         : transitiveGuards(candidate).contains(check.unit))) continue;
            matches.add(candidate);
        }
        if (matches.size() == 1) return matches.get(0);
        if (matches.isEmpty()) {
            String exception = string(spec, "exception",
                    string(spec, "exception_class", ""));
            int throwLine = integer(spec, "throw_line", 0);
            if (!exception.isEmpty() && throwLine > 0) {
                List<Site> calls = new ArrayList<>();
                for (Site candidate : check.owner.sites) {
                    if ((declaredId.isEmpty() || candidate.id.equals(declaredId))
                            && candidate.line == throwLine
                            && candidate.unit instanceof Stmt
                            && ((Stmt) candidate.unit).containsInvokeExpr()
                            && callArgumentControlledBy(check, candidate)) {
                        calls.add(candidate);
                    }
                }
                if (calls.size() == 1) return calls.get(0);
                throw new IllegalArgumentException("check branch must influence one exact "
                        + "call-thrown exception; found=" + calls.size()
                        + " check=" + check.id + " call=" + declaredId
                        + " exception=" + exception);
            }
        }
        String exception = string(spec, "exception", string(spec, "exception_class", ""));
        int throwLine = integer(spec, "throw_line", 0);
        if (matches.size() > 1 || throwLine > 0) {
            throw new IllegalArgumentException("check branch must control one fatal throw; found="
                    + matches.size() + " check=" + check.id + " exception=" + exception
                    + " throw_line=" + throwLine);
        }
        analysisGaps.add("controlled_throw_unresolved:" + check.id + ":" + exception);
        return null;
    }

    /** A call can run on both arms while its boolean argument carries the check outcome. */
    private boolean callArgumentControlledBy(Site check, Site call) {
        Method method = call.owner;
        method.flow();
        Stmt stmt = (Stmt) call.unit;
        for (Value argument : stmt.getInvokeExpr().getArgs()) {
            if (argument.getType() instanceof soot.BooleanType
                    && valueControlledBy(method, argument, call.unit, check.unit,
                            new HashSet<String>())) return true;
        }
        return false;
    }

    private boolean valueControlledBy(Method method, Value value, Unit use,
                                      Unit check, Set<String> seen) {
        if (!(value instanceof Local)) return false;
        String key = method.indexOf(use) + ":" + value;
        if (!seen.add(key)) return false;
        for (Unit definition : method.defs.getDefsOfAt((Local) value, use)) {
            if (method.guardsOf(definition).contains(check)) return true;
            if (definition instanceof AssignStmt) {
                for (ValueBox input : ((AssignStmt) definition).getRightOp()
                        .getUseBoxes()) {
                    if (valueControlledBy(method, input.getValue(), definition,
                            check, seen)) return true;
                }
                if (valueControlledBy(method,
                        ((AssignStmt) definition).getRightOp(), definition,
                        check, seen)) return true;
            }
        }
        return false;
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
            // A referenced interface may still be DANGLING even when its jar
            // is present on Soot's classpath.  Hierarchy queries on that
            // placeholder throw instead of resolving it lazily.  If Soot
            // cannot resolve a parent, keep the class in the analysis: only
            // a proven protobuf ancestry justifies summarizing its body.
            try {
                next = Scene.v().forceResolve(name, SootClass.HIERARCHY);
                if (next == null || next.resolvingLevel() < SootClass.HIERARCHY
                        || next.isPhantom()) return false;
                if (next.hasSuperclass()) pending.add(next.getSuperclass());
                pending.addAll(next.getInterfaces());
            } catch (RuntimeException unresolved) {
                return false;
            }
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
        addCompoundCheckGroup(result);
        result.add("scopeSites", scope);
        result.add("weaveManifest", manifest);
        if (analysisConfig.has("graphchecker_region_port")
                && analysisConfig.get("graphchecker_region_port").getAsBoolean()) {
            result.add("graphCheckerRegionPort", graphCheckerRegionPort(
                    selectedMethods, manifest, rows));
        }
        JsonArray gaps = new JsonArray();
        for (String gap : analysisGaps) gaps.add(gap);
        result.add("analysisGaps", gaps);
        return result;
    }

    /**
     * Opt-in migration bridge. The source facts are selected Jimple units,
     * not reconstructed from a finished manifest. Their edge names and port
     * captures match GraphChecker's StaticProgram/SymbolicRegionPlanner input.
     * This branch never runs for the immutable ScopePlanner campaigns.
     */
    private JsonObject graphCheckerRegionPort(Set<Method> selectedMethods,
                                               JsonObject originalManifest,
                                               List<JsonObject> originalRows) {
        GraphCheckerRegionPlanner.Input facts = new GraphCheckerRegionPlanner.Input();
        String targetMethod = target.owner.soot.getSignature();
        facts.targetMethod = targetMethod;
        for (Method method : selectedMethods) {
            if (!materializedClasses.contains(method.soot.getDeclaringClass().getName())) continue;
            facts.selectedMethods.add(method.soot.getSignature());
            if (method.isCallback()) {
                facts.executionContextAuthorities.put(method.soot.getSignature(), "TASK_ENTRY");
            }
        }
        for (Site site : selected.values()) {
            String method = site.owner.soot.getSignature();
            if (!facts.selectedMethods.contains(method)) continue;
            Stmt stmt = (Stmt) site.unit;
            if (stmt instanceof AssignStmt) {
                Value left = ((AssignStmt) stmt).getLeftOp();
                Value right = ((AssignStmt) stmt).getRightOp();
                String leftCell = graphCheckerCell(method, left);
                if (right instanceof FieldRef) {
                    String field = ((FieldRef) right).getFieldRef().getSignature();
                    facts.edges.add(graphCheckerEdge(method, site.id, "HEAP_READ",
                            field, leftCell, ""));
                } else {
                    for (ValueBox used : right.getUseBoxes()) {
                        if (used.getValue() instanceof Local) facts.edges.add(
                                graphCheckerEdge(method, site.id, "LOCAL",
                                        graphCheckerCell(method, used.getValue()), leftCell, ""));
                    }
                    if (right instanceof Local) facts.edges.add(graphCheckerEdge(
                            method, site.id, "LOCAL", graphCheckerCell(method, right),
                            leftCell, ""));
                }
                if (left instanceof FieldRef) {
                    String field = ((FieldRef) left).getFieldRef().getSignature();
                    facts.edges.add(graphCheckerEdge(method, site.id, "HEAP_WRITE",
                            graphCheckerCell(method, right), field, ""));
                }
            }
            if (stmt.containsInvokeExpr()) {
                for (Method callee : resolveCallees(site)) {
                    if (facts.selectedMethods.contains(callee.soot.getSignature()))
                        facts.edges.add(graphCheckerEdge(method, site.id,
                                "CALL", "", "", callee.soot.getSignature()));
                }
            }
        }
        // GraphChecker's exception seed is a value node. Here the selected
        // controlling branch feeds that node with its Jimple condition uses.
        // We do not infer an outcome or a runtime field version from it.
        List<Site> controls = checkSites.isEmpty()
                ? Collections.singletonList(target) : checkSites;
        String failureCell = targetMethod + "#exception:"
                + string(object(config, "target"), "exception", "java.lang.Throwable");
        for (Site control : controls) {
            if (!facts.selectedMethods.contains(control.owner.soot.getSignature())) continue;
            if (control.unit.getUseBoxes().isEmpty()) facts.edges.add(graphCheckerEdge(
                    control.owner.soot.getSignature(), control.id, "CONTROL",
                    "", failureCell, ""));
            for (ValueBox used : control.unit.getUseBoxes()) {
                if (!(used.getValue() instanceof Local)) continue;
                facts.edges.add(graphCheckerEdge(control.owner.soot.getSignature(),
                        control.id, "CONTROL", graphCheckerCell(
                                control.owner.soot.getSignature(), used.getValue()),
                        failureCell, ""));
            }
        }
        for (String field : selectedFields) {
            soot.SootField resolved = Scene.v().grabField(field);
            if (resolved != null && resolved.isStatic() && resolved.isFinal())
                facts.constantFields.add(field);
        }
        for (Port port : ports) {
            Map<String, Object> flow = new LinkedHashMap<>();
            flow.put("portId", port.id);
            flow.put("name", port.id);
            flow.put("exchangeSiteKey", port.id);
            flow.put("transport", port.transport);
            List<Map<String, Object>> producers = new ArrayList<>();
            List<Map<String, Object>> consumers = new ArrayList<>();
            for (Site site : port.producers) {
                if (facts.selectedMethods.contains(site.owner.soot.getSignature()))
                    producers.add(graphCheckerCapture(site, "CALL_ARGUMENT"));
            }
            for (Site site : port.consumers) {
                if (facts.selectedMethods.contains(site.owner.soot.getSignature()))
                    consumers.add(graphCheckerCapture(site, "CALL_RETURN"));
            }
            flow.put("producers", producers);
            flow.put("consumers", consumers);
            if (!producers.isEmpty() || !consumers.isEmpty())
                facts.communicationCallSites.add(flow);
        }
        GraphCheckerRegionPlanner.Result planned = GraphCheckerRegionPlanner.plan(facts);
        JsonObject out = new JsonObject();
        JsonObject factRows = new JsonObject();
        factRows.add("selectedMethods", JSON.toJsonTree(facts.selectedMethods));
        factRows.add("edges", JSON.toJsonTree(facts.edges));
        factRows.add("executionContextAuthorities",
                JSON.toJsonTree(facts.executionContextAuthorities));
        factRows.add("communicationCallSites",
                JSON.toJsonTree(facts.communicationCallSites));
        factRows.add("constantFields", JSON.toJsonTree(facts.constantFields));
        factRows.addProperty("targetMethod", facts.targetMethod);
        out.add("facts", factRows);
        out.add("regions", JSON.toJsonTree(planned.regions));
        out.add("gaps", JSON.toJsonTree(planned.gaps));
        JsonArray portScopeRows = new JsonArray();
        for (JsonObject row : originalRows) {
            String siteId = string(row, "siteId", "");
            int unit = siteId.lastIndexOf("#u");
            if (unit < 0) continue;
            for (String regionId : planned.regionsHolding(siteId.substring(0, unit))) {
                JsonObject owned = row.deepCopy();
                owned.addProperty("regionId", regionId);
                portScopeRows.add(owned);
            }
        }
        out.add("staticScopeSites", portScopeRows);
        out.add("weaveManifest", graphCheckerWeaveManifest(planned,
                originalManifest));
        return out;
    }

    private static String graphCheckerCell(String method, Value value) {
        return method + "::" + value;
    }

    private static Map<String, Object> graphCheckerEdge(String method,
            String siteId, String transfer, String from, String to, String invoke) {
        Map<String, Object> edge = new LinkedHashMap<>();
        edge.put("method", method);
        edge.put("siteId", siteId);
        edge.put("transferKind", transfer);
        edge.put("fromCell", from);
        edge.put("toCell", to);
        if (!invoke.isEmpty()) edge.put("invoke", invoke);
        return edge;
    }

    private static Map<String, Object> graphCheckerCapture(Site site, String kind) {
        Map<String, Object> capture = new LinkedHashMap<>();
        capture.put("definitionMethod", site.owner.soot.getSignature());
        capture.put("callSiteId", site.id);
        capture.put("definitionUnitIndex", site.index);
        capture.put("outputCaptureKind", kind);
        return capture;
    }

    private JsonObject graphCheckerWeaveManifest(GraphCheckerRegionPlanner.Result planned,
                                                 JsonObject original) {
        JsonObject out = new JsonObject();
        for (String key : Arrays.asList("schemaVersion", "caseId",
                "sootDependencyClasspathSha256")) out.add(key, original.get(key));
        Set<String> held = planned.instrumentedMethods();
        Set<String> refKeys = new HashSet<>();
        JsonArray roots = new JsonArray();
        JsonArray frames = new JsonArray();
        for (String signature : held) {
            Method method = methods.get(signature);
            if (method == null || !materializedClasses.contains(
                    method.soot.getDeclaringClass().getName())) continue;
            frames.add(methodRef(method));
            refKeys.add(graphCheckerMethodKey(method));
        }
        for (Map<String, Object> region : planned.regions) {
            Method method = methods.get(String.valueOf(region.get("rootMethod")));
            if (method == null || !materializedClasses.contains(
                    method.soot.getDeclaringClass().getName())) continue;
            JsonObject root = methodRef(method);
            root.addProperty("regionId", String.valueOf(region.get("regionId")));
            root.addProperty("sourceOwner", sourceOwner(method));
            roots.add(root);
        }
        out.add("regions", roots);
        out.add("frames", frames);
        for (String family : Arrays.asList("coverage", "doors", "stateCandidates")) {
            JsonArray chosen = new JsonArray();
            for (JsonElement value : original.getAsJsonArray(family)) {
                JsonObject row = value.getAsJsonObject();
                if (refKeys.contains(graphCheckerMethodKey(row))) chosen.add(row.deepCopy());
            }
            out.add(family, chosen);
        }
        out.add("targets", original.getAsJsonArray("targets").deepCopy());
        JsonArray selectedPorts = new JsonArray();
        for (JsonElement value : original.getAsJsonArray("rpcPorts")) {
            JsonObject port = value.getAsJsonObject().deepCopy();
            JsonArray exports = new JsonArray();
            JsonArray imports = new JsonArray();
            for (JsonElement site : port.getAsJsonArray("exports")) {
                String siteId = site.getAsString();
                int unit = siteId.lastIndexOf("#u");
                if (unit >= 0 && held.contains(siteId.substring(0, unit))) exports.add(site);
            }
            for (JsonElement site : port.getAsJsonArray("imports")) {
                String siteId = site.getAsString();
                int unit = siteId.lastIndexOf("#u");
                if (unit >= 0 && held.contains(siteId.substring(0, unit))) imports.add(site);
            }
            if (exports.size() == 0 && imports.size() == 0) continue;
            port.add("exports", exports);
            port.add("imports", imports);
            selectedPorts.add(port);
        }
        out.add("rpcPorts", selectedPorts);
        return out;
    }

    private static String graphCheckerMethodKey(Method method) {
        return method.soot.getDeclaringClass().getName() + "#"
                + method.soot.getName() + "#" + descriptor(method.soot);
    }

    private static String graphCheckerMethodKey(JsonObject row) {
        return string(row, "clazz", "") + "#" + string(row, "method", "")
                + "#" + string(row, "descriptor", "");
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

    private static void addOriginal(List<JsonObject> rows, Set<String> seen, JsonObject row) {
        String key = string(row, "regionId", "") + "|" + string(row, "role", "")
                + "|" + string(row, "siteId", "") + "|" + string(row, "cell", "")
                + "|" + string(row, "portId", "");
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
                Site oracle = fatalThrow;
                ref.addProperty("kind", oracle.unit instanceof ThrowStmt
                        ? "THROW" : "CALL_THROW");
                ref.addProperty("exceptionClass", oracle.unit instanceof ThrowStmt
                        ? ((ThrowStmt) oracle.unit).getOp().getType().toString()
                        : string(object(config, "target"), "exception", ""));
                if (!(oracle.unit instanceof ThrowStmt)) ref.addProperty("callee",
                        ((Stmt) oracle.unit).getInvokeExpr().getMethodRef()
                                .getSignature());
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
