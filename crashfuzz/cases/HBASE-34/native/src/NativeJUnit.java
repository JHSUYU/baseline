import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;
import org.junit.platform.launcher.listeners.SummaryGeneratingListener;
import org.junit.platform.launcher.Launcher;
import org.junit.platform.launcher.listeners.TestExecutionSummary;

/** Executes the unchanged original parameterized JUnit test method. */
public class NativeJUnit {
  public static void main(String[] args) {
    Thread.currentThread().setContextClassLoader(NativeJUnit.class.getClassLoader());
    System.err.println("HBASE34 RESOURCE SecureTestCluster="
      + Thread.currentThread().getContextClassLoader().getResource(
        "org/apache/hadoop/hbase/security/token/SecureTestCluster.class"));
    SummaryGeneratingListener listener = new SummaryGeneratingListener();
    Launcher launcher = LauncherFactory.create();
    launcher.registerTestExecutionListeners(listener);
    launcher.execute(LauncherDiscoveryRequestBuilder.request()
      .selectors(DiscoverySelectors.selectMethod(args[0], args[1])).build());
    TestExecutionSummary summary = listener.getSummary();
    System.err.println("HBASE34 JUNIT found=" + summary.getTestsFoundCount()
      + " succeeded=" + summary.getTestsSucceededCount()
      + " failed=" + summary.getTestsFailedCount()
      + " aborted=" + summary.getTestsAbortedCount());
    summary.getFailures().forEach(f -> f.getException().printStackTrace(System.err));
    System.exit(summary.getTestsFoundCount() == 1 && summary.getTestsSucceededCount() == 1
      && summary.getTestsFailedCount() == 0 && summary.getTestsAbortedCount() == 0 ? 0 : 1);
  }
}
