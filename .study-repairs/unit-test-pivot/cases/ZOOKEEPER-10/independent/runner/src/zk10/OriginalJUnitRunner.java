package zk10;

import java.io.PrintWriter;
import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.launcher.Launcher;
import org.junit.platform.launcher.LauncherDiscoveryRequest;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;
import org.junit.platform.launcher.listeners.SummaryGeneratingListener;
import org.junit.platform.launcher.listeners.TestExecutionSummary;

/** Execute the original parameterized JUnit with its normal lifecycle. */
public final class OriginalJUnitRunner {
    public static void main(String[] args) throws Exception {
        // Define the selected target class before Follower frame computation
        // can load it recursively. The original test method stays unchanged.
        Class.forName("org.apache.zookeeper.server.quorum.ObserverMaster", false,
                ClassLoader.getSystemClassLoader());
        System.out.println("ZK10_PRELOAD_OBSERVER_MASTER_OK");
        String invocation = "[engine:junit-jupiter]/"
                + "[class:org.apache.zookeeper.test.ObserverMasterTest]/"
                + "[test-template:testInOrderCommits(boolean)]/"
                + "[test-template-invocation:#1]";
        LauncherDiscoveryRequest request = LauncherDiscoveryRequestBuilder.request()
                .selectors(DiscoverySelectors.selectUniqueId(invocation))
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
