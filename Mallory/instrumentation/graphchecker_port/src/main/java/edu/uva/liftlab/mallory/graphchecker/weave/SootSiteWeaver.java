package edu.uva.liftlab.mallory.graphchecker.weave;

import java.util.ArrayList;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.regex.Pattern;
import soot.ArrayType;
import soot.Body;
import soot.BodyTransformer;
import soot.Local;
import soot.PrimType;
import soot.RefType;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.SootMethodRef;
import soot.Trap;
import soot.Type;
import soot.Unit;
import soot.Value;
import soot.VoidType;
import soot.jimple.IdentityStmt;
import soot.jimple.InvokeExpr;
import soot.jimple.IfStmt;
import soot.jimple.IntConstant;
import soot.jimple.Jimple;
import soot.jimple.NullConstant;
import soot.jimple.ReturnStmt;
import soot.jimple.ReturnVoidStmt;
import soot.jimple.Stmt;
import soot.jimple.StringConstant;
import soot.jimple.SwitchStmt;
import soot.jimple.LookupSwitchStmt;
import soot.jimple.TableSwitchStmt;
import soot.jimple.ThrowStmt;
import soot.toolkits.exceptions.UnitThrowAnalysis;

/**
 * Focused Soot rewrite of GraphChecker's selected region/branch/throw hooks.
 * It refuses unmatched declared sites instead of silently producing a trace
 * that appears to cover them.
 */
public final class SootSiteWeaver extends BodyTransformer {
    private static final String HOOK = TraceHooks.class.getName();
    // Soot numbers invokedynamic lambda bootstrap classes in global discovery
    // order. That counter can change across otherwise identical Soot runs.
    private static final Pattern SOOT_LAMBDA_SUFFIX = Pattern.compile(
            "(\\$lambda_[A-Za-z0-9_$]*__)\\d+(?=:)");
    private final SiteManifest manifest;
    private final AtomicInteger matchedRegions = new AtomicInteger();
    private final AtomicInteger matchedTargets = new AtomicInteger();
    private final AtomicInteger matchedCoverage = new AtomicInteger();
    private final AtomicInteger matchedFrames = new AtomicInteger();
    private final AtomicInteger matchedDoors = new AtomicInteger();
    private final AtomicInteger matchedStateCandidates = new AtomicInteger();

    public SootSiteWeaver(SiteManifest manifest) { this.manifest = manifest; }

    public void verifyAllSites() {
        if (matchedRegions.get() != manifest.regions.size()
                || matchedTargets.get() != manifest.targets.size()
                || matchedCoverage.get() != manifest.coverage.size()
                || matchedFrames.get() != manifest.frames.size()
                || matchedDoors.get() != manifest.doors.size()
                || matchedStateCandidates.get() != manifest.stateCandidates.size()) {
            throw new IllegalStateException("site mismatch: region "
                    + matchedRegions + "/" + manifest.regions.size()
                    + ", target " + matchedTargets + "/" + manifest.targets.size()
                    + ", coverage " + matchedCoverage + "/"
                    + manifest.coverage.size() + ", frames "
                    + matchedFrames + "/" + manifest.frames.size()
                    + ", doors " + matchedDoors + "/" + manifest.doors.size()
                    + ", stateCandidates " + matchedStateCandidates + "/"
                    + manifest.stateCandidates.size());
        }
    }

