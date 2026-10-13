package edu.uva.liftlab.mallory.solr.graphchecker;

import edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.runner.Description;
import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;
import org.junit.runner.notification.RunListener;

/** Runs one original Solr JUnit method under its own JUnit runner. */
public final class GraphJUnit {
  private GraphJUnit() { }

  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("test class and method required");
    Class<?> testClass = Class.forName(args[0]);
    Object workload = new Object();
    String api = args[0] + "#" + args[1];
    MessageDoors.registerNode(workload, "EXTERNAL_APP", "CLIENT", api);
    AtomicBoolean assumed = new AtomicBoolean();
    AtomicLong scope = new AtomicLong();
    JUnitCore runner = new JUnitCore();
    runner.addListener(new RunListener() {
      @Override public void testStarted(Description description) {
        scope.set(MessageDoors.beginRequest(workload, api));
        System.out.println("MALLORY_GRAPH_TEST_STARTED " + description);
      }

      @Override public void testFinished(Description description) {
        long token = scope.getAndSet(0L);
        if (token != 0L) MessageDoors.endRequest(token, api);
      }

      @Override public void testAssumptionFailure(Failure failure) {
        assumed.set(true);
        System.out.println("MALLORY_GRAPH_TEST_ASSUMPTION " + failure);
      }
    });
    // JUnit may start @BeforeClass cluster fixtures before testStarted fires.
    // Keep one trace window across the entire original JUnit invocation.
    MessageDoors.startRecording();
    Result result;
    try {
      result = runner.run(Request.method(testClass, args[1]));
    } finally {
      long token = scope.getAndSet(0L);
      if (token != 0L) MessageDoors.endRequest(token, api);
      MessageDoors.stopRecording();
    }
    for (Failure failure : result.getFailures()) {
      System.err.println("MALLORY_GRAPH_TEST_FAILURE " + failure);
      failure.getException().printStackTrace(System.err);
    }
    System.out.println("MALLORY_GRAPH_TEST_RESULT run=" + result.getRunCount()
        + " failures=" + result.getFailureCount() + " ignored=" + result.getIgnoreCount());
    System.exit(result.wasSuccessful() && result.getRunCount() == 1
        && result.getIgnoreCount() == 0 && !assumed.get() ? 0 : 1);
  }
}
