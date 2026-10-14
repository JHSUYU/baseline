package edu.uva.liftlab.graphchecker.causynth;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import edu.uva.liftlab.graphchecker.runtime.RuntimeTraceMode;
import soot.Body;
import soot.Local;
import soot.RefType;
import soot.Scene;
import soot.SceneTransformer;
import soot.SootClass;
import soot.SootMethod;
import soot.SootMethodRef;
import soot.Trap;
import soot.Type;
import soot.Unit;
import soot.VoidType;
import soot.jimple.Jimple;
import soot.jimple.IfStmt;
import soot.jimple.GotoStmt;
import soot.jimple.Stmt;
import soot.jimple.StringConstant;
import soot.jimple.ThrowStmt;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Optional Mallory adapter around, never inside, the original GraphChecker Soot pass. */
public final class MalloryNativeFaultWeave {
    public static final String PROPERTY = "mallory.native.fault.manifest";
    private static final String HOOK =
            "edu.uva.liftlab.graphchecker.runtime.NativeFaultHooks";
    private final List<Site> sites;

    public static boolean requested() {
        String path = System.getProperty(PROPERTY);
        return path != null && !path.trim().isEmpty();
    }

    public MalloryNativeFaultWeave() {
        if (!requested()) throw new IllegalStateException("native fault manifest absent");
        try {
            JsonObject manifest = new JsonParser().parse(new String(Files.readAllBytes(
                    Paths.get(System.getProperty(PROPERTY))),
                    StandardCharsets.UTF_8)).getAsJsonObject();
            sites = new ArrayList<>();
            add(manifest.getAsJsonArray("doors"), false);
            add(manifest.getAsJsonArray("targets"), true);
            if (sites.isEmpty()) throw new IllegalArgumentException(
                    "native static manifest selects no I/O door or target site");
            Set<String> selected = new HashSet<>();
            for (Site site : sites) {
                if (!selected.add(site.siteId)) throw new IllegalArgumentException(
                        "duplicate native static site " + site.siteId);
            }
        } catch (IOException failure) {
            throw new IllegalStateException("cannot read native fault manifest", failure);
        }
    }

    public SceneTransformer capture() {
        return new SceneTransformer() {
            @Override protected void internalTransform(String phase,
                                                       Map<String, String> options) {
                captureSites();
            }
        };
    }

    public SceneTransformer insert() {
        return new SceneTransformer() {
            @Override protected void internalTransform(String phase,
                                                       Map<String, String> options) {
                insertHooks();
            }
        };
    }

    private void add(JsonArray rows, boolean target) {
        if (rows == null) return;
        for (JsonElement element : rows) {
            JsonObject row = element.getAsJsonObject();
            if (target && !"THROW".equals(value(row, "kind"))
                    && !"CALL_THROW".equals(value(row, "kind"))
                    && !"BRANCH".equals(value(row, "kind"))) continue;
            sites.add(new Site(row, target));
        }
    }

