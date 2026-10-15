package edu.uva.liftlab.graphchecker.causynth;

import com.google.gson.JsonObject;
import org.junit.Test;
import soot.Body;
import soot.BooleanType;
import soot.Local;
import soot.Modifier;
import soot.RefType;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.SootMethodRef;
import soot.Trap;
import soot.Unit;
import soot.VoidType;
import soot.jimple.GotoStmt;
import soot.jimple.Jimple;
import soot.jimple.Stmt;
import soot.jimple.StaticInvokeExpr;
import soot.jimple.NullConstant;
import soot.options.Options;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Collections;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertSame;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/** Checks the actual fault-site admission path in recording and replay modes. */
public class MalloryNativeFaultWeaveModeTest {
    @Test public void nativeDoorWeaveCarriesExactInstanceOwnerAndNullForStatic()
            throws Exception {
        soot.G.reset();
        Options.v().set_allow_phantom_refs(true);
        SootClass hooks = new SootClass(
                "edu.uva.liftlab.graphchecker.runtime.NativeFaultHooks", Modifier.PUBLIC);
        Scene.v().addClass(hooks);
        hooks.addMethod(new SootMethod("beforeDoor", Arrays.asList(
                RefType.v("java.lang.String"), RefType.v("java.lang.String"),
                RefType.v("java.lang.Object")), VoidType.v(),
                Modifier.PUBLIC | Modifier.STATIC));
        SootClass owner = new SootClass("test.NativeDoorOwner", Modifier.PUBLIC);
        Scene.v().addClass(owner);
        SootMethod callee = new SootMethod("io", Collections.<soot.Type>emptyList(),
                VoidType.v(), Modifier.PUBLIC | Modifier.STATIC);
        owner.addMethod(callee);
        JsonObject manifest = new JsonObject();
        com.google.gson.JsonArray doors = new com.google.gson.JsonArray();
        manifest.add("doors", doors);
        for (boolean staticMethod : new boolean[] {false, true}) {
            SootMethod method = new SootMethod(staticMethod ? "staticRun" : "instanceRun",
                    Collections.<soot.Type>emptyList(), VoidType.v(),
                    Modifier.PUBLIC | (staticMethod ? Modifier.STATIC : 0));
            owner.addMethod(method);
            Body body = Jimple.v().newBody(method);
            method.setActiveBody(body);
            Local receiver = null;
            if (!staticMethod) {
                receiver = Jimple.v().newLocal("self", RefType.v(owner.getName()));
                body.getLocals().add(receiver);
                body.getUnits().add(Jimple.v().newIdentityStmt(receiver,
                        Jimple.v().newThisRef(RefType.v(owner.getName()))));
            }
            Unit call = Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                    callee.makeRef()));
            body.getUnits().add(call);
            body.getUnits().add(Jimple.v().newReturnVoidStmt());
            JsonObject row = new JsonObject();
            row.addProperty("clazz", owner.getName());
            row.addProperty("method", method.getName());
            row.addProperty("descriptor", "()V");
            row.addProperty("unitIndex", staticMethod ? 0 : 1);
            row.addProperty("line", 1);
            row.addProperty("siteId", method.getSignature() + "#io");
            row.addProperty("kind", "RPC");
            row.addProperty("callee", callee.getSignature());
            row.addProperty("exceptionClass", "java.io.IOException");
            doors.add(row);
        }
        Path path = Files.createTempFile("native-owner-weave-", ".json");
        Files.write(path, manifest.toString().getBytes(StandardCharsets.UTF_8));
        String prior = System.getProperty(MalloryNativeFaultWeave.PROPERTY);
        try {
            System.setProperty(MalloryNativeFaultWeave.PROPERTY, path.toString());
            MalloryNativeFaultWeave weave = new MalloryNativeFaultWeave();
            java.lang.reflect.Field sitesField = MalloryNativeFaultWeave.class
                    .getDeclaredField("sites");
            sitesField.setAccessible(true);
            java.util.List<?> sites = (java.util.List<?>) sitesField.get(weave);
            for (Object site : sites) {
                Class<?> type = site.getClass();
                java.lang.reflect.Field bodyField = type.getDeclaredField("body");
                java.lang.reflect.Field unitField = type.getDeclaredField("unit");
                bodyField.setAccessible(true);
                unitField.setAccessible(true);
                java.lang.reflect.Field methodField = type.getDeclaredField("method");
                methodField.setAccessible(true);
                SootMethod method = owner.getMethodByName((String) methodField.get(site));
                Body body = method.getActiveBody();
                bodyField.set(site, body);
                unitField.set(site, body.getUnits().getPredOf(body.getUnits().getLast()));
            }
            Method insert = MalloryNativeFaultWeave.class.getDeclaredMethod("insertHooks");
            insert.setAccessible(true);
            insert.invoke(weave);
            for (boolean staticMethod : new boolean[] {false, true}) {
                Body body = owner.getMethodByName(staticMethod ? "staticRun" : "instanceRun")
                        .getActiveBody();
                Stmt hook = (Stmt) body.getUnits().getPredOf(
                        body.getUnits().getPredOf(body.getUnits().getLast()));
                StaticInvokeExpr expr = (StaticInvokeExpr) hook.getInvokeExpr();
                assertEquals(3, expr.getArgCount());
                assertEquals("beforeDoor", expr.getMethod().getName());
                assertEquals(staticMethod ? NullConstant.v() : body.getThisLocal(),
                        expr.getArg(2));
                body.validate();
            }
        } finally {
            restore(MalloryNativeFaultWeave.PROPERTY, prior);
            Files.deleteIfExists(path);
        }
    }

    @Test public void calledExceptionHookCatchesOneInvocationAndRethrows()
            throws Exception {
        soot.G.reset();
        Options.v().set_prepend_classpath(true);
        Options.v().set_allow_phantom_refs(true);
        SootClass exception = Scene.v().loadClassAndSupport(
                "java.lang.IllegalStateException");
        SootClass owner = new SootClass("test.CalledOracle", Modifier.PUBLIC);
        Scene.v().addClass(owner);
        SootMethod method = new SootMethod("run",
                Collections.singletonList(BooleanType.v()), VoidType.v(),
                Modifier.PUBLIC | Modifier.STATIC);
        owner.addMethod(method);
        Body body = Jimple.v().newBody(method);
        method.setActiveBody(body);
        Local valid = Jimple.v().newLocal("valid", BooleanType.v());
        body.getLocals().add(valid);
        body.getUnits().add(Jimple.v().newIdentityStmt(valid,
                Jimple.v().newParameterRef(BooleanType.v(), 0)));
        SootClass checks = new SootClass("test.Checks", Modifier.PUBLIC);
        Scene.v().addClass(checks);
        SootMethod checkState = new SootMethod("checkState",
                Collections.singletonList(BooleanType.v()), VoidType.v(),
                Modifier.PUBLIC | Modifier.STATIC);
        checks.addMethod(checkState);
        Unit call = Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                checkState.makeRef(), valid));
        Unit done = Jimple.v().newReturnVoidStmt();
        body.getUnits().add(call);
        body.getUnits().add(done);
        Local originalCaught = Jimple.v().newLocal("originalCaught",
                RefType.v("java.lang.Throwable"));
        body.getLocals().add(originalCaught);
        Unit originalHandler = Jimple.v().newIdentityStmt(originalCaught,
                Jimple.v().newCaughtExceptionRef());
        body.getUnits().add(originalHandler);
        body.getUnits().add(Jimple.v().newReturnVoidStmt());
        body.getTraps().add(Jimple.v().newTrap(
                Scene.v().loadClassAndSupport("java.lang.Throwable"),
                call, done, originalHandler));
        JsonObject row = new JsonObject();
        row.addProperty("clazz", owner.getName());
        row.addProperty("method", method.getName());
        row.addProperty("descriptor", "(Z)V");
        row.addProperty("unitIndex", 1);
        row.addProperty("line", 1);
        row.addProperty("siteId", method.getSignature() + "#u1");
        row.addProperty("kind", "CALL_THROW");
        row.addProperty("callee", checkState.getSignature());
        row.addProperty("exceptionClass", exception.getName());
        Class<?> siteClass = Class.forName(MalloryNativeFaultWeave.class.getName()
                + "$Site");
        java.lang.reflect.Constructor<?> constructor = siteClass
                .getDeclaredConstructor(JsonObject.class, boolean.class);
        constructor.setAccessible(true);
        Object site = constructor.newInstance(row, true);
        java.lang.reflect.Field selectedBody = siteClass.getDeclaredField("body");
        java.lang.reflect.Field selectedUnit = siteClass.getDeclaredField("unit");
        selectedBody.setAccessible(true);
        selectedUnit.setAccessible(true);
        selectedBody.set(site, body);
        selectedUnit.set(site, call);
        SootClass hooks = new SootClass("test.Hooks", Modifier.PUBLIC);
        Scene.v().addClass(hooks);
        SootMethod report = new SootMethod("targetThrow", Arrays.asList(
                RefType.v("java.lang.String"), RefType.v("java.lang.String"),
                RefType.v("java.lang.Throwable")), VoidType.v(),
                Modifier.PUBLIC | Modifier.STATIC);
        hooks.addMethod(report);
        Method insert = MalloryNativeFaultWeave.class.getDeclaredMethod(
                "insertCalledThrowHook", siteClass, SootMethodRef.class);
        insert.setAccessible(true);
        insert.invoke(null, site, report.makeRef());
        body.validate();
        assertEquals(2, body.getTraps().size());
        Trap trap = body.getTraps().getFirst();
        assertEquals(exception.getName(), trap.getException().getName());
        assertSame(call, trap.getBeginUnit());
        assertTrue(trap.getEndUnit() instanceof GotoStmt);
        assertSame(done, ((GotoStmt) trap.getEndUnit()).getTarget());
        assertSame(originalHandler, body.getTraps().getLast().getHandlerUnit());
        assertSame(done, body.getTraps().getLast().getEndUnit());
        assertTrue(body.getUnits().getSuccOf(trap.getHandlerUnit())
                instanceof Stmt);
        assertEquals(9, body.getUnits().size());
    }

    @Test public void recordingAdmitsSelectedSitesButContextOnlyReplayDoesNot()
            throws Exception {
        Path manifest = Files.createTempFile("mallory-native-fault-mode-", ".json");
        Files.write(manifest, ("{\"doors\":[{\"clazz\":\"missing.FaultDoor\","
                + "\"method\":\"call\",\"descriptor\":\"()V\","
                + "\"unitIndex\":0,\"line\":1,\"siteId\":\"missing#u0\","
                + "\"callee\":\"<missing.FaultDoor: void call()>\"}]}"
                ).getBytes(StandardCharsets.UTF_8));
        String priorManifest = System.getProperty(MalloryNativeFaultWeave.PROPERTY);
        String priorMode = System.getProperty("causynth.trace.mode");
        String priorConcolic = System.getProperty("causynth.instrument.concolic");
        try {
            System.setProperty(MalloryNativeFaultWeave.PROPERTY,
                    manifest.toString());
            System.setProperty("causynth.instrument.concolic", "false");
            MalloryNativeFaultWeave weave = new MalloryNativeFaultWeave();
            Method capture = MalloryNativeFaultWeave.class
                    .getDeclaredMethod("captureSites");
            capture.setAccessible(true);

            System.setProperty("causynth.trace.mode", "region-state");
            assertFailure(capture, weave,
                    "selected I/O class is outside GraphChecker process dirs");

            System.setProperty("causynth.trace.mode", "replay-context");
            assertFailure(capture, weave,
                    "requires original concolic or REGION_STATE weave");
        } finally {
            restore(MalloryNativeFaultWeave.PROPERTY, priorManifest);
            restore("causynth.trace.mode", priorMode);
            restore("causynth.instrument.concolic", priorConcolic);
            Files.deleteIfExists(manifest);
        }
    }

    private static void assertFailure(Method method, Object receiver,
                                      String expected) throws Exception {
        try {
            method.invoke(receiver);
            fail("expected selected-site admission to refuse the fixture");
        } catch (InvocationTargetException failure) {
            assertTrue(String.valueOf(failure.getCause().getMessage()),
                    failure.getCause().getMessage().contains(expected));
        }
    }

    private static void restore(String key, String value) {
        if (value == null) System.clearProperty(key);
        else System.setProperty(key, value);
    }
}
