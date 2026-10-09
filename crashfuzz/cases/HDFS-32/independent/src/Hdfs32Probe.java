import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.concurrent.atomic.AtomicLong;
import java.util.HashMap;
import java.util.Map;

/** Case-local runtime events for the exact DataNode.deleteBlockPool guard. */
public final class Hdfs32Probe {
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final Path OUTPUT = Paths.get(System.getProperty("hdfs32.trace"));
  private static final String[] PLAN = System.getProperty("hdfs32.plan", "").isEmpty()
      ? new String[0] : System.getProperty("hdfs32.plan").split("\\|\\|\\|");
  private static final Map<String, Integer> ORDINALS = new HashMap<>();
  private static int nextFault;
  private static synchronized void event(String name, Object... fields) {
    StringBuilder row = new StringBuilder();
    row.append(SEQUENCE.incrementAndGet()).append('\t').append(name).append('\t')
       .append(Thread.currentThread().getName());
    for (Object field : fields) row.append('\t').append(field);
    row.append('\n');
    try (FileOutputStream stream = new FileOutputStream(OUTPUT.toFile(), true)) {
      stream.write(row.toString().getBytes(StandardCharsets.UTF_8));
    } catch (IOException e) {
      // BPServiceActor invokes the removal callback while interrupted. A trace
      // failure must never interrupt that original cleanup path.
      System.err.println("HDFS32_PROBE_WRITE_ERROR\t" + e);
    }
  }
  private static int id(Object value) { return value == null ? 0 : System.identityHashCode(value); }
  public static synchronized void rpcResponse() throws IOException {
    String source = Thread.currentThread().getName().replaceAll(":\\d+", ":port")
        .replaceAll("\\d+", "N");
    String site = "Client.getRpcResponse:" + source;
    int ordinal = ORDINALS.containsKey(site) ? ORDINALS.get(site) + 1 : 1;
    ORDINALS.put(site, ordinal);
    event("IO", site, ordinal);
    String selector = site + "@@" + ordinal;
    if (nextFault < PLAN.length && PLAN[nextFault].equals(selector)) {
      event("FAULT_MATCHED", site, ordinal, nextFault);
      event("FAULT_APPLIED", site, ordinal, nextFault);
      nextFault++;
      throw new IOException("HDFS-32 independent RPC response fault " + selector);
    }
  }
  public static void guard(Object service, Object datanode, String bpid, boolean force) {
    event("TARGET_GUARD", id(datanode), bpid, force, service != null, id(service));
  }
  public static void targetThrow(Throwable error, Object datanode, String bpid, boolean force) {
    event("TARGET_THROW", id(datanode), bpid, force, error.getClass().getName(), error.getMessage());
  }
  public static void refresh(Object datanode) { event("REFRESH_NAMENODES", id(datanode)); }
  public static void datasetDelete(Object datanode, String bpid, boolean force) {
    event("DATASET_DELETE", id(datanode), bpid, force);
  }
  public static void poolAdd(Object manager, Object service) {
    event("POOL_ADD", id(manager), id(service));
  }
  public static void poolRemove(Object manager, Object service) {
    event("POOL_REMOVE", id(manager), id(service));
  }
}
