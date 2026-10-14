package edu.uva.liftlab.graphchecker.causynth;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import edu.uva.liftlab.graphchecker.contract.Clock;
import edu.uva.liftlab.graphchecker.plan.ScopeFrontier;
import edu.uva.liftlab.graphchecker.plan.StaticScopeMap;
import edu.uva.liftlab.graphchecker.plan.SiteId;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Predicate;

/**
 * Opt-in bridge executed inside Mallory's already loaded Soot Scene.
 *
 * Provenance: this class calls the ORIGINAL GraphChecker implementation at
 * revision c4a90033c654737206466ed36ce837c5b3c12457. Its analysis
 * sequence is CausynthPipeline.analyze(), lines 165-225. Only target-spec
 * adaptation and JSON export are new Mallory code. The original engine JAR
 * must be supplied explicitly; the default Mallory build never loads it.
 */
public final class MalloryOriginalSeedBridge {
    private MalloryOriginalSeedBridge() { }

    public static JsonObject analyze(List<String> processDirs, Path outputDir,
                                     String targetClass, int throwLine,
                                     String exceptionClass) throws IOException {
        Files.createDirectories(outputDir);
        Path spec = outputDir.resolve("original_graphchecker_target.spec");
        String target = "exception_target: mallory " + targetClass + " "
                + throwLine + " " + exceptionClass + "\n";
        Files.write(spec, target.getBytes(StandardCharsets.UTF_8));
        String oldSpec = System.getProperty("causynth.target.spec");
        String oldOut = System.getProperty("causynth.output.dir");
        String oldRoots = System.getProperty(LibraryReceivers.ROOTS);
        try {
            System.setProperty("causynth.target.spec", spec.toString());
            System.setProperty("causynth.output.dir", outputDir.toString());
            System.setProperty(LibraryReceivers.ROOTS,
                    String.join(java.io.File.pathSeparator, processDirs));
            CausynthTargetContext targetContext =
                    CausynthTargetResolver.resolve(processDirs);
            return analyzeResolved(processDirs, outputDir, targetContext);
        } finally {
            restore("causynth.target.spec", oldSpec);
            restore("causynth.output.dir", oldOut);
            restore(LibraryReceivers.ROOTS, oldRoots);
        }
    }

    /** Seed an exact caller invocation whose callee may raise the declared exception. */
    public static JsonObject analyzeCallThrow(List<String> processDirs, Path outputDir,
                                              String methodSignature, int callUnitIndex,
                                              String calledMethod, String exceptionClass)
            throws IOException {
        Files.createDirectories(outputDir);
        soot.SootMethod owner = soot.Scene.v().getMethod(methodSignature);
        soot.Body body = owner.retrieveActiveBody();
        soot.Unit[] units = body.getUnits().toArray(new soot.Unit[0]);
        if (callUnitIndex < 0 || callUnitIndex >= units.length
                || !(units[callUnitIndex] instanceof soot.jimple.Stmt)
                || !((soot.jimple.Stmt) units[callUnitIndex]).containsInvokeExpr()
                || !calledMethod.equals(((soot.jimple.Stmt) units[callUnitIndex])
                        .getInvokeExpr().getMethodRef().getSignature())
                || exceptionClass == null || exceptionClass.isEmpty()) {
            throw new IllegalArgumentException("call-thrown target has no exact invocation: "
                    + methodSignature + "#u" + callUnitIndex + " " + calledMethod);
        }
        ExceptionTargetSite site = new ExceptionTargetSite("mallory", owner,
                callUnitIndex, calledMethod, exceptionClass);
        String oldOut = System.getProperty("causynth.output.dir");
        String oldRoots = System.getProperty(LibraryReceivers.ROOTS);
        try {
            System.setProperty("causynth.output.dir", outputDir.toString());
            System.setProperty(LibraryReceivers.ROOTS,
                    String.join(java.io.File.pathSeparator, processDirs));
            return analyzeResolved(processDirs, outputDir,
                    new CausynthTargetContext(outputDir, site));
        } finally {
            restore("causynth.output.dir", oldOut);
            restore(LibraryReceivers.ROOTS, oldRoots);
        }
    }

