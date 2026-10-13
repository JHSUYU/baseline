package edu.uva.liftlab.graphchecker.runtime;

import java.io.PrintWriter;
import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.launcher.Launcher;
import org.junit.platform.launcher.LauncherDiscoveryRequest;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;
import org.junit.platform.launcher.listeners.SummaryGeneratingListener;
import org.junit.platform.launcher.listeners.TestExecutionSummary;

/** Session harness for an unchanged, selected JUnit Jupiter method. */
public final class NativeJUnitMethodRunner {
    private NativeJUnitMethodRunner() { }

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            throw new IllegalArgumentException("expected JUnit class and method");
        }
        String opened = ConcolicRegionRuntime.openWorkloadSession();
        if (!opened.isEmpty()) {
            throw new IllegalStateException(opened);
        }
        Object source = new Object();
        RuntimeTraceContext.registerSource(source,
                new SourceRef("SYSTEM", "CLIENT", "native-junit", 0));
        RecordingWindow.open();
        long request = RuntimeTraceContext.beginRequest(source, args[1]);
        long frame = Identity.enterFrame(args[1], source);
        boolean successful = false;
        try {
            LauncherDiscoveryRequest discovery = LauncherDiscoveryRequestBuilder.request()
                    .selectors(DiscoverySelectors.selectMethod(args[0], args[1]))
                    .build();
            Launcher launcher = LauncherFactory.create();
            SummaryGeneratingListener listener = new SummaryGeneratingListener();
            launcher.registerTestExecutionListeners(listener);
            launcher.execute(discovery);
            TestExecutionSummary summary = listener.getSummary();
            summary.printFailuresTo(new PrintWriter(System.err, true));
            successful = summary.getTestsSucceededCount() == 1
                    && summary.getTestsFailedCount() == 0;
            System.out.println("NATIVE_JUNIT_RESULT passed="
                    + summary.getTestsSucceededCount() + " failed="
                    + summary.getTestsFailedCount() + " skipped="
                    + summary.getTestsSkippedCount());
        } finally {
            for (ConcolicTaskPlan.RefusedCandidate reason
                    : ConcolicTaskPlan.configuration().tasks.get(0).unaddressedReasons) {
                System.out.println("NATIVE_UNADDRESSED " + reason.render(
                        ConcolicTaskPlan.configuration().tasks.get(0)));
            }
            Identity.exitFrame(frame);
            RuntimeTraceContext.endRequest(request);
            RecordingWindow.close();
            String closed = ConcolicRegionRuntime.closeWorkloadSession();
            if (!closed.isEmpty()) {
                throw new IllegalStateException(closed);
            }
            RowRuntime.closeSession();
        }
        // MiniCluster cleanup threads can outlive the method, as in Surefire.
        System.exit(successful ? 0 : 1);
    }
}
