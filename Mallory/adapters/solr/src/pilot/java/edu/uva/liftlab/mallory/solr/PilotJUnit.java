package edu.uva.liftlab.mallory.solr;

import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.runner.Description;
import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;
import org.junit.runner.notification.RunListener;

/** Runs one existing Solr test method, including its original repetitions and assertions. */
public final class PilotJUnit {
  private PilotJUnit() { }

  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("test class and method required");
    Class<?> testClass = Class.forName(args[0]);
    JUnitCore runner = new JUnitCore();
    AtomicBoolean assumed = new AtomicBoolean();
    runner.addListener(new RunListener() {
      @Override public void testStarted(Description description) {
        System.out.println("MALLORY_TEST_STARTED " + description);
      }
      @Override public void testAssumptionFailure(Failure failure) {
        assumed.set(true);
        System.out.println("MALLORY_TEST_ASSUMPTION " + failure);
      }
    });
    Result result = runner.run(Request.method(testClass, args[1]));
    for (Failure failure : result.getFailures())
      System.err.println("MALLORY_TEST_FAILURE " + failure);
    System.out.println("MALLORY_TEST_RESULT run=" + result.getRunCount()
        + " failures=" + result.getFailureCount() + " ignored=" + result.getIgnoreCount());
    if (!result.wasSuccessful() || result.getRunCount() < 1
        || result.getIgnoreCount() != 0 || assumed.get())
      System.exit(1);
  }
}