    private static JsonObject analyzeResolved(List<String> processDirs, Path outputDir,
                                              CausynthTargetContext targetContext)
            throws IOException {
            soot.SootMethod targetMethod = soot.Scene.v().getMethod(
                    targetContext.exceptionTargetSite.methodSignature);
            StringBuilder targetBody = new StringBuilder();
            int bodyIndex = 0;
            for (soot.Unit unit : targetMethod.retrieveActiveBody().getUnits()) {
                targetBody.append(bodyIndex++).append(' ')
                        .append(unit.getJavaSourceStartLineNumber()).append(' ')
                        .append(unit).append('\n');
            }
            Files.write(outputDir.resolve("original_target_jimple.txt"),
                    targetBody.toString().getBytes(StandardCharsets.UTF_8));
            StaticProgram result = new SeedBackwardStaticAnalyzer(
                    targetContext).analyze();
            List<DemandedDoors.Site> woven = DemandedDoors.woven();
            SymbolicRegionPlanner.planSelectedSkeleton(result,
                    result.traceMethods, woven);
            Map<String, Clock> clocks = RootCatalog.clocks(result.edges);
            ConfigRoots recognized = ConfigRoots.of(result.edges,
                    result.fieldWriters);
            Predicate<String> systemClass = LibraryReceivers.systemClasses(
                    System.getProperty(LibraryReceivers.ROOTS));
            RootDemand demand = RootDemand.of(result.edges, result.regions,
                    clocks, recognized,
                    targetPathSites(result.edges,
                            result.executionContextAuthorities::containsKey),
                    CausynthStaticFacts::trackedKind, systemClass,
                    new LatentFaults(systemClass,
                            method -> !result.regionsHolding(method).isEmpty()),
                    woven);
            ConfigRoots config = recognized.limitedTo(demand.configSources());
            Set<String> configReads = StaticSymbolicSourceDiscovery.discover(
                    result, config);
            List<StaticScopeMap.Site> sites = StaticScopeMap.sites(
                    result.edges, result.regions, clocks,
                    (method, unitIndex, callee) -> {
                        ConfigRoots.Source source = config.call(method,
                                unitIndex, callee);
                        return source == null ? null
                                : new StaticScopeMap.ConfigCall(source.sourceId,
                                        source.domainMin, source.domainMax);
                    }, demand.marks(),
                    method -> !CausynthStaticFacts.applicationMethod(method),
                    CausynthStaticFacts::trackedKind,
                    CausynthStaticFacts::staticField,
                    CausynthStaticFacts::constructionOnly);
            List<JsonObject> scope = StaticScopeMap.rows(sites,
                    SiteControlDependence.over(StaticScopeMap.siteIds(sites)),
                    result.executionContextAuthorities::containsKey);
            scope.addAll(recognized.keyRows(demand.configSources(),
                    configReads));
            Set<String> rootCallees = new LinkedHashSet<>(clocks.keySet());
            rootCallees.addAll(recognized.callees());
            List<JsonObject> frontier = ScopeFrontier.rows(result.edges,
                    CausynthStaticFacts::analysedMethod, rootCallees,
                    demand.frontier());
            CausynthArtifactWriter.writeDiscoveryArtifacts(outputDir, result,
                    scope, frontier, demand.rows());
            DemandedDoors.write(outputDir.resolve(DemandedDoors.FILE),
                    demand.doors());

            JsonObject exported = new JsonObject();
            exported.addProperty("engine", "original_graphchecker_seed_backward");
            exported.addProperty("graphCheckerRevision",
                    "c4a90033c654737206466ed36ce837c5b3c12457");
            exported.add("targetResolved", GraphCheckerJson.toTree(
                    result.targetResolved));
            exported.add("traceMethods", GraphCheckerJson.toTree(
                    result.traceMethods));
            // Discovery artifacts already preserve the graph; ScopePlanner
            // does not consume an in-memory copy of every edge.
            exported.add("regions", GraphCheckerJson.toTree(result.regions));
            exported.add("communicationCallSites", GraphCheckerJson.toTree(
                    result.communicationCallSites));
            exported.add("communicationGaps", GraphCheckerJson.toTree(
                    result.communicationGaps));
            exported.add("staticScopeSites", GraphCheckerJson.toTree(scope));
            exported.add("rootDemand", GraphCheckerJson.toTree(demand.rows()));
            JsonArray doors = new JsonArray();
            LatentFaults sitesForDoors = new LatentFaults(systemClass,
                    method -> !result.regionsHolding(method).isEmpty());
            for (DemandedDoors.Site door : demand.doors()) {
                JsonObject row = door.row();
                row.addProperty("siteId", sitesForDoors.site(door));
                doors.add(row);
            }
            exported.add("demandedDoors", doors);
            return exported;
    }

    private static void restore(String name, String prior) {
        if (prior == null) System.clearProperty(name);
        else System.setProperty(name, prior);
    }

    /** Direct transcription of CausynthPipeline.targetPathSites. */
    private static Set<String> targetPathSites(List<Map<String, Object>> edges,
                                                Predicate<String> entry) {
        Set<String> sites = new LinkedHashSet<>();
        for (Map<String, Object> edge : edges) {
            if (!"exception_throw".equals(MapFields.text(edge.get("kind"))))
                continue;
            String target = SiteId.of(MapFields.text(edge.get("method")),
                    MapFields.number(edge.get("unitIndex"), -1));
            StaticScopeMap.Guards control = SiteControlDependence.over(
                    Collections.singleton(target));
            for (StaticScopeMap.Guard guard : control.of(target))
                sites.add(guard.siteId());
            for (StaticScopeMap.Guard guard : StaticScopeMap.targetChain(
                    control, target, entry)) sites.add(guard.siteId());
            sites.addAll(StaticScopeMap.Guard.decidingSites(
                    control.chainOf(target)));
        }
        return sites;
    }

    private static final class GraphCheckerJson {
        private static final com.google.gson.Gson GSON = new com.google.gson.Gson();
        static com.google.gson.JsonElement toTree(Object value) {
            return GSON.toJsonTree(value);
        }
    }
}
