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
import org.apache.hadoop.hdfs.server.common.Storage.StorageDirectory;

/** Recorder for both adjacent BlockPoolSliceStorage guards in the original JUnit. */
public final class Hdfs22Probe {
  private static final String TRACE = System.getProperty("hdfs22.independent.trace", "");
  private static final String PLAN = System.getProperty("hdfs22.independent.plan", "");
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
        synchronized (Hdfs22Probe.class) {
          try { if (writer != null) writer.close(); } catch (IOException ignored) { }
        }
      }));
    } catch (IOException ex) { throw new ExceptionInInitializerError(ex); }
  }

  private Hdfs22Probe() { }

  private static String q(String s) {
    return "\"" + String.valueOf(s).replace("\\", "\\\\").replace("\"", "\\\"")
        .replace("\n", "\\n").replace("\r", "\\r") + "\"";
  }

  private static void emit(String event, String fields) {
    synchronized (Hdfs22Probe.class) {
      if (writer == null) return;
      try {
        writer.write("{\"event\":" + q(event) + ",\"seq\":" + (++seq)
            + ",\"thread\":" + q(Thread.currentThread().getName()) + fields + "}\n");
        writer.flush();
      } catch (IOException ex) { throw new RuntimeException(ex); }
    }
  }

  public static void namespaceCheck(int datanodeId, int namenodeId) {
    emit("TARGET_CHECK", ",\"siteId\":\"BlockPoolSliceStorage.doTransition#L392-IF_ICMPEQ\""
        + ",\"caseId\":\"HDFS-22\",\"equal\":" + (datanodeId == namenodeId)
        + ",\"datanodeNamespaceId\":" + datanodeId + ",\"namenodeNamespaceId\":" + namenodeId);
  }

  public static void blockpoolCheck(int equal) {
    emit("TARGET_CHECK", ",\"siteId\":\"BlockPoolSliceStorage.doTransition#L398-IFNE\""
        + ",\"caseId\":\"HDFS-23\",\"equal\":" + (equal != 0));
  }

  public static void ctimeCheck(int comparison) {
    emit("TARGET_CHECK", ",\"siteId\":\"BlockPoolSliceStorage.loadStorageDirectory#L184-IFEQ\""
        + ",\"caseId\":\"HDFS-25\",\"equal\":" + (comparison == 0));
  }

  public static void storageNamespaceCheck(int datanodeId, int namenodeId) {
    emit("TARGET_CHECK", ",\"siteId\":\"DataStorage.doTransition#L740-IF_ICMPEQ\""
        + ",\"caseId\":\"HDFS-34\",\"equal\":" + (datanodeId == namenodeId)
        + ",\"datanodeNamespaceId\":" + datanodeId + ",\"namenodeNamespaceId\":" + namenodeId);
  }

  public static void clusterCheck(int equal) {
    emit("TARGET_CHECK", ",\"siteId\":\"DataStorage.doTransition#L749-IFNE\""
        + ",\"caseId\":\"HDFS-35\",\"equal\":" + (equal != 0));
  }

  public static void targetThrow(String caseId, Throwable ex) {
    emit("TARGET_THROW", ",\"caseId\":" + q(caseId)
        + ",\"exception\":" + q(ex.getClass().getName())
        + ",\"message\":" + q(ex.getMessage()));
  }

  public static void versionRead(StorageDirectory directory) throws IOException {
    String path = directory.getRoot().getCanonicalPath();
    int start = path.indexOf("/data/");
    String source = (start < 0 ? directory.getRoot().getName() : path.substring(start + 6))
        .replaceAll("BP-[^/]+", "BP-ID");
    io("FAULT:HDFS_BP_FILE:VERSION_READ", "BlockPoolSliceStorage.readProperties", source);
  }

  public static void dataVersionRead(StorageDirectory directory) throws IOException {
    String path = directory.getRoot().getCanonicalPath();
    int start = path.indexOf("/data/");
    String source = (start < 0 ? directory.getRoot().getName() : path.substring(start + 6))
        .replaceAll("BP-[^/]+", "BP-ID");
    io("FAULT:HDFS_BP_FILE:DN_VERSION_READ", "DataStorage.readProperties", source);
  }

  public static void ipcResponse() throws IOException {
    String thread = Thread.currentThread().getName();
    String source = thread.replaceAll(":\\d+", ":port").replaceAll("\\d+", "N");
    io("FAULT:HDFS_BP_RPC:RESPONSE", "Client.getRpcResponse", source);
  }

  private static void io(String marker, String site, String source) throws IOException {
    String key = marker + "|" + site + "|" + source;
    int ordinal;
    synchronized (Hdfs22Probe.class) {
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
      synchronized (Hdfs22Probe.class) {
        if (fault[4].equals("applied")) continue;
        fault[4] = "applied";
      }
      String kind = fault[5];
      emit("FAULT_MATCHED", fields + ",\"faultIndex\":" + i + ",\"faultType\":" + q(kind));
      emit("FAULT_APPLIED", fields + ",\"faultIndex\":" + i + ",\"faultType\":" + q(kind));
      String message = "HDFS-22/23 independent injected " + kind + " at " + site + ":" + ordinal;
      if (kind.equals("SocketTimeoutException")) throw new java.net.SocketTimeoutException(message);
      if (kind.equals("EOFException")) throw new java.io.EOFException(message);
      if (kind.equals("FileNotFoundException")) throw new java.io.FileNotFoundException(message);
      if (!kind.equals("IOException")) throw new IllegalArgumentException("Unknown fault: " + kind);
      throw new IOException(message);
    }
  }
}
