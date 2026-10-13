package edu.uva.liftlab.graphchecker.runtime;

import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

/** One unchanged HDFS MiniDFSCluster JUnit in an original GraphChecker session. */
public final class NativeHdfsJUnitRunner {
  private NativeHdfsJUnitRunner() { }

  public static void main(String[] args) throws Exception {
    if (args.length != 2) {
      throw new IllegalArgumentException("expected original JUnit class and method");
    }
    String opened = ConcolicRegionRuntime.openWorkloadSession();
    if (!opened.isEmpty()) throw new IllegalStateException(opened);
    Object source = new Object();
    String selector = args[0] + "#" + args[1];
    MessageDoors.registerNode(source, "HDFS", "CLIENT", selector);
    HdfsRuntimeSource.registerAnchor(source);
    long request = MessageDoors.beginRequest(source, selector);
    long frame = Identity.enterFrame(selector, source);
    Result result = null;
    Throwable failure = null;
    CausynthTraceRecorder.startRecording();
    try {
      Class<?> testClass = Class.forName(args[0], true,
          Thread.currentThread().getContextClassLoader());
      result = new JUnitCore().run(Request.method(testClass, args[1]));
      for (Failure failed : result.getFailures()) {
        System.err.println(failed.getTrace());
      }
    } catch (Throwable thrown) {
      failure = thrown;
      thrown.printStackTrace(System.err);
    } finally {
      CausynthTraceRecorder.stopRecording();
      Identity.exitFrame(frame);
      MessageDoors.endRequest(request, selector);
      String closed = ConcolicRegionRuntime.closeWorkloadSession();
      if (!closed.isEmpty()) throw new IllegalStateException(closed);
      RowRuntime.closeSession();
    }
    int run = result == null ? 0 : result.getRunCount();
    int failed = result == null ? 1 : result.getFailureCount();
    int ignored = result == null ? 0 : result.getIgnoreCount();
    System.err.println("NATIVE_HDFS_JUNIT run=" + run + " failed=" + failed
        + " ignored=" + ignored + " exception=" + (failure != null));
    System.exit(failure == null && run == 1 && failed == 0 && ignored == 0 ? 0 : 1);
  }
}
