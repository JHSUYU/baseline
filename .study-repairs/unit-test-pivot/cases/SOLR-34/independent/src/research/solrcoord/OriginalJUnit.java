package research.solrcoord;

import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

/** Runs one unchanged Solr test method with its original JUnit runner and rules. */
public final class OriginalJUnit {
  private OriginalJUnit() {}

  public static void main(String[] args) {
    int exit = 1;
    try {
      if (args.length != 2) throw new IllegalArgumentException("class and method required");
      Result result = new JUnitCore().run(Request.method(Class.forName(args[0]), args[1]));
      for (Failure failure : result.getFailures()) {
        System.err.println(failure.getDescription());
        failure.getException().printStackTrace(System.err);
      }
      System.out.println("SOLR_COORD_ORIGINAL_JUNIT ran=" + result.getRunCount()
          + " ignored=" + result.getIgnoreCount()
          + " failures=" + result.getFailureCount());
      exit = result.getRunCount() == 1 && result.getIgnoreCount() == 0
          && result.wasSuccessful() ? 0 : 1;
    } catch (Throwable failure) {
      failure.printStackTrace(System.err);
    }
    System.exit(exit);
  }
}
