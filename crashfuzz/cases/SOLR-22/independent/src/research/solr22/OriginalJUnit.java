package research.solr22;

import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

/** Runs exactly the original JUnit method with its own runner, rules, and setup. */
public final class OriginalJUnit {
  private OriginalJUnit() {}

  public static void main(String[] args) {
    int exit = 1;
    try {
      if (args.length != 2) throw new IllegalArgumentException("class and method required");
      Class<?> testClass = Class.forName(args[0]);
      Result result = new JUnitCore().run(Request.method(testClass, args[1]));
      for (Failure failure : result.getFailures()) {
        System.err.println(failure.getDescription());
        failure.getException().printStackTrace(System.err);
      }
      System.out.println("SOLR22_ORIGINAL_JUNIT ran=" + result.getRunCount()
          + " ignored=" + result.getIgnoreCount()
          + " failures=" + result.getFailureCount());
      exit = result.getRunCount() == 1 && result.getIgnoreCount() == 0
          && result.wasSuccessful() ? 0 : 1;
    } catch (Throwable failure) {
      failure.printStackTrace(System.err);
    } finally {
      Probe.close();
    }
    System.exit(exit);
  }
}
