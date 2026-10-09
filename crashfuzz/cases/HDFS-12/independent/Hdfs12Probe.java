import java.io.FileWriter;
import java.io.EOFException;
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

/** Minimal production target recorder; no static region or graph input. */
public final class Hdfs12Probe {
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final String TRACE = System.getProperty("hdfs12.trace");
  private static final String SOURCE = "hdfs/datanode/0";
  private static final Map<String, Integer> ORDINALS = new HashMap<>();
  private static final List<String[]> PLAN = readPlan();
  private static int nextFault = 0;

  private Hdfs12Probe() { }

  private static List<String[]> readPlan() {
    List<String[]> plan = new ArrayList<>();
    String path = System.getProperty("hdfs12.plan");
    if (path == null) return plan;
    try {
      for (String line : Files.readAllLines(Paths.get(path), StandardCharsets.UTF_8)) {
        if (line.trim().isEmpty()) continue;
        String[] fields = line.split("\\t", -1);
        if (fields.length != 5) throw new IllegalArgumentException("invalid HDFS-12 plan row");
        plan.add(fields);
      }
    } catch (IOException exception) {
      throw new RuntimeException("cannot read HDFS-12 plan", exception);
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
    } catch (IOException exception) {
      throw new RuntimeException("HDFS-12 target trace write failed", exception);
    }
  }

  public static void targetCheck(Object key, int keyId) {
    record("\"event\":\"TARGET_CHECK\",\"siteId\":\"BlockTokenSecretManager.retrievePassword#L511\","
        + "\"keyId\":" + keyId + ",\"keyPresent\":" + (key != null));
  }

  public static void targetThrow(Throwable error) {
    record("\"event\":\"TARGET_THROW\",\"siteId\":\"BlockTokenSecretManager.retrievePassword#L514\","
        + "\"exception\":\"" + escape(error.getClass().getName()) + "\"");
  }

  /** Called immediately before a released-class socket read call site. */
  public static synchronized void io(String marker, String site) throws IOException {
    String identity = marker + "|" + site + "|" + SOURCE;
    int ordinal = ORDINALS.containsKey(identity) ? ORDINALS.get(identity) + 1 : 1;
    ORDINALS.put(identity, ordinal);
    String occurrence = SOURCE + "/" + site;
    String fields = "\"marker\":\"" + escape(marker) + "\",\"siteId\":\""
        + escape(site) + "\",\"sourceKey\":\"" + SOURCE
        + "\",\"occurrence\":\"" + escape(occurrence)
        + "\",\"hitOrdinal\":" + ordinal;
    record("\"event\":\"FAULT_POINT_OBSERVED\"," + fields);
    if (nextFault >= PLAN.size()) return;
    String[] requested = PLAN.get(nextFault);
    if (!requested[0].equals(marker) || !requested[1].equals(site)
        || !requested[2].equals(SOURCE)
        || Integer.parseInt(requested[3]) != ordinal) return;
    String kind = requested[4];
    record("\"event\":\"FAULT_MATCHED\"," + fields
        + ",\"faultType\":\"" + escape(kind) + "\",\"planIndex\":" + nextFault);
    record("\"event\":\"FAULT_APPLIED\"," + fields
        + ",\"faultType\":\"" + escape(kind) + "\",\"planIndex\":" + nextFault);
    nextFault++;
    if (kind.equals("EOFException")) throw new EOFException("HDFS-12 injected EOF at " + site);
    if (kind.equals("SocketTimeoutException")) {
      throw new SocketTimeoutException("HDFS-12 injected timeout at " + site);
    }
    if (kind.equals("IOException")) throw new IOException("HDFS-12 injected I/O at " + site);
    throw new IllegalArgumentException("unsupported HDFS-12 fault type " + kind);
  }
}
