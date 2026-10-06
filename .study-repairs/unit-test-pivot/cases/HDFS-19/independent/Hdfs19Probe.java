import java.io.FileWriter;
import java.io.File;
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
public final class Hdfs19Probe {
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final String TRACE = System.getProperty("hdfs19.trace");
  private static final Map<String, String> BLOCK_POOLS = new HashMap<>();
  private static final Map<String, Integer> ORDINALS = new HashMap<>();
  private static final List<String[]> PLAN = readPlan();
  private static int nextFault = 0;

  private Hdfs19Probe() { }

  private static List<String[]> readPlan() {
    List<String[]> plan = new ArrayList<>();
    String path = System.getProperty("hdfs19.plan");
    if (path == null) return plan;
    try {
      for (String line : Files.readAllLines(Paths.get(path), StandardCharsets.UTF_8)) {
        if (line.trim().isEmpty()) continue;
        String[] fields = line.split("\\t", -1);
        if (fields.length != 5) throw new IllegalArgumentException("invalid HDFS-19 plan row");
        plan.add(fields);
      }
    } catch (IOException exception) {
      throw new RuntimeException("cannot read HDFS-19 plan", exception);
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
      throw new RuntimeException("HDFS-19 target trace write failed", exception);
    }
  }

  private static String logicalPool(String physicalPool) {
    String logical = BLOCK_POOLS.get(physicalPool);
    if (logical == null) {
      logical = "hdfs/blockpool/" + BLOCK_POOLS.size();
      BLOCK_POOLS.put(physicalPool, logical);
    }
    return logical;
  }

  public static synchronized void targetCheck(boolean poolMatches,
      String localPool, String commandPool) {
    record("\"event\":\"TARGET_CHECK\",\"siteId\":\"BPOfferService.processCommandFromActive#L768\","
        + "\"sourceKey\":\"" + escape(logicalPool(localPool)) + "\","
        + "\"localBlockPoolId\":\"" + escape(localPool) + "\","
        + "\"commandBlockPoolId\":\"" + escape(commandPool) + "\","
        + "\"poolMatches\":" + poolMatches);
  }

  public static void targetThrow(Throwable error) {
    record("\"event\":\"TARGET_THROW\",\"siteId\":\"BPOfferService.processCommandFromActive#L769\","
        + "\"exception\":\"" + escape(error.getClass().getName()) + "\"");
  }

  /** Called immediately before the released-class block-report RPC call. */
  public static synchronized void io(String marker, String site,
      String physicalPool) throws IOException {
    String source = logicalPool(physicalPool);
    ioSelected(marker, site, source, physicalPool);
  }

  private static String stablePath(File file) {
    String path = file.getAbsolutePath().replace('\\', '/');
    int start = path.indexOf("/scratch/data/");
    if (start >= 0) path = path.substring(start + "/scratch/data/".length());
    return path.replaceAll("BP-[^/]+", "BP");
  }

  /** Called with the actual source and destination of a finalize rename. */
  public static synchronized void ioFile(File from, File to, String marker,
      String site) throws IOException {
    String source = "hdfs/file/" + stablePath(from) + "->" + stablePath(to);
    ioSelected(marker, site, source, from.getAbsolutePath() + "->" + to.getAbsolutePath());
  }

  private static void ioSelected(String marker, String site, String source,
      String physicalResource) throws IOException {
    String identity = marker + "|" + site + "|" + source;
    int ordinal = ORDINALS.containsKey(identity) ? ORDINALS.get(identity) + 1 : 1;
    ORDINALS.put(identity, ordinal);
    String occurrence = source + "/" + site;
    String fields = "\"marker\":\"" + escape(marker) + "\",\"siteId\":\""
        + escape(site) + "\",\"sourceKey\":\"" + escape(source)
        + "\",\"occurrence\":\"" + escape(occurrence)
        + "\",\"physicalResource\":\"" + escape(physicalResource)
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
    if (kind.equals("EOFException")) throw new EOFException("HDFS-19 injected EOF at " + site);
    if (kind.equals("SocketTimeoutException")) {
      throw new SocketTimeoutException("HDFS-19 injected timeout at " + site);
    }
    if (kind.equals("IOException")) throw new IOException("HDFS-19 injected I/O at " + site);
    throw new IllegalArgumentException("unsupported HDFS-19 fault type " + kind);
  }
}
