import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.launcher.Launcher;
import org.junit.platform.launcher.LauncherDiscoveryRequest;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;
import org.junit.platform.launcher.listeners.TestExecutionSummary;
import org.junit.platform.launcher.listeners.SummaryGeneratingListener;

public final class NativeJUnit {
  public static void main(String[] args) {
    LauncherDiscoveryRequest request = LauncherDiscoveryRequestBuilder.request()
      .selectors(DiscoverySelectors.selectMethod(args[0], args[1])).build();
    SummaryGeneratingListener listener = new SummaryGeneratingListener();
    Launcher launcher = LauncherFactory.create();
    launcher.registerTestExecutionListeners(listener);
    launcher.execute(request);
    TestExecutionSummary summary = listener.getSummary();
    System.err.println("HBASE32 JUNIT found=" + summary.getTestsFoundCount()
      + " succeeded=" + summary.getTestsSucceededCount()
      + " failed=" + summary.getTestsFailedCount());
    summary.getFailures().forEach(failure -> failure.getException().printStackTrace(System.err));
    if (summary.getTestsFoundCount() != 1 || summary.getTestsFailedCount() != 0
        || summary.getTestsSucceededCount() != 1) System.exit(1);
  }
}
