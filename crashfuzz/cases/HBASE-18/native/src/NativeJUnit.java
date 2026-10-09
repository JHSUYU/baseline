import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;
import org.junit.platform.launcher.listeners.SummaryGeneratingListener;
import org.junit.platform.launcher.Launcher;
import org.junit.platform.launcher.listeners.TestExecutionSummary;

/** Executes one unchanged original JUnit Jupiter method through the native launcher. */
public class NativeJUnit {
  public static void main(String[] args) {
    SummaryGeneratingListener listener = new SummaryGeneratingListener();
    Launcher launcher = LauncherFactory.create();
    launcher.registerTestExecutionListeners(listener);
    launcher.execute(LauncherDiscoveryRequestBuilder.request()
      .selectors(DiscoverySelectors.selectMethod(args[0], args[1])).build());
    TestExecutionSummary summary = listener.getSummary();
    System.err.println("HBASE18 JUNIT found=" + summary.getTestsFoundCount()
      + " succeeded=" + summary.getTestsSucceededCount()
      + " failed=" + summary.getTestsFailedCount()
      + " aborted=" + summary.getTestsAbortedCount());
    summary.getFailures().forEach(f -> f.getException().printStackTrace(System.err));
    System.exit(summary.getTestsFoundCount() == 1 && summary.getTestsSucceededCount() == 1
      && summary.getTestsFailedCount() == 0 && summary.getTestsAbortedCount() == 0 ? 0 : 1);
  }
}
