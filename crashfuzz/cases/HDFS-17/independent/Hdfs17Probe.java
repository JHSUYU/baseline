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

/** Case-local trace and ordered I/O exception plan for the original JUnit. */
public final class Hdfs17Probe {
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final String TRACE = System.getProperty("hdfs17.trace");
  private static final Map<String, String> POOLS = new HashMap<>();
  private static final Map<String, String> DATANODES = new HashMap<>();
  private static final Map<String, Integer> ORDINALS = new HashMap<>();
  private static final List<String[]> PLAN = readPlan();
  private static int nextFault = 0;

  private Hdfs17Probe() { }

  private static List<String[]> readPlan() {
    List<String[]> plan = new ArrayList<>();
    String path = System.getProperty("hdfs17.plan");
    if (path == null) return plan;
    try {
      for (String line : Files.readAllLines(Paths.get(path), StandardCharsets.UTF_8)) {
        if (line.trim().isEmpty()) continue;
        String[] fields = line.split("\t", -1);
        if (fields.length != 5) throw new IllegalArgumentException("invalid HDFS-17 plan row");
        plan.add(fields);
      }
    } catch (IOException error) {
      throw new RuntimeException("cannot read HDFS-17 fault plan", error);
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
      throw new RuntimeException("HDFS-17 trace write failed", error);
    }
  }

  private static String logicalPool(String physicalPool) {
    String logical = POOLS.get(physicalPool);
    if (logical == null) {
      logical = "hdfs/blockpool/" + POOLS.size();
      POOLS.put(physicalPool, logical);
    }
    return logical;
  }

  public static synchronized void targetCheck(boolean condition, long storedBlockId,
      long reportedBlockId, String replicaState) {
    String fields = "\"siteId\":\"BlockManager.StatefulBlockInfo#L2851\","
        + "\"storedBlockId\":" + storedBlockId + ","
        + "\"reportedBlockId\":" + reportedBlockId + ","
        + "\"reportedState\":\"" + escape(replicaState) + "\","
        + "\"condition\":" + condition;
    record("\"event\":\"TARGET_CHECK\"," + fields);
    // Preconditions.checkArgument(false) immediately throws the selected
    // IllegalArgumentException; there is no intervening user instruction.
    if (!condition) {
      record("\"event\":\"TARGET_THROW\"," + fields
          + ",\"exception\":\"java.lang.IllegalArgumentException\"");
    }
  }

  /** Called immediately before the released DataNode block-report RPC call. */
  public static synchronized void io(String marker, String site,
      String physicalPool, String datanodeUuid) throws IOException {
    String logicalDn = DATANODES.get(datanodeUuid);
    if (logicalDn == null) {
      logicalDn = "dn/" + DATANODES.size();
      DATANODES.put(datanodeUuid, logicalDn);
    }
    String source = logicalPool(physicalPool) + "/" + logicalDn;
    String identity = marker + "|" + site + "|" + source;
    int ordinal = ORDINALS.containsKey(identity) ? ORDINALS.get(identity) + 1 : 1;
    ORDINALS.put(identity, ordinal);
    String occurrence = source + "/" + site;
    String fields = "\"marker\":\"" + escape(marker) + "\",\"siteId\":\""
        + escape(site) + "\",\"sourceKey\":\"" + escape(source)
        + "\",\"occurrence\":\"" + escape(occurrence)
        + "\",\"physicalResource\":\"" + escape(physicalPool)
        + "\",\"datanodeUuid\":\"" + escape(datanodeUuid)
        + "\",\"hitOrdinal\":" + ordinal;
    record("\"event\":\"FAULT_POINT_OBSERVED\"," + fields);
    if (nextFault >= PLAN.size()) return;
    String[] requested = PLAN.get(nextFault);
    if (!requested[0].equals(marker) || !requested[1].equals(site)
        || !requested[2].equals(source)
        || Integer.parseInt(requested[3]) != ordinal) return;
    String kind = requested[4];
    record("\"event\":\"FAULT_MATCHED\"," + fields
        + ",\"faultType\":\"" + escape(kind) + "\",\"planIndex\":" + nextFault);
    record("\"event\":\"FAULT_APPLIED\"," + fields
        + ",\"faultType\":\"" + escape(kind) + "\",\"planIndex\":" + nextFault);
    nextFault++;
    if (kind.equals("EOFException")) throw new EOFException("HDFS-17 injected EOF at " + site);
    if (kind.equals("SocketTimeoutException")) {
      throw new SocketTimeoutException("HDFS-17 injected timeout at " + site);
    }
    if (kind.equals("IOException")) throw new IOException("HDFS-17 injected I/O at " + site);
    throw new IllegalArgumentException("unsupported HDFS-17 fault type " + kind);
  }
}
