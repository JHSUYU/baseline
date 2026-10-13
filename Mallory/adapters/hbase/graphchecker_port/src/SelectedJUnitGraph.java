package edu.uva.liftlab.mallory.hbase.graphchecker;

import edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors;
import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.launcher.Launcher;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;
import org.junit.platform.launcher.listeners.SummaryGeneratingListener;
import org.junit.platform.launcher.listeners.TestExecutionSummary;

/** Runs one unchanged HBase JUnit method, including MiniCluster startup, in one trace window. */
public final class SelectedJUnitGraph {
  private SelectedJUnitGraph() { }

  public static void main(String[] args) {
    if (args.length != 2) throw new IllegalArgumentException("class and method required");
    Object client = new Object();
    MessageDoors.registerNode(client, "junit", "client", args[0] + "#" + args[1]);
    MessageDoors.startRecording();
    MessageDoors.gap("STATE_VERSION_UNHOOKED", "HBase 2.6.6",
        "No atomic HBase metadata state key/version adapter is installed");
    long request = MessageDoors.beginRequest(client, args[1]);
    SummaryGeneratingListener listener = new SummaryGeneratingListener();
    try {
      Launcher launcher = LauncherFactory.create();
      launcher.registerTestExecutionListeners(listener);
      launcher.execute(LauncherDiscoveryRequestBuilder.request()
          .selectors(DiscoverySelectors.selectMethod(args[0], args[1])).build());
    } finally {
      MessageDoors.endRequest(request, args[1]);
      MessageDoors.stopRecording();
    }
    TestExecutionSummary summary = listener.getSummary();
    System.err.println("MALLORY_JUNIT found=" + summary.getTestsFoundCount()
        + " succeeded=" + summary.getTestsSucceededCount()
        + " failed=" + summary.getTestsFailedCount()
        + " containersFailed=" + summary.getContainersFailedCount());
    summary.getFailures().forEach(f -> f.getException().printStackTrace(System.err));
    // MiniCluster tests can leave non-daemon service threads behind.
    System.exit(summary.getTestsFoundCount() >= 1
        && summary.getTestsSucceededCount() >= 1
        && summary.getTestsFailedCount() == 0
        && summary.getContainersFailedCount() == 0 ? 0 : 1);
  }
}
