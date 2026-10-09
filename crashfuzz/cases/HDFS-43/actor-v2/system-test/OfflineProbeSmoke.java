import java.io.IOException;
import org.apache.hadoop.hdfs.hdfs43actor.Probe;

/** Synthetic probe protocol smoke; never starts MiniDFSCluster or counts as a trial. */
public final class OfflineProbeSmoke {
  public static void main(String[] ignored) throws Exception {
    Probe.registerNameNode(12345);
    Probe.markPhase("secondTruncate");
    Probe.truncateContext("/testTruncateTwiceTogether/file", 398L);
    try {
      Probe.rpcResponse(7, new byte[] {1, 2, 3},
          "localhost/127.0.0.1:12345", 12345);
      throw new AssertionError("synthetic selector did not inject");
    } catch (IOException expected) {
      if (!expected.getMessage().startsWith("HDFS-43 injected at")) {
        throw expected;
      }
    } finally {
      Probe.clearContext();
    }
    Probe.guard("/testTruncateTwiceTogether/file", 1073741825L,
        1073741825L, "UNDER_RECOVERY", 398L, 399L);
  }
}