    @Override protected void internalTransform(Body body, String phase,
                                                java.util.Map<String, String> options) {
        SootMethod method = body.getMethod();
        normalizeApplicationTraps(body, method);
        String className = method.getDeclaringClass().getName();
        String descriptor = descriptor(method);
        List<SiteManifest.Region> regions = new ArrayList<>();
        List<SiteManifest.Target> targets = new ArrayList<>();
        List<SiteManifest.Coverage> coverage = new ArrayList<>();
        List<SiteManifest.Frames> frames = new ArrayList<>();
        List<SiteManifest.Door> doors = new ArrayList<>();
        List<SiteManifest.StateCandidate> stateCandidates = new ArrayList<>();
        for (SiteManifest.Region site : manifest.regions) {
            if (site.matches(className, method.getName(), descriptor)) regions.add(site);
        }
        for (SiteManifest.Target site : manifest.targets) {
            if (site.matches(className, method.getName(), descriptor)) targets.add(site);
        }
        for (SiteManifest.Coverage site : manifest.coverage) {
            if (site.matches(className, method.getName(), descriptor)) coverage.add(site);
        }
        for (SiteManifest.Frames site : manifest.frames) {
            if (site.matches(className, method.getName(), descriptor)) frames.add(site);
        }
        for (SiteManifest.Door site : manifest.doors) {
            if (site.matches(className, method.getName(), descriptor)) doors.add(site);
        }
        for (SiteManifest.StateCandidate site : manifest.stateCandidates) {
            if (site.matches(className, method.getName(), descriptor)) stateCandidates.add(site);
        }
        if (regions.isEmpty() && targets.isEmpty() && coverage.isEmpty()
                && frames.isEmpty() && doors.isEmpty() && stateCandidates.isEmpty()) return;
        if (regions.size() > 1) throw new IllegalArgumentException(
                "more than one region on " + method.getSignature());
        Unit entry = safeEntry(body, method);
        if (entry == null) throw new IllegalArgumentException(
                "no safe entry for " + method.getSignature());
        // The selected method's `this` is not automatically a registered
        // node. A null owner asks MessageDoors for the current request or
        // transported scope; an unclaimed background thread remains a GAP.
        SiteManifest.Region selectedRegion = regions.isEmpty() ? null : regions.get(0);
        Value receiver = selectedRegion != null
                && "THIS".equals(selectedRegion.sourceOwner)
                && !method.isStatic() ? body.getThisLocal() : NullConstant.v();

        // First rewrite sites against the original unit array. The branch's
        // taken arm gets its own trampoline so shared successor labels do not
        // make a branch outcome appear on another predecessor's path.
        Unit[] original = body.getUnits().toArray(new Unit[0]);
        java.util.Map<Unit, Integer> originalPositions = new java.util.IdentityHashMap<>();
        for (int i = 0; i < original.length; i++) originalPositions.put(original[i], i);
        final int entryIndex = originalPositions.get(entry);
        java.util.List<TrapSnapshot> applicationTraps = new ArrayList<>();
        for (Trap trap : body.getTraps()) {
            applicationTraps.add(new TrapSnapshot(trap,
                    originalPositions.get(trap.getBeginUnit()),
                    originalPositions.get(trap.getEndUnit())));
        }
        // Open the selected region before any selected hook or call-frame
        // hook at the method entry. Inserting this after call frames made the
        // first enterCall execute outside the region and corrupted the path.
        SiteManifest.Region region = selectedRegion;
        Unit regionOpen = null;
        if (region != null) {
            Value regionOwner = NullConstant.v();
            if ("THIS".equals(region.sourceOwner)) {
                if (method.isStatic()) throw new IllegalArgumentException(
                        "THIS source owner on static region " + method.getSignature());
                regionOwner = body.getThisLocal();
            }
            regionOpen = Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                    ref("regionOpen", VoidType.v(), RefType.v("java.lang.String"),
                            RefType.v("java.lang.String"), RefType.v("java.lang.Object")),
                    StringConstant.v(region.regionId),
                    StringConstant.v(method.getSignature()), regionOwner));
            body.getUnits().insertBeforeNoRedirect(regionOpen, entry);
            for (Unit unit : original) {
                if (unit instanceof ReturnStmt || unit instanceof ReturnVoidStmt) {
                    body.getUnits().insertBefore(
                            Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                                    ref("regionClose", VoidType.v(),
                                            RefType.v("java.lang.String")),
                                    StringConstant.v(region.regionId))), unit);
                }
            }
            matchedRegions.incrementAndGet();
        }
        java.util.Map<Unit, Unit> doorStarts = new java.util.IdentityHashMap<>();
        for (SiteManifest.Door door : doors) {
            int matches = 0;
            for (Unit unit : original) {
                if (!(unit instanceof Stmt) || !((Stmt) unit).containsInvokeExpr()
                        || unit.getJavaSourceStartLineNumber() != door.line
                        || (door.unitIndex != null
                            && !door.unitIndex.equals(originalPositions.get(unit)))
                        || !sameCallee(((Stmt) unit).getInvokeExpr()
                                .getMethodRef().getSignature(), door.callee)) continue;
                boolean preInit = method.isConstructor()
                        && originalPositions.get(unit) < entryIndex;
                Unit hit = preInit ? preInitGap(door.siteId, "DOOR")
                        : Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                                ref("faultDoor", VoidType.v(), RefType.v("java.lang.String"),
                                        RefType.v("java.lang.Object"),
                                        RefType.v("java.lang.String"), soot.IntType.v()),
                                StringConstant.v(door.siteId), receiver,
                                StringConstant.v(door.exceptionClass == null
                                        ? "java.io.IOException" : door.exceptionClass),
                                IntConstant.v("MALLORY_PROBE".equals(manifest.faultController) ? 1
                                        : "MALLORY_GC_FAULT_PLAN".equals(manifest.faultController) ? 2 : 0)));
                body.getUnits().insertBefore(hit, unit);
                if (!preInit) doorStarts.put(unit, hit);
                matches++;
            }
            if (matches != 1) throw new IllegalArgumentException(
                    "door " + door.siteId + " resolved to " + matches
                            + " units in " + method.getSignature());
            matchedDoors.incrementAndGet();
        }
        for (SiteManifest.StateCandidate state : stateCandidates) {
            int matches = 0;
            for (Unit unit : original) {
                if (unit.getJavaSourceStartLineNumber() != state.line
                        || !state.unitIndex.equals(originalPositions.get(unit))) continue;
                Unit gap = Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                        ref("stateAccessGap", VoidType.v(), RefType.v("java.lang.String"),
                                RefType.v("java.lang.String"), RefType.v("java.lang.String")),
                        StringConstant.v(state.siteId), StringConstant.v(state.access),
                        StringConstant.v(state.field)));
                body.getUnits().insertBefore(gap, unit);
                matches++;
            }
            if (matches != 1) throw new IllegalArgumentException(
                    "state candidate " + state.siteId + " resolved to " + matches
                            + " units in " + method.getSignature());
            matchedStateCandidates.incrementAndGet();
        }
        if (!frames.isEmpty()) {
            if (frames.size() != 1) throw new IllegalArgumentException(
                    "duplicate frame selection " + method.getSignature());
            weaveCallFrames(body, method, original, entry,
                    originalPositions, applicationTraps, doorStarts);
            matchedFrames.incrementAndGet();
        }
        for (SiteManifest.Target target : targets) {
            int matches = 0;
            for (Unit unit : original) {
                if (unit.getJavaSourceStartLineNumber() != target.line) continue;
                if (target.unitIndex != null
                        && !target.unitIndex.equals(originalPositions.get(unit))) continue;
                if ("BRANCH".equals(target.kind) && unit instanceof IfStmt) {
                    if (method.isConstructor() && originalPositions.get(unit) < entryIndex)
                        body.getUnits().insertBefore(preInitGap(target.siteId, "TARGET"), unit);
                    else weaveBranch(body, (IfStmt) unit, target.siteId, receiver);
                    matches++;
                } else if ("SWITCH".equals(target.kind)
                        && unit instanceof SwitchStmt) {
                    if (method.isConstructor() && originalPositions.get(unit) < entryIndex)
                        body.getUnits().insertBefore(preInitGap(target.siteId, "TARGET"), unit);
                    else weaveSwitch(body, (SwitchStmt) unit, target.siteId, receiver);
                    matches++;
                } else if ("THROW".equals(target.kind) && unit instanceof ThrowStmt) {
                    if (method.isConstructor() && originalPositions.get(unit) < entryIndex)
                        body.getUnits().insertBefore(preInitGap(target.siteId, "TARGET"), unit);
                    else weaveThrow(body, (ThrowStmt) unit, target, receiver);
                    matches++;
                }
            }
            if (matches != 1) throw new IllegalArgumentException(
                    "target " + target.siteId + " resolved to " + matches
                            + " units in " + method.getSignature());
            matchedTargets.incrementAndGet();
        }

        for (SiteManifest.Coverage site : coverage) {
            if (site.line <= 0 && site.unitIndex == null) {
                body.getUnits().insertBeforeNoRedirect(coverage(site.siteId, receiver), entry);
                matchedCoverage.incrementAndGet();
                continue;
            }
            int matches = 0;
            for (Unit unit : original) {
                if (site.line > 0 && unit.getJavaSourceStartLineNumber() != site.line) continue;
                if (site.unitIndex != null
                        && !site.unitIndex.equals(originalPositions.get(unit))) continue;
                if (unit instanceof IfStmt) {
                    if (method.isConstructor() && originalPositions.get(unit) < entryIndex)
                        body.getUnits().insertBefore(preInitGap(site.siteId, "COVERAGE"), unit);
                    else weaveCoverageBranch(body, (IfStmt) unit, site.siteId, receiver);
                    matches++;
                } else if (unit instanceof SwitchStmt) {
                    if (method.isConstructor() && originalPositions.get(unit) < entryIndex)
                        body.getUnits().insertBefore(preInitGap(site.siteId, "COVERAGE"), unit);
                    else weaveCoverageSwitch(body, (SwitchStmt) unit, site.siteId, receiver);
                    matches++;
                }
            }
            if (matches != 1) throw new IllegalArgumentException(
                    "coverage " + site.siteId + " resolved to " + matches
                            + " branch units in " + method.getSignature());
            matchedCoverage.incrementAndGet();
        }
        if (region != null) {
            // Include all hooks inserted at the entry in the exceptional
            // range, while excluding regionOpen itself.
            appendRegionHandler(body, body.getUnits().getSuccOf(regionOpen),
                    region.regionId);
        }
        body.validate();
    }

    /**
     * Soot can widen an original typed catch to include arithmetic/local
     * assignments before the first operation capable of throwing that type.
     * Its StackMap writer then merges an uninitialized local into the catch
     * frame, even though the original JVM table started after initialization.
     * Removing only non-catching prefix/suffix units preserves the catch's
     * behavior and keeps the original handler's live locals verifiable.
     */
    private static void normalizeApplicationTraps(Body body, SootMethod method) {
        for (Trap trap : body.getTraps()) {
            RefType catchType = trap.getException().getType();
            Unit first = null;
            Unit last = null;
            for (Unit unit = trap.getBeginUnit(); unit != null
                    && unit != trap.getEndUnit(); unit = body.getUnits().getSuccOf(unit)) {
                if (UnitThrowAnalysis.v().mightThrow(unit, method)
                        .catchableAs(catchType)) {
                    if (first == null) first = unit;
                    last = unit;
                }
            }
            if (first == null) continue;
            if (first != trap.getBeginUnit()) trap.setBeginUnit(first);
            Unit afterLast = body.getUnits().getSuccOf(last);
            if (afterLast != null && afterLast != trap.getEndUnit())
                trap.setEndUnit(afterLast);
        }
    }

    static boolean sameCallee(String actual, String selected) {
        if (actual.equals(selected)) return true;
        return SOOT_LAMBDA_SUFFIX.matcher(actual).replaceAll("$1*")
                .equals(SOOT_LAMBDA_SUFFIX.matcher(selected).replaceAll("$1*"));
    }

    private static Unit preInitGap(String siteId, String kind) {
        return Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                ref("preInitGap", VoidType.v(), RefType.v("java.lang.String"),
                        RefType.v("java.lang.String")),
                StringConstant.v(siteId), StringConstant.v(kind)));
    }

    private static void weaveBranch(Body body, IfStmt branch, String siteId,
                                    Value receiver) {
        Unit originalTarget = branch.getTarget();
        Unit trueEntry = Jimple.v().newNopStmt();
        body.getUnits().add(trueEntry);
        body.getUnits().add(check(siteId, receiver, "TRUE"));
        body.getUnits().add(Jimple.v().newGotoStmt(originalTarget));
        branch.setTarget(trueEntry);
        body.getUnits().insertAfter(check(siteId, receiver, "FALSE"), branch);
    }

    private static Unit check(String siteId, Value receiver, String outcome) {
        return Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                ref("targetCheck", VoidType.v(), RefType.v("java.lang.String"),
                        RefType.v("java.lang.Object"), RefType.v("java.lang.String")),
                StringConstant.v(siteId), receiver, StringConstant.v(outcome)));
    }

    private static Unit coverage(String siteId, Value receiver) {
        return Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                ref("coverage", VoidType.v(), RefType.v("java.lang.String"),
                        RefType.v("java.lang.Object")),
                StringConstant.v(siteId), receiver));
    }

    private static void weaveCoverageBranch(Body body, IfStmt branch,
                                             String siteId, Value receiver) {
        Unit originalTarget = branch.getTarget();
        Unit trueEntry = Jimple.v().newNopStmt();
        body.getUnits().add(trueEntry);
        body.getUnits().add(coveredBranch(siteId, receiver, true));
        body.getUnits().add(Jimple.v().newGotoStmt(originalTarget));
        branch.setTarget(trueEntry);
        body.getUnits().insertAfter(coveredBranch(siteId, receiver, false), branch);
    }

    private static Unit coveredBranch(String siteId, Value receiver, boolean outcome) {
        return Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                ref("branch", VoidType.v(), RefType.v("java.lang.String"),
                        RefType.v("java.lang.Object"), soot.BooleanType.v()),
                StringConstant.v(siteId), receiver, IntConstant.v(outcome ? 1 : 0)));
    }

    private static void weaveCoverageSwitch(Body body, SwitchStmt branch,
                                             String siteId, Value receiver) {
        for (int index = 0; index < branch.getTargets().size(); index++) {
            Unit original = branch.getTarget(index);
            String value = branch instanceof LookupSwitchStmt
                    ? String.valueOf(((LookupSwitchStmt) branch).getLookupValue(index))
                    : String.valueOf(((TableSwitchStmt) branch).getLowIndex() + index);
            Unit entry = Jimple.v().newNopStmt();
            body.getUnits().add(entry);
            body.getUnits().add(coverage(siteId + "/CASE:" + value, receiver));
            body.getUnits().add(Jimple.v().newGotoStmt(original));
            branch.setTarget(index, entry);
        }
        Unit fallback = branch.getDefaultTarget();
        Unit defaultEntry = Jimple.v().newNopStmt();
        body.getUnits().add(defaultEntry);
        body.getUnits().add(coverage(siteId + "/DEFAULT", receiver));
        body.getUnits().add(Jimple.v().newGotoStmt(fallback));
        branch.setDefaultTarget(defaultEntry);
    }

    private static void weaveSwitch(Body body, SwitchStmt branch,
                                    String siteId, Value receiver) {
        for (int index = 0; index < branch.getTargets().size(); index++) {
            Unit original = branch.getTarget(index);
            String value = branch instanceof LookupSwitchStmt
                    ? String.valueOf(((LookupSwitchStmt) branch).getLookupValue(index))
                    : String.valueOf(((TableSwitchStmt) branch).getLowIndex() + index);
            Unit entry = Jimple.v().newNopStmt();
            body.getUnits().add(entry);
            body.getUnits().add(check(siteId, receiver, "CASE:" + value));
            body.getUnits().add(Jimple.v().newGotoStmt(original));
            branch.setTarget(index, entry);
        }
        Unit fallback = branch.getDefaultTarget();
        Unit defaultEntry = Jimple.v().newNopStmt();
        body.getUnits().add(defaultEntry);
        body.getUnits().add(check(siteId, receiver, "DEFAULT"));
        body.getUnits().add(Jimple.v().newGotoStmt(fallback));
        branch.setDefaultTarget(defaultEntry);
    }

    private static void weaveThrow(Body body, ThrowStmt thrown,
                                   SiteManifest.Target site, Value receiver) {
        Unit record = Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                ref("targetThrow", VoidType.v(), RefType.v("java.lang.String"),
                        RefType.v("java.lang.Object"), RefType.v("java.lang.String"),
                        RefType.v("java.lang.Throwable")),
                StringConstant.v(site.siteId), receiver,
                StringConstant.v(site.exceptionClass == null ? "" : site.exceptionClass),
                thrown.getOp()));
        body.getUnits().insertBefore(record, thrown);
    }

    private static void weaveCallFrames(Body body, SootMethod method,
                                        Unit[] original, Unit entry,
                                        java.util.Map<Unit, Integer> originalPositions,
                                        java.util.List<TrapSnapshot> applicationTraps,
                                        java.util.Map<Unit, Unit> doorStarts) {
        int ordinal = 0;
        boolean safe = false;
        for (Unit unit : original) {
            if (unit == entry) safe = true;
            if (!safe || !(unit instanceof Stmt)
                    || !((Stmt) unit).containsInvokeExpr()) continue;
            InvokeExpr call = ((Stmt) unit).getInvokeExpr();
            String descriptorKey = Base64.getUrlEncoder().withoutPadding()
                    .encodeToString(descriptor(method).getBytes(StandardCharsets.UTF_8));
            String siteId = method.getDeclaringClass().getName() + "#"
                    + method.getName() + "#" + descriptorKey + "#"
                    + (++ordinal);
            // A callee can open or end a request/tick root. Keep an opaque
            // receipt for the pre-call context instead of relying on the
            // current thread context at return. Object, rather than long,
            // also keeps JVM StackMap merging verifier-safe in catch paths.
            Local receipt = Jimple.v().newLocal("$malloryCallReceipt" + ordinal,
                    RefType.v("java.lang.Object"));
            body.getLocals().add(receipt);
            Unit enter = Jimple.v().newAssignStmt(receipt,
                    Jimple.v().newStaticInvokeExpr(
                            ref("openCall", RefType.v("java.lang.Object"),
                                    RefType.v("java.lang.String"), soot.IntType.v()),
                            StringConstant.v(siteId), IntConstant.v(ordinal)));
            Unit leave = Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                    ref("closeCall", VoidType.v(), RefType.v("java.lang.Object"),
                            RefType.v("java.lang.String")),
                    receipt, StringConstant.v(siteId)));
            Unit protectedStart = doorStarts.containsKey(unit)
                    ? doorStarts.get(unit) : unit;
            body.getUnits().insertBefore(enter, protectedStart);
            body.getUnits().insertAfter(leave, unit);
            // This trap is first so a pre-existing application catch still
            // sees the original exception after the frame is popped.
            Local caught = Jimple.v().newLocal("$malloryCallThrown" + ordinal,
                    RefType.v("java.lang.Throwable"));
            body.getLocals().add(caught);
            Unit handler = Jimple.v().newIdentityStmt(caught,
                    Jimple.v().newCaughtExceptionRef());
            body.getUnits().add(handler);
            body.getUnits().add(Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                    ref("closeCall", VoidType.v(), RefType.v("java.lang.Object"),
                            RefType.v("java.lang.String")),
                    receipt, StringConstant.v(siteId))));
            Unit rethrow = Jimple.v().newThrowStmt(caught);
            body.getUnits().add(rethrow);
            Unit bridgeEnd = Jimple.v().newNopStmt();
            body.getUnits().add(bridgeEnd);
            soot.Trap trap = Jimple.v().newTrap(
                    Scene.v().getSootClass("java.lang.Throwable"),
                    protectedStart, leave, handler);
            body.getTraps().addFirst(trap);
            // The synthetic handler lives after the original protected
            // ranges. Bridge its rethrow through every application trap
            // that guarded this call, in the original order. Otherwise an
            // existing JUnit/workload catch would be silently bypassed.
            Trap after = trap;
            Integer callPosition = originalPositions.get(unit);
            for (TrapSnapshot application : applicationTraps) {
                if (application.begin == null || application.end == null
                        || callPosition == null || callPosition < application.begin
                        || callPosition >= application.end) continue;
                Trap bridge = Jimple.v().newTrap(application.trap.getException(),
                        rethrow, bridgeEnd, application.trap.getHandlerUnit());
                body.getTraps().insertAfter(bridge, after);
                after = bridge;
            }
        }
    }

    private static final class TrapSnapshot {
        final Trap trap;
        final Integer begin;
        final Integer end;
        TrapSnapshot(Trap trap, Integer begin, Integer end) {
            this.trap = trap;
            this.begin = begin;
            this.end = end;
        }
    }

    private static void appendRegionHandler(Body body, Unit start, String regionId) {
        Local caught = Jimple.v().newLocal("$malloryRegionThrown",
                RefType.v("java.lang.Throwable"));
        body.getLocals().add(caught);
        Unit handler = Jimple.v().newIdentityStmt(caught,
                Jimple.v().newCaughtExceptionRef());
        body.getUnits().add(handler);
        body.getUnits().add(Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                ref("regionClose", VoidType.v(), RefType.v("java.lang.String")),
                StringConstant.v(regionId))));
        body.getUnits().add(Jimple.v().newThrowStmt(caught));
        body.getTraps().add(Jimple.v().newTrap(
                Scene.v().getSootClass("java.lang.Throwable"), start, handler, handler));
    }

    private static Unit safeEntry(Body body, SootMethod method) {
        Unit first = null;
        for (Unit unit : body.getUnits()) {
            if (!(unit instanceof IdentityStmt)) { first = unit; break; }
        }
        if (!method.isConstructor()) return first;
        if (first == null) return null;
        for (Unit unit : body.getUnits()) {
            if (unit instanceof Stmt && ((Stmt) unit).containsInvokeExpr()
                    && ((Stmt) unit).getInvokeExpr() instanceof soot.jimple.SpecialInvokeExpr
                    && "<init>".equals(((Stmt) unit).getInvokeExpr().getMethodRef().name())
                    && ((soot.jimple.SpecialInvokeExpr) ((Stmt) unit).getInvokeExpr())
                            .getBase().equivTo(body.getThisLocal())) {
                return body.getUnits().getSuccOf(unit);
            }
        }
        return null;
    }

    private static SootMethodRef ref(String name, Type result, Type... arguments) {
        SootClass hooks = Scene.v().getSootClass(HOOK);
        java.util.List<Type> parameters = java.util.Arrays.asList(arguments);
        return Scene.v().makeMethodRef(hooks, name, parameters, result, true);
    }

    static String descriptor(SootMethod method) {
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
        if (type instanceof RefType) return "L" + ((RefType) type).getClassName().replace('.', '/') + ";";
        if (type instanceof VoidType) return "V";
        String name = type.toString();
        if ("boolean".equals(name)) return "Z";
        if ("byte".equals(name)) return "B";
        if ("char".equals(name)) return "C";
        if ("short".equals(name)) return "S";
        if ("int".equals(name)) return "I";
        if ("long".equals(name)) return "J";
        if ("float".equals(name)) return "F";
        if ("double".equals(name)) return "D";
        throw new IllegalArgumentException("unsupported JVM descriptor type " + type);
    }
}