    private void captureSites() {
        if (!ConcolicInstrumentationSelections.instrumentationRequested()
                && RuntimeTraceMode.configured() != RuntimeTraceMode.REGION_STATE) {
            throw new IllegalStateException("native fault adapter requires original concolic or REGION_STATE weave");
        }
        List<SootClass> application = new ArrayList<>(Scene.v().getApplicationClasses());
        application.sort(Comparator.comparing(SootClass::getName));
        for (Site site : sites) {
            SootClass clazz = null;
            for (SootClass candidate : application) {
                if (candidate.getName().equals(site.clazz)) {
                    clazz = candidate;
                    break;
                }
            }
            if (clazz == null) throw new IllegalArgumentException(
                    "selected I/O class is outside GraphChecker process dirs: " + site.clazz);
            for (SootMethod method : clazz.getMethods()) {
                if (!method.getName().equals(site.method)
                        || !descriptor(method).equals(site.descriptor)) continue;
                Body body = method.retrieveActiveBody();
                Unit[] units = body.getUnits().toArray(new Unit[0]);
                if (site.unitIndex < 0 || site.unitIndex >= units.length) {
                    throw new IllegalArgumentException("static Jimple unit index is absent: "
                            + site.siteId);
                }
                Unit unit = units[site.unitIndex];
                if (unit.getJavaSourceStartLineNumber() != site.line) {
                    throw new IllegalArgumentException("static/Jimple line mismatch: "
                            + site.siteId);
                }
                if ("THROW".equals(site.kind) ? !(unit instanceof ThrowStmt)
                        : "BRANCH".equals(site.kind) ? !(unit instanceof IfStmt)
                        : "CALL_THROW".equals(site.kind)
                          ? !(unit instanceof Stmt)
                            || !((Stmt) unit).containsInvokeExpr()
                            || !site.callee.equals(((Stmt) unit).getInvokeExpr()
                                    .getMethodRef().getSignature())
                        : !(unit instanceof Stmt)
                          || !((Stmt) unit).containsInvokeExpr()
                          || !site.callee.equals(((Stmt) unit).getInvokeExpr()
                                  .getMethodRef().getSignature())) {
                    throw new IllegalArgumentException("static/Jimple selected unit mismatch: "
                            + site.siteId + " at " + unit);
                }
                site.body = body;
                site.unit = unit;
                break;
            }
            if (site.unit == null) throw new IllegalArgumentException(
                    "selected method absent from GraphChecker application scope: "
                    + site.siteId);
        }
        // The runtime helper is supplied by the pinned adapter JAR on the
        // original GraphChecker weave classpath, not by a case-specific patch.
        SootClass helper = Scene.v().loadClassAndSupport(HOOK);
        if (helper == null || helper.isPhantom()) throw new IllegalStateException(
                "native fault helper is absent from pinned weave classpath");
    }

