import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

/** Runs one original cluster JUnit method; '-' selects a non-parameterized test. */
public final class RunOriginalJUnit {
  public static void main(String[] args) throws Exception {
    if (args.length != 3) {
      throw new IllegalArgumentException("class, method, parameter index required");
    }
    Class<?> testClass = Class.forName(args[0]);
    String invocation = args[2].equals("-") ? args[1] : args[1] + "[" + args[2] + "]";
    Result result = new JUnitCore().run(Request.method(testClass, invocation));
    for (Failure failure : result.getFailures()) {
      System.err.println(failure);
    }
    System.out.println("Original JUnit " + invocation + ": runs=" + result.getRunCount()
        + " failures=" + result.getFailureCount() + " ignored=" + result.getIgnoreCount());
    if (result.getRunCount() != 1 || !result.wasSuccessful()) {
      System.exit(1);
    }
  }
}
