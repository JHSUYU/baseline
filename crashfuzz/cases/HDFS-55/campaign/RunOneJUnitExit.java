import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

/** Case-local JUnit wrapper: release JaCoCo after the one test finishes. */
public final class RunOneJUnitExit {
  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("class method");
    Result result = new JUnitCore().run(Request.method(Class.forName(args[0]), args[1]));
    for (Failure failure : result.getFailures()) System.err.println(failure);
    System.out.println("CONTROL original_junit_runs=" + result.getRunCount());
    System.out.println("CONTROL original_junit_failures=" + result.getFailureCount());
    System.out.flush();
    System.err.flush();
    System.exit(result.getRunCount() == 1 && result.wasSuccessful() ? 0 : 1);
  }
}
