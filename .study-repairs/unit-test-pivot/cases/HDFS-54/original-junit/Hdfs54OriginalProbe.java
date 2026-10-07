import java.io.EOFException;
import java.io.FileWriter;
import java.io.IOException;
import java.io.PrintWriter;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;
import org.apache.hadoop.hdfs.protocol.LocatedStripedBlock;
import org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException;
import org.apache.hadoop.hdfs.protocol.DatanodeInfo;

/** Native checksum-RPC fault points for one unchanged TestFileChecksum JUnit. */
public final class Hdfs54OriginalProbe {
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final String TRACE = System.getProperty("hdfs54.original.trace");
  private static final List<String[]> PLAN = readPlan();
  private static final Map<String, Integer> ORDINALS = new HashMap<>();
  private static final ThreadLocal<Context> CONTEXT = new ThreadLocal<>();
  private static int nextFault = 0;

  private Hdfs54OriginalProbe() { }

  private static final class Context {
    final String file;
    final int group;
    final int role;
    final long blockId;
    final String dnUuid;

    Context(String file, int group, int role, long blockId, String dnUuid) {
      this.file = file;
      this.group = group;
      this.role = role;
      this.blockId = blockId;
      this.dnUuid = dnUuid;
    }
  }

  private static List<String[]> readPlan() {
    List<String[]> plan = new ArrayList<>();
    String path = System.getProperty("hdfs54.original.plan");
    if (path == null) return plan;
    try {
      for (String line : Files.readAllLines(Paths.get(path), StandardCharsets.UTF_8)) {
        if (line.trim().isEmpty()) continue;
        String[] fields = line.split("\t", -1);
        if (fields.length != 6) throw new IllegalArgumentException("invalid plan row");
        plan.add(fields);
      }
    } catch (IOException error) {
      throw new RuntimeException("cannot read HDFS-54 original plan", error);
    }
    return plan;
  }

  private static String escape(String value) {
    return value.replace("\\", "\\\\").replace("\"", "\\\"")
        .replace("\n", "\\n").replace("\r", "\\r");
  }

  private static synchronized void record(String payload) {
    if (TRACE == null) return;
    try (PrintWriter out = new PrintWriter(new FileWriter(TRACE, true))) {
      out.println("{\"seq\":" + SEQUENCE.incrementAndGet() + ",\"thread\":\""
          + escape(Thread.currentThread().getName()) + "\"," + payload + "}");
    } catch (IOException error) {
      throw new RuntimeException("HDFS-54 trace write failed", error);
    }
  }

  public static void enterRpc(String file, Object blockGroupObject,
                              Object datanodeObject, int group) {
    LocatedStripedBlock blockGroup = (LocatedStripedBlock) blockGroupObject;
    DatanodeInfo datanode = (DatanodeInfo) datanodeObject;
    int role = -1;
    DatanodeInfo[] locations = blockGroup.getLocations();
    for (int i = 0; i < locations.length; i++) {
      if (locations[i].getDatanodeUuid().equals(datanode.getDatanodeUuid())) {
        role = i;
        break;
      }
    }
    CONTEXT.set(new Context(file, group, role,
        blockGroup.getBlock().getBlockId(), datanode.getDatanodeUuid()));
  }

  public static synchronized void point(String site) throws IOException {
    Context ctx = CONTEXT.get();
    if (ctx == null) throw new IllegalStateException("checksum RPC context absent");
    String identity = ctx.file + "|" + ctx.group + "|" + ctx.role + "|" + site;
    int ordinal = ORDINALS.containsKey(identity) ? ORDINALS.get(identity) + 1 : 1;
    ORDINALS.put(identity, ordinal);
    String fields = "\"file\":\"" + escape(ctx.file) + "\",\"blockGroup\":"
        + ctx.group + ",\"dnRole\":" + ctx.role + ",\"blockId\":"
        + ctx.blockId + ",\"dnUuid\":\"" + escape(ctx.dnUuid)
        + "\",\"site\":\"" + site + "\",\"ordinal\":" + ordinal;
    record("\"event\":\"IO_OBSERVED\"," + fields);
    if (nextFault >= PLAN.size()) return;
    String[] fault = PLAN.get(nextFault);
    if (!fault[0].equals(ctx.file) || Integer.parseInt(fault[1]) != ctx.group
        || Integer.parseInt(fault[2]) != ctx.role || !fault[3].equals(site)
        || Integer.parseInt(fault[4]) != ordinal) return;
    String type = fault[5];
    record("\"event\":\"FAULT_MATCHED\"," + fields + ",\"type\":\""
        + type + "\",\"planIndex\":" + nextFault);
    record("\"event\":\"FAULT_APPLIED\"," + fields + ",\"type\":\""
        + type + "\",\"planIndex\":" + nextFault);
    nextFault++;
    if (type.equals("IOException")) throw new IOException("HDFS54 original injected RPC error");
    if (type.equals("EOFException")) throw new EOFException("HDFS54 original injected RPC EOF");
    if (type.equals("SocketTimeoutException")) {
      throw new SocketTimeoutException("HDFS54 original injected RPC timeout");
    }
    if (type.equals("InvalidEncryptionKeyException")) {
      throw new InvalidEncryptionKeyException("HDFS54 original injected stale key response");
    }
    throw new IllegalArgumentException("unsupported HDFS54 fault type " + type);
  }

  public static void target(boolean completed, String file) {
    record("\"event\":\"TARGET_CHECK\",\"siteId\":\"FileChecksumHelper"
        + "$StripedFileNonStripedChecksumComputer.checksumBlocks#L629\",\"file\":\""
        + escape(file) + "\",\"completed\":" + completed);
  }

  public static void caught(Throwable error, String file) {
    record("\"event\":\"TARGET_IO_CATCH\",\"siteId\":\"FileChecksumHelper"
        + "$StripedFileNonStripedChecksumComputer.checksumBlockGroup#L669\",\"file\":\""
        + escape(file) + "\",\"exception\":\""
        + escape(error.getClass().getName()) + "\"");
  }
}
