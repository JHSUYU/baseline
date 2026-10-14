package edu.uva.liftlab.graphchecker.causynth;

import org.junit.Test;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

/** Checks the actual fault-site admission path in recording and replay modes. */
public class MalloryNativeFaultWeaveModeTest {
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
