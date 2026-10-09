import org.apache.hadoop.hdfs.security.token.block.TestBlockToken;
import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

/** Run one unchanged upstream JUnit method, including its fixtures. */
public final class OriginalHdfs15Test {
  public static void main(String[] args) {
    if (args.length != 1) {
      throw new IllegalArgumentException("Expected one TestBlockToken method name");
    }
    Result result = new JUnitCore().run(Request.method(TestBlockToken.class, args[0]));
    for (Failure failure : result.getFailures()) {
      System.err.println(failure.getTrace());
    }
    System.out.println("JUNIT_RESULT method=" + args[0] + " count=" +
        result.getRunCount() + " failures=" + result.getFailureCount());
    if (!result.wasSuccessful() || result.getRunCount() != 1) {
      System.exit(1);
    }
  }
}
