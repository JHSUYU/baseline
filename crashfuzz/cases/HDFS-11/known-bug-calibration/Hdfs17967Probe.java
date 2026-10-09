import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import org.apache.hadoop.hdfs.protocol.DatanodeID;
import org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException;

/** Records and optionally faults the real outbound SASL I/O boundary. */
public final class Hdfs17967Probe {
  private static final String TRACE = System.getProperty("hdfs17967.trace", "");
  private static final String PLAN = System.getProperty("hdfs17967.plan", "");
  private static int writeHits;
  private static int replaceHits;
  private static long sequence;

  private Hdfs17967Probe() { }

  private static void emit(String kind, String path, int hit, DatanodeID target)
      throws IOException {
    if (TRACE.isEmpty()) return;
    String row = (++sequence) + "\t" + kind + "\t" + path + "\t" + hit
        + "\t" + String.valueOf(target) + "\n";
    try (FileOutputStream out = new FileOutputStream(TRACE, true)) {
      out.write(row.getBytes(StandardCharsets.UTF_8));
    }
  }

  public static synchronized void before(DatanodeID target) throws IOException {
    String path = "other";
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (!frame.getClassName().equals(
          "org.apache.hadoop.hdfs.server.datanode.DataXceiver")) continue;
      if (frame.getMethodName().equals("writeBlock")) path = "writeBlock";
      if (frame.getMethodName().equals("replaceBlock")) path = "replaceBlock";
    }
    if (path.equals("other")) return;
    int hit = path.equals("writeBlock") ? ++writeHits : ++replaceHits;
    emit("SASL_ATTEMPT", path, hit, target);
    if (PLAN.equals(path + ":" + hit)) {
      emit("FAULT_APPLIED", path, hit, target);
      throw new InvalidEncryptionKeyException(
          "HDFS-17967 control at outbound SASL setup " + path + ":" + hit);
    }
  }
}
