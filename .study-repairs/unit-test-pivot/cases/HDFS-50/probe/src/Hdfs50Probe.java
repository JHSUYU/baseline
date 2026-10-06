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

/** Small HDFS-50 runtime recorder and exact I/O exception controller. */
public final class Hdfs50Probe {
  private static final String TRACE = System.getProperty("hdfs50.trace", "");
  private static final String PLAN = System.getProperty("hdfs50.plan", "");
  private static final Map<String, Integer> HITS = new HashMap<>();
  private static final List<String[]> FAULTS = new ArrayList<>();
  private static BufferedWriter writer;
  private static long eventNumber;

  static {
    try {
      if (!TRACE.isEmpty()) writer = new BufferedWriter(new FileWriter(TRACE));
      if (!PLAN.isEmpty()) {
        for (String line : Files.readAllLines(Paths.get(PLAN), StandardCharsets.UTF_8)) {
          if (!line.isEmpty() && !line.startsWith("#")) FAULTS.add(line.split("\t", -1));
        }
      }
      Runtime.getRuntime().addShutdownHook(new Thread(() -> {
        synchronized (Hdfs50Probe.class) {
          try { if (writer != null) writer.close(); } catch (IOException ignored) { }
        }
      }));
    } catch (IOException ex) { throw new ExceptionInInitializerError(ex); }
  }

  private Hdfs50Probe() { }

  private static String q(String value) {
    return "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"")
        .replace("\n", "\\n").replace("\r", "\\r") + "\"";
  }

  private static void emit(String event, String rest) {
    synchronized (Hdfs50Probe.class) {
      if (writer == null) return;
      try {
        writer.write("{\"event\":" + q(event) + ",\"seq\":" + (++eventNumber)
            + ",\"thread\":" + q(Thread.currentThread().getName()) + rest + "}\n");
        writer.flush();
      } catch (IOException ex) { throw new RuntimeException(ex); }
    }
  }

  public static void targetEnter(String name) {
    emit("TARGET_ENTER", ",\"method\":\"DirectorySnapshottableFeature.addSnapshot\",\"snapshot\":" + q(name));
  }

  public static void targetBranch(String name, int searchResult) {
    emit("TARGET_BRANCH", ",\"method\":\"DirectorySnapshottableFeature.addSnapshot\",\"snapshot\":" + q(name)
        + ",\"duplicate\":" + (searchResult >= 0) + ",\"searchResult\":" + searchResult);
  }

  public static void targetThrow(Throwable exception, String name) {
    emit("TARGET_THROW", ",\"method\":\"DirectorySnapshottableFeature.addSnapshot\",\"snapshot\":" + q(name)
        + ",\"exception\":" + q(exception.getClass().getName()) + ",\"message\":" + q(String.valueOf(exception.getMessage())));
  }

  public static void targetReturn(String name) {
    emit("TARGET_RETURN", ",\"method\":\"DirectorySnapshottableFeature.addSnapshot\",\"snapshot\":" + q(name));
  }

  /** Called at application I/O boundaries; sourceKey and ordinal are replay identity. */
  public static void io(String marker, String siteId) throws IOException {
    String sourceKey = Thread.currentThread().getName();
    String key = marker + "|" + siteId + "|" + sourceKey;
    int ordinal;
    synchronized (Hdfs50Probe.class) {
      ordinal = HITS.containsKey(key) ? HITS.get(key) + 1 : 1;
      HITS.put(key, ordinal);
    }
    String fields = ",\"marker\":" + q(marker) + ",\"siteId\":" + q(siteId)
        + ",\"sourceKey\":" + q(sourceKey) + ",\"occurrence\":" + q(sourceKey + "/" + siteId)
        + ",\"hitOrdinal\":" + ordinal;
    emit("FAULT_POINT_OBSERVED", fields);
    for (int i = 0; i < FAULTS.size(); i++) {
      String[] fault = FAULTS.get(i);
      if (fault.length < 5 || !fault[0].equals(marker) || !fault[1].equals(siteId)
          || !fault[2].equals(sourceKey) || Integer.parseInt(fault[3]) != ordinal) continue;
      synchronized (Hdfs50Probe.class) {
        if (fault[4].equals("applied")) continue;
        fault[4] = "applied";
      }
      String type = fault.length > 5 ? fault[5] : "IOException";
      emit("FAULT_MATCHED", fields + ",\"faultIndex\":" + i + ",\"faultType\":" + q(type));
      emit("FAULT_APPLIED", fields + ",\"faultIndex\":" + i + ",\"faultType\":" + q(type));
      String message = "HDFS-50 injected I/O exception at " + siteId + ":" + ordinal;
      if (type.equals("SocketTimeoutException")) throw new java.net.SocketTimeoutException(message);
      if (type.equals("EOFException")) throw new java.io.EOFException(message);
      if (!type.equals("IOException")) throw new IllegalArgumentException("Unknown HDFS-50 fault type " + type);
      throw new IOException(message);
    }
  }
}