    private void insertHooks() {
        SootClass helper = Scene.v().getSootClass(HOOK);
        SootMethodRef door = Scene.v().makeMethodRef(helper, "beforeDoor",
                java.util.Arrays.<Type>asList(RefType.v("java.lang.String"),
                        RefType.v("java.lang.String")), VoidType.v(), true);
        SootMethodRef target = Scene.v().makeMethodRef(helper, "targetThrow",
                java.util.Arrays.<Type>asList(RefType.v("java.lang.String"),
                        RefType.v("java.lang.String"),
                        RefType.v("java.lang.Throwable")), VoidType.v(), true);
        SootMethodRef targetCheck = Scene.v().makeMethodRef(helper, "targetCheck",
                java.util.Arrays.<Type>asList(RefType.v("java.lang.String")),
                VoidType.v(), true);
        IdentityHashMap<Body, Boolean> modified = new IdentityHashMap<>();
        for (Site site : sites) {
            Body body = site.body;
            Unit at = site.unit;
            if (body == null || at == null || !body.getUnits().contains(at)) {
                throw new IllegalStateException("original GraphChecker dropped selected unit: "
                        + site.siteId);
            }
            if ("CALL_THROW".equals(site.kind)) {
                insertCalledThrowHook(site, target);
                modified.put(body, Boolean.TRUE);
                continue;
            }
            Unit hook = "THROW".equals(site.kind)
                    ? Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                            target, StringConstant.v(site.siteId),
                            StringConstant.v(site.exceptionClass),
                            ((ThrowStmt) at).getOp()))
                    : "BRANCH".equals(site.kind)
                    ? Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                            targetCheck, StringConstant.v(site.siteId)))
                    : Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                            door, StringConstant.v(site.siteId),
                            StringConstant.v(site.exceptionClass)));
            body.getUnits().insertBefore(hook, at);
            // An injected IOException should enter the same application
            // handler that encloses the selected I/O call.
            for (Trap trap : body.getTraps()) {
                if (trap.getBeginUnit() == at) trap.setBeginUnit(hook);
            }
            modified.put(body, Boolean.TRUE);
        }
        for (Body body : modified.keySet()) body.validate();
    }

    /** Catch only the declared exception at one exact invocation, then rethrow unchanged. */
    private static void insertCalledThrowHook(Site site, SootMethodRef target) {
        Body body = site.body;
        Unit invocation = site.unit;
        Unit successor = body.getUnits().getSuccOf(invocation);
        if (successor == null) throw new IllegalArgumentException(
                "call-thrown target has no normal successor: " + site.siteId);
        SootClass exception = Scene.v().loadClassAndSupport(site.exceptionClass);
        if (exception == null || exception.isPhantom()) throw new IllegalArgumentException(
                "call-thrown exception class unavailable: " + site.exceptionClass);
        Local caught = Jimple.v().newLocal("$malloryCallThrow" + site.unitIndex,
                RefType.v(site.exceptionClass));
        body.getLocals().add(caught);
        GotoStmt resume = Jimple.v().newGotoStmt(successor);
        Unit handler = Jimple.v().newIdentityStmt(caught,
                Jimple.v().newCaughtExceptionRef());
        Unit report = Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                target, StringConstant.v(site.siteId),
                StringConstant.v(site.exceptionClass), caught));
        Unit rethrow = Jimple.v().newThrowStmt(caught);
        body.getUnits().insertAfter(resume, invocation);
        body.getUnits().insertAfter(handler, resume);
        body.getUnits().insertAfter(report, handler);
        body.getUnits().insertAfter(rethrow, report);
        // The new handler must precede an existing application catch. Its
        // rethrow stays inside the original protected range when there is one.
        body.getTraps().addFirst(Jimple.v().newTrap(exception,
                invocation, resume, handler));
    }

    private static String value(JsonObject row, String key) {
        if (!row.has(key) || !row.get(key).isJsonPrimitive()) {
            throw new IllegalArgumentException("static manifest lacks " + key);
        }
        String result = row.get(key).getAsString();
        if (result.isEmpty()) throw new IllegalArgumentException(
                "static manifest has empty " + key);
        return result;
    }

    private static String descriptor(SootMethod method) {
        StringBuilder out = new StringBuilder("(");
        for (Type type : method.getParameterTypes()) out.append(type(type));
        return out.append(')').append(type(method.getReturnType())).toString();
    }

    private static String type(Type sootType) {
        String name = sootType.toString();
        int dimensions = 0;
        while (name.endsWith("[]")) {
            dimensions++;
            name = name.substring(0, name.length() - 2);
        }
        String primitive;
        switch (name) {
            case "void": primitive = "V"; break;
            case "boolean": primitive = "Z"; break;
            case "byte": primitive = "B"; break;
            case "char": primitive = "C"; break;
            case "short": primitive = "S"; break;
            case "int": primitive = "I"; break;
            case "long": primitive = "J"; break;
            case "float": primitive = "F"; break;
            case "double": primitive = "D"; break;
            default: primitive = "L" + name.replace('.', '/') + ";";
        }
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < dimensions; i++) out.append('[');
        return out.append(primitive).toString();
    }

    private static final class Site {
        final String clazz;
        final String method;
        final String descriptor;
        final int unitIndex;
        final int line;
        final String siteId;
        final String callee;
        final String exceptionClass;
        final String kind;
        Body body;
        Unit unit;

        Site(JsonObject row, boolean target) {
            clazz = value(row, "clazz");
            method = value(row, "method");
            descriptor = value(row, "descriptor");
            unitIndex = row.get("unitIndex").getAsInt();
            line = row.get("line").getAsInt();
            siteId = value(row, "siteId");
            callee = target && !"CALL_THROW".equals(value(row, "kind"))
                    ? "" : value(row, "callee");
            exceptionClass = row.has("exceptionClass")
                    ? value(row, "exceptionClass") : "java.io.IOException";
            this.kind = target ? value(row, "kind") : "DOOR";
        }
    }
}
