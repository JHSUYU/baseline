import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

/** Select one parameter of the released, unchanged Hadoop test class. */
public final class RunOriginalHdfs54JUnit {
  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("class method");
    Result result = new JUnitCore().run(Request.method(Class.forName(args[0]), args[1]));
    for (Failure failure : result.getFailures()) System.err.println(failure);
    System.out.println("Original JUnit runs=" + result.getRunCount()
        + " failures=" + result.getFailureCount()
        + " ignored=" + result.getIgnoreCount());
    if (result.getRunCount() != 1 || !result.wasSuccessful()) System.exit(1);
  }
}
