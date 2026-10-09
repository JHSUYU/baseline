import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

/** Runs one unchanged released MiniDFSCluster JUnit method and fixture. */
public final class OriginalHdfs40Test {
  public static void main(String[] args) throws Throwable {
    if (args.length != 2) {
      throw new IllegalArgumentException("Expected original class and method");
    }
    Class<?> owner = Class.forName(args[0]);
    Result result = new JUnitCore().run(Request.method(owner, args[1]));
    if (result.getRunCount() != 1 || result.getIgnoreCount() != 0) {
      throw new AssertionError("Expected one JUnit method, got run=" +
          result.getRunCount() + ", ignored=" + result.getIgnoreCount());
    }
    for (Failure failure : result.getFailures()) {
      throw failure.getException();
    }
    System.out.println("ORIGINAL_JUNIT_PASS " + args[0] + "#" + args[1]);
  }
}
