package edu.uva.liftlab.mallory.hbase.pilot;

import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.launcher.Launcher;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;
import org.junit.platform.launcher.listeners.SummaryGeneratingListener;
import org.junit.platform.launcher.listeners.TestExecutionSummary;

/** Selects one existing Jupiter method by its declared parameter types. */
public final class SelectedJUnitSignature {
  public static void main(String[] args) {
    if (args.length != 3)
      throw new IllegalArgumentException("class, method, and parameter signature required");
    SummaryGeneratingListener listener = new SummaryGeneratingListener();
    Launcher launcher = LauncherFactory.create();
    launcher.registerTestExecutionListeners(listener);
    launcher.execute(LauncherDiscoveryRequestBuilder.request()
        .selectors(DiscoverySelectors.selectMethod(args[0], args[1], args[2])).build());
    TestExecutionSummary summary = listener.getSummary();
    System.err.println("MALLORY_JUNIT found=" + summary.getTestsFoundCount()
        + " succeeded=" + summary.getTestsSucceededCount()
        + " failed=" + summary.getTestsFailedCount());
    summary.getFailures().forEach(f -> f.getException().printStackTrace(System.err));
    System.exit(summary.getTestsFoundCount() >= 1 && summary.getTestsFailedCount() == 0 ? 0 : 1);
  }
}
