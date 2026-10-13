package edu.uva.liftlab.mallory.adapters.hdfs.graphchecker;

import edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors;
import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

/** Runs exactly one original JUnit method with a GraphChecker trace window. */
public final class RunOriginalJUnit {
  private RunOriginalJUnit() { }

  public static void main(String[] args) throws Exception {
    if (args.length != 2) {
      throw new IllegalArgumentException("expected <original-test-class> <method>");
    }
    Class<?> test = Class.forName(args[0]);
    Object anchor = new Object();
    String selected = args[0] + "#" + args[1];
    MessageDoors.registerNode(anchor, "EXTERNAL_APP", "CLIENT", selected);
    MessageDoors.startRecording();
    long root = MessageDoors.beginRequest(anchor, selected);
    Result result;
    try {
      result = new JUnitCore().run(Request.method(test, args[1]));
    } finally {
      MessageDoors.endRequest(root, selected);
      MessageDoors.stopRecording();
    }
    for (Failure failure : result.getFailures()) {
      System.err.println(failure.getTrace());
    }
    System.out.println("JUNIT_RUNS=" + result.getRunCount()
        + " JUNIT_FAILURES=" + result.getFailureCount()
        + " JUNIT_IGNORED=" + result.getIgnoreCount());
    if (result.getRunCount() != 1 || result.getIgnoreCount() != 0
        || result.getFailureCount() != 0) System.exit(1);
  }
}
