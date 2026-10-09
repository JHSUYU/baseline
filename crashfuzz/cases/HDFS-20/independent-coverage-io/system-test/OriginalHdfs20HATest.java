import org.apache.hadoop.hdfs.server.namenode.ha.TestHAStateTransitions;
import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

/** Runs one unchanged released MiniDFSCluster JUnit method and fixture. */
public final class OriginalHdfs20HATest {
  public static void main(String[] args) throws Throwable {
    if (args.length != 1) {
      throw new IllegalArgumentException("Expected one original method name");
    }
    Result result = new JUnitCore().run(Request.method(
        TestHAStateTransitions.class, args[0]));
    if (result.getRunCount() != 1 || result.getIgnoreCount() != 0) {
      throw new AssertionError("Expected one JUnit method, got run=" +
          result.getRunCount() + ", ignored=" + result.getIgnoreCount());
    }
    for (Failure failure : result.getFailures()) {
      throw failure.getException();
    }
    System.out.println("ORIGINAL_JUNIT_PASS " + args[0]);
  }
}
