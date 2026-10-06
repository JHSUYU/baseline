import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

/** Exact snapshot-count guard, actual serialization calls, and IPC reads. */
public final class Hdfs52Probe {
  private static final String TRACE = System.getProperty("hdfs52.trace", "");
  private static final String PLAN = System.getProperty("hdfs52.plan", "");
  private static final Map<String, Integer> HITS = new HashMap<>();
  private static long seq;
  private static int nextFault;
  private static int targetOrdinal;

  private Hdfs52Probe() { }

  private static synchronized void emit(String event, Object... fields) {
    if (TRACE.isEmpty()) return;
    StringBuilder row = new StringBuilder().append(++seq).append('\t').append(event)
        .append('\t').append(Thread.currentThread().getName());
    for (Object field : fields) row.append('\t').append(String.valueOf(field));
    row.append('\n');
    try (FileOutputStream stream = new FileOutputStream(TRACE, true)) {
      stream.write(row.toString().getBytes(StandardCharsets.UTF_8));
    } catch (IOException error) {
      System.err.println("HDFS52_TRACE_WRITE_ERROR\t" + error);
    }
  }

  public static synchronized void counts(int serialized, int expected, Object manager) {
    ++targetOrdinal;
    Object[] fields = {targetOrdinal, System.identityHashCode(manager), serialized,
        expected, serialized == expected};
    emit("TARGET_GUARD", fields);
    if (serialized != expected) emit("TARGET_FALSE", fields);
  }

  public static void fileWrite(String phase) throws IOException {
    io("FSImageSnapshot.writeDelimitedTo#" + phase, "fsimage/snapshot");
  }

  public static void rpcResponse() throws IOException {
    String source = Thread.currentThread().getName().replaceAll(":\\d+", ":port")
        .replaceAll("\\d+", "N");
    io("Client.getRpcResponse", source);
  }

  private static synchronized void io(String site, String source) throws IOException {
    String key = site + "|" + source;
    int ordinal = HITS.containsKey(key) ? HITS.get(key) + 1 : 1;
    HITS.put(key, ordinal);
    emit("IO", site, source, ordinal);
    String selector = key + "|" + ordinal;
    String[] plan = PLAN.isEmpty() ? new String[0] : PLAN.split("\\|\\|\\|");
    if (nextFault < plan.length && plan[nextFault].startsWith(selector + "|")) {
      String kind = plan[nextFault].substring(selector.length() + 1);
      if (!kind.equals("IOException") && !kind.equals("SocketTimeoutException")
          && !kind.equals("EOFException") && !kind.equals("FileNotFoundException"))
        throw new IllegalArgumentException(kind);
      emit("FAULT_MATCHED", site, source, ordinal, nextFault, kind);
      emit("FAULT_APPLIED", site, source, ordinal, nextFault, kind);
      nextFault++;
      String message = "HDFS-52 injected I/O failure at " + selector;
      if (kind.equals("SocketTimeoutException")) throw new java.net.SocketTimeoutException(message);
      if (kind.equals("EOFException")) throw new java.io.EOFException(message);
      if (kind.equals("FileNotFoundException")) throw new java.io.FileNotFoundException(message);
      throw new IOException(message);
    }
  }
}
