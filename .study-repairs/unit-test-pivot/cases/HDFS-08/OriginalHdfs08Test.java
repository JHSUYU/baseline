import org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager;
import org.junit.Test;
import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

/** Runs the unchanged upstream JUnit method through JUnit's own rules. */
public final class OriginalHdfs08Test {
  @Test
  public void originalSingleWriter() throws Throwable {
    String method = System.getProperty("hdfs08.test.method",
        "testSingleWriter");
    Result result = new JUnitCore().run(Request.method(
        TestQuorumJournalManager.class, method));
    if (result.getRunCount() != 1 || result.getIgnoreCount() != 0) {
      throw new AssertionError("Expected one original JUnit method, got run="
          + result.getRunCount() + ", ignored=" + result.getIgnoreCount());
    }
    for (Failure failure : result.getFailures()) {
      throw failure.getException();
    }
  }
}
