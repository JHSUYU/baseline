package edu.uva.liftlab.graphchecker.runtime;

import java.io.PrintWriter;
import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.launcher.Launcher;
import org.junit.platform.launcher.LauncherDiscoveryRequest;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;
import org.junit.platform.launcher.listeners.SummaryGeneratingListener;
import org.junit.platform.launcher.listeners.TestExecutionSummary;

/** Runs one unchanged HBase JUnit method inside the original session. */
public final class NativeHBaseJUnitRunner {
  private NativeHBaseJUnitRunner() { }

  public static void main(String[] args) throws Exception {
    if (args.length != 2) {
      throw new IllegalArgumentException("expected JUnit class and method");
    }
    String opened = ConcolicRegionRuntime.openWorkloadSession();
    if (!opened.isEmpty()) throw new IllegalStateException(opened);
    Object source = new Object();
    MessageDoors.registerNode(source, "HBASE", "CLIENT", args[0] + "#" + args[1]);
    HBaseRuntimeSource.registerAnchor(source);
    long request = MessageDoors.beginRequest(source, args[1]);
    long frame = Identity.enterFrame(args[1], source);
    TestExecutionSummary summary = null;
    Throwable failure = null;
    CausynthTraceRecorder.startRecording();
    try {
      LauncherDiscoveryRequest discovery = LauncherDiscoveryRequestBuilder.request()
          .selectors(DiscoverySelectors.selectMethod(args[0], args[1]))
          .build();
      Launcher launcher = LauncherFactory.create();
      SummaryGeneratingListener listener = new SummaryGeneratingListener();
      launcher.registerTestExecutionListeners(listener);
      launcher.execute(discovery);
      summary = listener.getSummary();
      summary.printFailuresTo(new PrintWriter(System.err, true));
    } catch (Throwable thrown) {
      failure = thrown;
      thrown.printStackTrace(System.err);
    } finally {
      CausynthTraceRecorder.stopRecording();
      Identity.exitFrame(frame);
      MessageDoors.endRequest(request, args[1]);
      String closed = ConcolicRegionRuntime.closeWorkloadSession();
      if (!closed.isEmpty()) throw new IllegalStateException(closed);
      RowRuntime.closeSession();
    }
    long run = summary == null ? 0 : summary.getTestsFoundCount();
    long passed = summary == null ? 0 : summary.getTestsSucceededCount();
    long failed = summary == null ? 1 : summary.getTestsFailedCount();
    long ignored = summary == null ? 0 : summary.getTestsSkippedCount();
    System.err.println("NATIVE_HBASE_JUNIT run=" + run + " failed=" + failed
        + " ignored=" + ignored + " exception=" + (failure != null));
    System.exit(failure == null && run == 1 && passed == 1 && failed == 0
        && ignored == 0 ? 0 : 1);
  }
}
