import java.io.BufferedWriter;
import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.apache.hadoop.hdfs.qjournal.protocol.RequestInfo;

/** Case-local recorder for the original testSingleWriter MiniJournalCluster. */
public final class Hdfs09Probe {
  private static final String TRACE = System.getProperty("hdfs09.independent.trace", "");
  private static final String PLAN = System.getProperty("hdfs09.independent.plan", "");
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
        synchronized (Hdfs09Probe.class) {
          try { if (writer != null) writer.close(); } catch (IOException ignored) { }
        }
      }));
    } catch (IOException ex) { throw new ExceptionInInitializerError(ex); }
  }

  private Hdfs09Probe() { }

  private static String q(String s) {
    return "\"" + String.valueOf(s).replace("\\", "\\\\").replace("\"", "\\\"")
        .replace("\n", "\\n").replace("\r", "\\r") + "\"";
  }

  private static void emit(String event, String fields) {
    synchronized (Hdfs09Probe.class) {
      if (writer == null) return;
      try {
        writer.write("{\"event\":" + q(event) + ",\"seq\":" + (++seq)
            + ",\"thread\":" + q(Thread.currentThread().getName()) + fields + "}\n");
        writer.flush();
      } catch (IOException ex) { throw new RuntimeException(ex); }
    }
  }

  public static void targetCheck(boolean allowed, Object message, RequestInfo req) {
    emit("TARGET_CHECK", ",\"siteId\":\"Journal.checkRequest#L504-Preconditions\""
        + ",\"allowed\":" + allowed + ",\"epoch\":" + req.getEpoch()
        + ",\"serial\":" + req.getIpcSerialNumber()
        + ",\"committedTxId\":" + req.getCommittedTxId()
        + ",\"message\":" + q(String.valueOf(message)));
  }

  public static void targetReturn() {
    emit("TARGET_RETURN", ",\"siteId\":\"Journal.checkRequest#L504-Preconditions\"");
  }

  public static void targetThrow(Throwable ex) {
    emit("TARGET_THROW", ",\"siteId\":\"Journal.checkRequest#L504-Preconditions\""
        + ",\"exception\":" + q(ex.getClass().getName())
        + ",\"message\":" + q(ex.getMessage()));
  }

  public static void ipcResponse() throws IOException {
    String thread = Thread.currentThread().getName();
    // Dynamic socket ports and generated thread serials do not define the I/O family.
    String source = thread.replaceAll(":\\d+", ":port").replaceAll("\\d+", "N");
    io("FAULT:HDFS_QJM_RPC:RESPONSE", "Client.getRpcResponse", source);
  }

  public static void committedWrite(File file) throws IOException {
    String path = file.getAbsolutePath();
    int start = path.indexOf("journalnode-");
    String suffix = start < 0 ? file.getName() : path.substring(start);
    if (!suffix.endsWith("/test-journal/current/committed-txid")) return;
    String node = suffix.split("/", 2)[0];
    io("FAULT:HDFS_QJM_FILE:COMMITTED_TXID_WRITE", "BestEffortLongFile.set", node);
  }

  private static void io(String marker, String site, String source) throws IOException {
    String key = marker + "|" + site + "|" + source;
    int ordinal;
    synchronized (Hdfs09Probe.class) {
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
      synchronized (Hdfs09Probe.class) {
        if (fault[4].equals("applied")) continue;
        fault[4] = "applied";
      }
      String kind = fault[5];
      emit("FAULT_MATCHED", fields + ",\"faultIndex\":" + i + ",\"faultType\":" + q(kind));
      emit("FAULT_APPLIED", fields + ",\"faultIndex\":" + i + ",\"faultType\":" + q(kind));
      String message = "HDFS-09 independent injected " + kind + " at " + site + ":" + ordinal;
      if (kind.equals("SocketTimeoutException")) throw new java.net.SocketTimeoutException(message);
      if (kind.equals("EOFException")) throw new java.io.EOFException(message);
      if (kind.equals("FileNotFoundException")) throw new java.io.FileNotFoundException(message);
      if (!kind.equals("IOException")) throw new IllegalArgumentException("Unknown fault: " + kind);
      throw new IOException(message);
    }
  }
}
