package zk13;

import java.io.PrintWriter;
import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.launcher.Launcher;
import org.junit.platform.launcher.LauncherDiscoveryRequest;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;
import org.junit.platform.launcher.listeners.SummaryGeneratingListener;
import org.junit.platform.launcher.listeners.TestExecutionSummary;

/** Execute one unchanged JUnit Jupiter method with its normal lifecycle. */
public final class OriginalJUnitRunner {
    public static void main(String[] args) {
        if (args.length != 2) {
            throw new IllegalArgumentException("expected test class and method");
        }
        LauncherDiscoveryRequest request = LauncherDiscoveryRequestBuilder.request()
                .selectors(DiscoverySelectors.selectMethod(args[0], args[1]))
                .build();
        Launcher launcher = LauncherFactory.create();
        SummaryGeneratingListener listener = new SummaryGeneratingListener();
        launcher.registerTestExecutionListeners(listener);
        launcher.execute(request);
        TestExecutionSummary summary = listener.getSummary();
        summary.printTo(new PrintWriter(System.out, true));
        summary.printFailuresTo(new PrintWriter(System.out, true));
        int code = (summary.getTestsFoundCount() != 1 || summary.getTestsSucceededCount() != 1
                || summary.getTestsFailedCount() != 0 || summary.getTestsSkippedCount() != 0)
                ? 1 : 0;
        System.exit(code);
    }
}
