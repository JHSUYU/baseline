package edu.uva.liftlab.mallory.hbase.pilot;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.launcher.Launcher;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;
import org.junit.platform.launcher.listeners.SummaryGeneratingListener;
import org.junit.platform.launcher.listeners.TestExecutionSummary;

/** Runs one unchanged Jupiter method while identifying its MiniCluster client. */
public final class SelectedJUnit {
  private SelectedJUnit() { }

  public static void main(String[] args) {
    if (args.length != 2) throw new IllegalArgumentException("class and method required");
    SummaryGeneratingListener listener = new SummaryGeneratingListener();
    Launcher launcher = LauncherFactory.create();
    launcher.registerTestExecutionListeners(listener);
    // The runner thread initiates Admin RPCs. Server threads use receiver aliases.
    try (Probe.NodeScope client = Probe.withNode("client", 0)) {
      launcher.execute(LauncherDiscoveryRequestBuilder.request()
          .selectors(DiscoverySelectors.selectMethod(args[0], args[1])).build());
    }
    TestExecutionSummary summary = listener.getSummary();
    System.err.println("MALLORY_JUNIT found=" + summary.getTestsFoundCount()
        + " succeeded=" + summary.getTestsSucceededCount()
        + " failed=" + summary.getTestsFailedCount());
    summary.getFailures().forEach(f -> f.getException().printStackTrace(System.err));
    System.exit(summary.getTestsFoundCount() >= 1 && summary.getTestsFailedCount() == 0 ? 0 : 1);
  }
}
