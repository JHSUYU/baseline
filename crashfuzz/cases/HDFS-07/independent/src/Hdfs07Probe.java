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
import org.apache.hadoop.hdfs.qjournal.protocol.QJournalProtocolProtos.SegmentStateProto;

/** Runtime identity, target, and I/O recorder for the unchanged original JUnit. */
public final class Hdfs07Probe {
  private static final String TRACE = System.getProperty("hdfs07.independent.trace", "");
  private static final String PLAN = System.getProperty("hdfs07.independent.plan", "");
  private static final Map<String, Integer> HITS = new HashMap<>();
  private static final List<String[]> FAULTS = new ArrayList<>();
  private static BufferedWriter writer;
  private static long seq;

  static {
    try {
      if (!TRACE.isEmpty()) writer = new BufferedWriter(new FileWriter(TRACE));
      if (!PLAN.isEmpty()) {
        for (String line : Files.readAllLines(Paths.get(PLAN), StandardCharsets.UTF_8))
          if (!line.isEmpty() && !line.startsWith("#")) FAULTS.add(line.split("\t", -1));
      }
      Runtime.getRuntime().addShutdownHook(new Thread(() -> {
        synchronized (Hdfs07Probe.class) {
          try { if (writer != null) writer.close(); } catch (IOException ignored) { }
        }
      }));
    } catch (IOException ex) { throw new ExceptionInInitializerError(ex); }
  }

  private Hdfs07Probe() { }

  private static String q(String s) {
    return "\"" + String.valueOf(s).replace("\\", "\\\\").replace("\"", "\\\"")
        .replace("\n", "\\n").replace("\r", "\\r") + "\"";
  }

  private static void emit(String event, String fields) {
    synchronized (Hdfs07Probe.class) {
      if (writer == null) return;
      try {
        writer.write("{\"event\":" + q(event) + ",\"seq\":" + (++seq)
            + ",\"thread\":" + q(Thread.currentThread().getName()) + fields + "}\n");
        writer.flush();
      } catch (IOException ex) { throw new RuntimeException(ex); }
    }
  }

  private static String node(File path) {
    String value = path.getAbsolutePath();
    int start = value.indexOf("journalnode-");
    return start < 0 ? path.getName() : value.substring(start).split("/", 2)[0];
  }

  public static void targetCheck(File root, long committed, RequestInfo req, SegmentStateProto old,
                                 SegmentStateProto proposed) {
    emit("TARGET_CHECK", ",\"siteId\":\"Journal.acceptRecovery#L924-933\""
        + ",\"journalId\":" + q(req.getJournalId())
        + ",\"journalNode\":" + q(node(root))
        + ",\"epoch\":" + req.getEpoch() + ",\"serial\":" + req.getIpcSerialNumber()
        + ",\"committedTxId\":" + committed
        + ",\"oldStart\":" + old.getStartTxId() + ",\"oldEnd\":" + old.getEndTxId()
        + ",\"newStart\":" + proposed.getStartTxId() + ",\"newEnd\":" + proposed.getEndTxId()
        + ",\"guardWouldFail\":" + (old.getStartTxId() <= committed
              && committed <= old.getEndTxId()
              && !(proposed.getStartTxId() <= committed && committed <= proposed.getEndTxId())));
  }

  public static void targetThrow(File root, RequestInfo req) {
    emit("TARGET_THROW", ",\"siteId\":\"Journal.acceptRecovery#L924-933\""
        + ",\"journalId\":" + q(req.getJournalId())
        + ",\"journalNode\":" + q(node(root))
        + ",\"epoch\":" + req.getEpoch()
        + ",\"exception\":\"java.lang.AssertionError\"");
  }

  public static void ipcResponse() throws IOException {
    String thread = Thread.currentThread().getName();
    String source = thread.replaceAll(":\\d+", ":port").replaceAll("\\d+", "N");
    io("FAULT:HDFS_QJM_RPC:RESPONSE", "Client.getRpcResponse", source);
  }

  public static void paxosWrite(File root, RequestInfo req, SegmentStateProto state) throws IOException {
    io("FAULT:HDFS_QJM_FILE:PAXOS_WRITE", "Journal.acceptRecovery.persistPaxosData",
        node(root) + "/" + req.getJournalId() + "/" + state.getStartTxId());
  }

  public static void fileReplace(File source, File target) throws IOException {
    io("FAULT:HDFS_QJM_FILE:REPLACE", "Journal.acceptRecovery.FileUtil.replaceFile",
        node(target) + "/" + target.getName());
  }

  private static void io(String marker, String site, String source) throws IOException {
    String key = marker + "|" + site + "|" + source;
    int ordinal;
    synchronized (Hdfs07Probe.class) {
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
      synchronized (Hdfs07Probe.class) {
        if (fault[4].equals("applied")) continue;
        fault[4] = "applied";
      }
      String kind = fault[5];
      emit("FAULT_MATCHED", fields + ",\"faultIndex\":" + i + ",\"faultType\":" + q(kind));
      emit("FAULT_APPLIED", fields + ",\"faultIndex\":" + i + ",\"faultType\":" + q(kind));
      String message = "HDFS-07 independent injected " + kind + " at " + site + ":" + ordinal;
      if (kind.equals("SocketTimeoutException")) throw new java.net.SocketTimeoutException(message);
      if (kind.equals("EOFException")) throw new java.io.EOFException(message);
      if (kind.equals("FileNotFoundException")) throw new java.io.FileNotFoundException(message);
      if (!kind.equals("IOException")) throw new IllegalArgumentException("Unknown fault: " + kind);
      throw new IOException(message);
    }
  }
}
