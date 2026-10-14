package edu.uva.liftlab.graphchecker.runtime;

import java.io.PrintWriter;
import java.lang.reflect.Method;
import java.nio.file.Paths;
import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.launcher.Launcher;
import org.junit.platform.launcher.LauncherDiscoveryRequest;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;
import org.junit.platform.launcher.listeners.SummaryGeneratingListener;
import org.junit.platform.launcher.listeners.TestExecutionSummary;

/** Opens an original GraphChecker session around an unchanged Jupiter workload. */
public final class NativeZooKeeperSessionJUnitRunner {
    private NativeZooKeeperSessionJUnitRunner() { }

    public static void main(String[] args) throws Exception {
        if (args.length != 3) throw new IllegalArgumentException(
                "expected result file, JUnit class and method");
        Class<?> testClass = Class.forName(args[1]);
        Method selected = null;
        for (Method method : testClass.getDeclaredMethods()) {
            if (!args[2].equals(method.getName())) continue;
            if (selected != null) throw new IllegalArgumentException(
                    "ambiguous JUnit method: " + args[1] + "#" + args[2]);
            selected = method;
        }
        if (selected == null) throw new IllegalArgumentException(
                "missing JUnit method: " + args[1] + "#" + args[2]);
        RowRuntime.configure(Paths.get(args[0]));
        Object source = new Object();
        RuntimeTraceContext.registerSource(source,
                new SourceRef("SYSTEM", "CLIENT", "native-junit", 0));
        long request = RuntimeTraceContext.beginRequest(source, args[2]);
        long frame = Identity.enterFrame(args[2], source);
        int status = 1;
        CausynthTraceRecorder.startRecording();
        try {
            LauncherDiscoveryRequest discovery = LauncherDiscoveryRequestBuilder.request()
                    .selectors(DiscoverySelectors.selectMethod(testClass, selected))
                    .build();
            Launcher launcher = LauncherFactory.create();
            SummaryGeneratingListener listener = new SummaryGeneratingListener();
            launcher.registerTestExecutionListeners(listener);
            launcher.execute(discovery);
            TestExecutionSummary summary = listener.getSummary();
            summary.printFailuresTo(new PrintWriter(System.err, true));
            status = summary.getTestsSucceededCount() >= 1
                    && summary.getTestsFailedCount() == 0
                    && summary.getTestsSkippedCount() == 0 ? 0 : 1;
            System.out.println("NATIVE_ZK_SESSION_JUNIT_RESULT passed="
                    + summary.getTestsSucceededCount() + " failed="
                    + summary.getTestsFailedCount() + " skipped="
                    + summary.getTestsSkippedCount());
        } finally {
            CausynthTraceRecorder.stopRecording();
            Identity.exitFrame(frame);
            RuntimeTraceContext.endRequest(request);
            RowRuntime.closeSession();
        }
        System.exit(status);
    }
}
