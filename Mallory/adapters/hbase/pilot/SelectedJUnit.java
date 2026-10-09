package edu.uva.liftlab.mallory.hbase.pilot;

import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.launcher.Launcher;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;
import org.junit.platform.launcher.listeners.SummaryGeneratingListener;
import org.junit.platform.launcher.listeners.TestExecutionSummary;

/** Selects one unchanged original Jupiter test method in a fresh JVM. */
public final class SelectedJUnit {
  public static void main(String[] args) {
    if (args.length != 2) throw new IllegalArgumentException("class and method required");
    SummaryGeneratingListener listener = new SummaryGeneratingListener();
    Launcher launcher = LauncherFactory.create();
    launcher.registerTestExecutionListeners(listener);
    launcher.execute(LauncherDiscoveryRequestBuilder.request()
        .selectors(DiscoverySelectors.selectMethod(args[0], args[1])).build());
    TestExecutionSummary summary = listener.getSummary();
    System.err.println("MALLORY_JUNIT found=" + summary.getTestsFoundCount()
        + " succeeded=" + summary.getTestsSucceededCount()
        + " failed=" + summary.getTestsFailedCount());
    summary.getFailures().forEach(f -> f.getException().printStackTrace(System.err));
    // MiniCluster tests can leave non-daemon service threads after JUnit has completed.
    // Terminate the fresh per-trial JVM from the authoritative JUnit summary; this still
    // runs JVM shutdown hooks, including the event recorder's final flush.
    // A selected @TestTemplate method can expand to multiple invocations.
    System.exit(summary.getTestsFoundCount() >= 1 && summary.getTestsFailedCount() == 0 ? 0 : 1);
  }
}
