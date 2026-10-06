package research.solr13;

import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;
import org.junit.runner.notification.RunListener;
import org.junit.runner.Description;

/** Execute one unchanged original JUnit method with its original rules. */
public final class OriginalJUnit {
  private OriginalJUnit() {}

  public static void main(String[] args) throws ClassNotFoundException {
    if (args.length != 2) {
      throw new IllegalArgumentException("class and method required");
    }
    JUnitCore junit = new JUnitCore();
    junit.addListener(new RunListener() {
      @Override public void testStarted(Description description) {
        System.out.println("SOLR13_TEST_STARTED " + description);
      }
      @Override public void testAssumptionFailure(Failure failure) {
        System.err.println("SOLR13_ASSUMPTION_FAILURE " + failure);
      }
    });
    Result result = junit.run(Request.method(Class.forName(args[0]), args[1]));
    for (Failure failure : result.getFailures()) {
      System.err.println(failure.getDescription());
      failure.getException().printStackTrace(System.err);
    }
    System.out.println("SOLR13_ORIGINAL_JUNIT ran=" + result.getRunCount()
        + " ignored=" + result.getIgnoreCount()
        + " failures=" + result.getFailureCount());
    System.exit(result.getRunCount() == 1 && result.getIgnoreCount() == 0
        && result.wasSuccessful() ? 0 : 1);
  }
}
