package baseline.solr07;

import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

public final class RunSingleJUnit {
  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("class method");
    Class<?> testClass = Class.forName(args[0]);
    Result result = new JUnitCore().run(Request.method(testClass, args[1]));
    for (Failure failure : result.getFailures()) System.err.println("SOLR05_JUNIT_FAILURE " + failure);
    System.out.println("SOLR05_JUNIT_RESULT run=" + result.getRunCount() + " failures=" + result.getFailureCount() + " ignored=" + result.getIgnoreCount());
    if (!result.wasSuccessful()) System.exit(1);
  }
}
