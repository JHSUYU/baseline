import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

/** Runs the unmodified Hadoop distribution's single original JUnit method. */
public final class RunOriginalJUnit {
  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("class and method required");
    Class<?> testClass = Class.forName(args[0]);
    Result result = new JUnitCore().run(Request.method(testClass, args[1]));
    for (Failure failure : result.getFailures()) System.err.println(failure);
    System.out.println("Original JUnit " + args[1] + ": runs=" + result.getRunCount()
        + " failures=" + result.getFailureCount()
        + " ignored=" + result.getIgnoreCount());
    if (result.getRunCount() != 1 || !result.wasSuccessful()) System.exit(1);
  }
}
