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
