import java.io.BufferedWriter;
import java.io.FileWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.apache.hadoop.hdfs.protocol.LocatedBlocks;

/** Case-local runtime check and I/O recorder for the unchanged TestPread JUnit. */
public final class Hdfs01Probe {
  private static final String TRACE = System.getProperty("hdfs01.trace", "");
  private static final String PLAN = System.getProperty("hdfs01.plan", "");
  private static final Map<String, Integer> HITS = new HashMap<>();
  private static final List<String[]> FAULTS = new ArrayList<>();
  private static BufferedWriter writer;
  private static long seq;

  static {
    try {
      if (!TRACE.isEmpty()) writer = new BufferedWriter(new FileWriter(TRACE));
      if (!PLAN.isEmpty()) {
        for (String line : Files.readAllLines(Paths.get(PLAN), StandardCharsets.UTF_8)) {
          if (!line.isEmpty() && !line.startsWith("#")) FAULTS.add(line.split("\t", -1));
        }
      }
      Runtime.getRuntime().addShutdownHook(new Thread(() -> {
        synchronized (Hdfs01Probe.class) {
          try { if (writer != null) writer.close(); } catch (IOException ignored) { }
        }
      }));
    } catch (IOException ex) { throw new ExceptionInInitializerError(ex); }
  }

  private Hdfs01Probe() { }

  private static String q(String s) {
    return "\"" + String.valueOf(s).replace("\\", "\\\\").replace("\"", "\\\"")
        .replace("\n", "\\n").replace("\r", "\\r") + "\"";
  }

  private static void emit(String event, String fields) {
    synchronized (Hdfs01Probe.class) {
      if (writer == null) return;
      try {
        writer.write("{\"event\":" + q(event) + ",\"seq\":" + (++seq)
            + ",\"thread\":" + q(Thread.currentThread().getName()) + fields + "}\n");
        writer.flush();
      } catch (IOException ex) { throw new RuntimeException(ex); }
    }
  }

  /** Called immediately before the selected IFNULL in fetchBlockAt. */
  public static void targetCheck(LocatedBlocks blocks, long offset) {
    int count = blocks == null ? -1 : blocks.locatedBlockCount();
    emit("TARGET_CHECK", ",\"siteId\":\"DFSInputStream.fetchBlockAt#L517-B5\""
        + ",\"offset\":" + offset + ",\"blockCount\":" + count
        + ",\"wouldThrow\":" + (count <= 0));
  }

  public static void targetThrow(Throwable ex) {
    emit("TARGET_THROW", ",\"siteId\":\"DFSInputStream.fetchBlockAt#L518\""
        + ",\"exception\":" + q(ex.getClass().getName())
        + ",\"message\":" + q(ex.getMessage()));
  }

  /** Runtime address includes the physical thread and ordinal, not a graph region. */
  public static void io(String marker, String site) throws IOException {
    String source = Thread.currentThread().getName();
    String key = marker + "|" + site + "|" + source;
    int ordinal;
    synchronized (Hdfs01Probe.class) {
      ordinal = HITS.containsKey(key) ? HITS.get(key) + 1 : 1;
      HITS.put(key, ordinal);
    }
    String fields = ",\"marker\":" + q(marker) + ",\"siteId\":" + q(site)
        + ",\"sourceKey\":" + q(source) + ",\"occurrence\":" + q(source + "/" + site)
        + ",\"hitOrdinal\":" + ordinal;
    emit("FAULT_POINT_OBSERVED", fields);
    for (int i = 0; i < FAULTS.size(); i++) {
      String[] fault = FAULTS.get(i);
      if (fault.length < 6 || !fault[0].equals(marker) || !fault[1].equals(site)
          || !fault[2].equals(source) || Integer.parseInt(fault[3]) != ordinal) continue;
      synchronized (Hdfs01Probe.class) {
        if (fault[4].equals("applied")) continue;
        fault[4] = "applied";
      }
      String kind = fault[5];
      emit("FAULT_MATCHED", fields + ",\"faultIndex\":" + i + ",\"faultType\":" + q(kind));
      emit("FAULT_APPLIED", fields + ",\"faultIndex\":" + i + ",\"faultType\":" + q(kind));
      String message = "HDFS-01 injected " + kind + " at " + site + ":" + ordinal;
      if (kind.equals("SocketTimeoutException")) throw new java.net.SocketTimeoutException(message);
      if (kind.equals("EOFException")) throw new java.io.EOFException(message);
      if (!kind.equals("IOException")) throw new IllegalArgumentException("Unknown fault: " + kind);
      throw new IOException(message);
    }
  }
}
