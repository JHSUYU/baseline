import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;
import org.apache.hadoop.hdfs.server.namenode.INode;
import org.apache.hadoop.hdfs.server.namenode.INodeDirectory;

/** Case-local recorder for the exact replaceChild second checkState call. */
public final class Hdfs48Probe {
  private static final String TRACE = System.getProperty("hdfs48.trace", "");
  private static final String PLAN = System.getProperty("hdfs48.plan", "");
  private static final Map<String, Integer> HITS = new HashMap<>();
  private static long seq;
  private static int nextFault;

  private Hdfs48Probe() { }

  private static synchronized void emit(String event, Object... fields) {
    if (TRACE.isEmpty()) return;
    StringBuilder row = new StringBuilder().append(++seq).append('\t').append(event)
        .append('\t').append(Thread.currentThread().getName());
    for (Object field : fields) row.append('\t').append(String.valueOf(field));
    row.append('\n');
    try (FileOutputStream stream = new FileOutputStream(TRACE, true)) {
      stream.write(row.toString().getBytes(StandardCharsets.UTF_8));
    } catch (IOException error) {
      System.err.println("HDFS48_TRACE_WRITE_ERROR\t" + error);
    }
  }

  public static void guard(boolean valid, INodeDirectory parent, INode oldChild, INode replacement) {
    String parentPath = parent.getFullPathName();
    String childName = replacement.getLocalName();
    Object[] identity = {parentPath, childName, System.identityHashCode(parent),
        System.identityHashCode(oldChild), System.identityHashCode(replacement), valid};
    emit("TARGET_GUARD", identity);
    if (!valid) emit("TARGET_FALSE", identity);
  }

  /** A real Hadoop IPC response read; faults are selected only after observing this site. */
  public static synchronized void rpcResponse() throws IOException {
    String site = "Client.getRpcResponse";
    String source = Thread.currentThread().getName().replaceAll(":\\d+", ":port")
        .replaceAll("\\d+", "N");
    String key = site + "|" + source;
    int ordinal = HITS.containsKey(key) ? HITS.get(key) + 1 : 1;
    HITS.put(key, ordinal);
    emit("IO", site, source, ordinal);
    String selector = key + "|" + ordinal;
    String[] plan = PLAN.isEmpty() ? new String[0] : PLAN.split("\\|\\|\\|");
    if (nextFault < plan.length && plan[nextFault].startsWith(selector + "|")) {
      String kind = plan[nextFault].substring(selector.length() + 1);
      if (!kind.equals("IOException") && !kind.equals("SocketTimeoutException")
          && !kind.equals("EOFException")) throw new IllegalArgumentException(kind);
      emit("FAULT_MATCHED", site, source, ordinal, nextFault, kind);
      emit("FAULT_APPLIED", site, source, ordinal, nextFault, kind);
      nextFault++;
      String message = "HDFS-48 injected IPC response failure at " + selector;
      if (kind.equals("SocketTimeoutException")) throw new java.net.SocketTimeoutException(message);
      if (kind.equals("EOFException")) throw new java.io.EOFException(message);
      throw new IOException(message);
    }
  }
}
