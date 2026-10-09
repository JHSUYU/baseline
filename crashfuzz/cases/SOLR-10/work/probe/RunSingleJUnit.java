package baseline.solr103940;

import org.junit.runner.JUnitCore;
import org.junit.runner.Description;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;
import org.junit.runner.notification.RunListener;

public final class RunSingleJUnit {
  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("class method");
    Class<?> testClass = Class.forName(args[0]);
    JUnitCore core = new JUnitCore();
    core.addListener(new RunListener() {
      @Override public void testStarted(Description description) {
        System.out.println("SOLR103940_JUNIT_STARTED " + description);
      }
      @Override public void testAssumptionFailure(Failure failure) {
        System.out.println("SOLR103940_JUNIT_ASSUMPTION " + failure);
      }
    });
    Result result = core.run(Request.method(testClass, args[1]));
    for (Failure failure : result.getFailures()) System.err.println("SOLR103940_JUNIT_FAILURE " + failure);
    System.out.println("SOLR103940_JUNIT_RESULT run=" + result.getRunCount() + " failures=" + result.getFailureCount() + " ignored=" + result.getIgnoreCount());
    if (!result.wasSuccessful()) System.exit(1);
  }
}
