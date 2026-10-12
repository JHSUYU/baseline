import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;
import org.junit.runner.notification.RunListener;
import java.util.concurrent.atomic.AtomicInteger;

/** Execute exactly one existing Hadoop JUnit method with its native fixture. */
public final class RunOriginalHdfsJUnit {
  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("test class and method required");
    AtomicInteger assumptions = new AtomicInteger();
    JUnitCore core = new JUnitCore();
    core.addListener(new RunListener() {
      @Override public void testAssumptionFailure(Failure failure) {
        assumptions.incrementAndGet();
        System.err.println("JUnit assumption: " + failure);
      }
    });
    Result result = core.run(Request.method(Class.forName(args[0]), args[1]));
    for (Failure failure : result.getFailures()) {
      System.err.println(failure);
      if (failure.getException() != null) failure.getException().printStackTrace(System.err);
    }
    System.out.println("JUnit original method: runs=" + result.getRunCount()
        + " failures=" + result.getFailureCount() + " ignored=" + result.getIgnoreCount()
        + " assumptions=" + assumptions.get());
    if (!result.wasSuccessful() || result.getRunCount() != 1 ||
        result.getIgnoreCount() != 0 || assumptions.get() != 0) System.exit(1);
  }
}
