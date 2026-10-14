package edu.uva.liftlab.graphchecker.runtime;

import java.io.PrintWriter;
import java.lang.reflect.Method;
import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.launcher.Launcher;
import org.junit.platform.launcher.LauncherDiscoveryRequest;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;
import org.junit.platform.launcher.listeners.SummaryGeneratingListener;
import org.junit.platform.launcher.listeners.TestExecutionSummary;

/** Opens a native GraphChecker recording window around an unchanged Jupiter method. */
public final class NativeRecordingJUnitMethodRunner {
    private NativeRecordingJUnitMethodRunner() { }

    public static void main(String[] args) {
        if (args.length != 2) {
            throw new IllegalArgumentException("expected JUnit class and method");
        }
        Object source = new Object();
        RuntimeTraceContext.registerSource(source,
                new SourceRef("SYSTEM", "CLIENT", "native-junit", 0));
        long request = RuntimeTraceContext.beginRequest(source, args[1]);
        long frame = Identity.enterFrame(args[1], source);
        int status = 1;
        CausynthTraceRecorder.startRecording();
        try {
            Class<?> testClass = Class.forName(args[0]);
            Method selected = null;
            for (Class<?> owner = testClass; owner != null;
                    owner = owner.getSuperclass()) {
                for (Method candidate : owner.getDeclaredMethods()) {
                    if (candidate.getName().equals(args[1])) {
                        if (selected != null) {
                            throw new IllegalArgumentException(
                                    "JUnit method name is ambiguous: " + args[1]);
                        }
                        selected = candidate;
                    }
                }
            }
            if (selected == null) {
                throw new IllegalArgumentException("JUnit method is absent: " + args[1]);
            }
            LauncherDiscoveryRequest discovery = LauncherDiscoveryRequestBuilder.request()
                    .selectors(DiscoverySelectors.selectMethod(testClass, selected))
                    .build();
            Launcher launcher = LauncherFactory.create();
            SummaryGeneratingListener listener = new SummaryGeneratingListener();
            launcher.registerTestExecutionListeners(listener);
            launcher.execute(discovery);
            TestExecutionSummary summary = listener.getSummary();
            summary.printFailuresTo(new PrintWriter(System.err, true));
            // Selecting one parameterized method executes all of its original
            // invocations.  Require at least one completed invocation and no
            // failed or skipped invocation, without assuming a single test.
            status = summary.getTestsSucceededCount() > 0
                    && summary.getTestsFailedCount() == 0
                    && summary.getTestsSkippedCount() == 0 ? 0 : 1;
            System.out.println("NATIVE_RECORDING_JUNIT_RESULT passed="
                    + summary.getTestsSucceededCount() + " failed="
                    + summary.getTestsFailedCount() + " skipped="
                    + summary.getTestsSkippedCount() + " found="
                    + summary.getTestsFoundCount());
        } finally {
            CausynthTraceRecorder.stopRecording();
            Identity.exitFrame(frame);
            RuntimeTraceContext.endRequest(request);
        }
        // A MiniCluster can retain non-daemon threads after Jupiter teardown.
        System.exit(status);
    }
}
