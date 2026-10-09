import org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManager;
import org.apache.hadoop.hdfs.qjournal.server.JournalFaultInjector;
import org.apache.hadoop.hdfs.hdfs08independent.Probe;
import java.io.IOException;
import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;

/** Runs one unchanged upstream JUnit method and its MiniJournalCluster fixture. */
public final class OriginalHdfs08IndependentTest {
  public static void main(String[] args) throws Throwable {
    if (args.length != 1) {
      throw new IllegalArgumentException("Expected one original test method");
    }
    if (Boolean.getBoolean("hdfs08.independent.paxos")) {
      // The released Journal already has test hooks immediately before and
      // after its atomic Paxos-file persistence operation.  The original
      // JUnit method and production Journal bytecode remain unchanged.
      JournalFaultInjector.instance = new JournalFaultInjector() {
        @Override
        public void beforePersistPaxosData() throws IOException {
          Probe.paxosIo("before");
        }

        @Override
        public void afterPersistPaxosData() throws IOException {
          Probe.paxosIo("after");
        }
      };
    }
    Result result = new JUnitCore().run(Request.method(
        TestQuorumJournalManager.class, args[0]));
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
