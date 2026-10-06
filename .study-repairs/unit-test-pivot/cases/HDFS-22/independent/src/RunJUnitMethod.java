import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

/** Executes the original JUnit method with its native fixture and rules. */
public final class RunJUnitMethod {
  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("test class and method required");
    Result result = new JUnitCore().run(Request.method(Class.forName(args[0]), args[1]));
    for (Failure failure : result.getFailures()) System.err.println(failure);
    System.out.println("JUnit original method: runs=" + result.getRunCount()
        + " failures=" + result.getFailureCount() + " ignored=" + result.getIgnoreCount());
    if (!result.wasSuccessful()) System.exit(1);
  }
}
