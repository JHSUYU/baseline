import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;
import org.apache.hadoop.hdfs.protocol.ExtendedBlock;

/** Case-local non-throwing recorder for the exact getBPOSForBlock guard. */
public final class Hdfs31Probe {
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final Path OUTPUT = Paths.get(System.getProperty("hdfs31.trace"));
  private static final String[] PLAN = System.getProperty("hdfs31.plan", "").isEmpty()
      ? new String[0] : System.getProperty("hdfs31.plan").split("\\|\\|\\|");
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
      // Actor cleanup may be interrupted. The recorder must not change it.
      System.err.println("HDFS31_PROBE_WRITE_ERROR\t" + e);
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
      throw new IOException("HDFS-31 independent RPC response fault " + selector);
    }
  }

  public static void transfer(Object datanode, ExtendedBlock block) {
    event("TRANSFER_BLOCK", id(datanode), block.getBlockPoolId(), block.getBlockId());
  }
  public static void guard(Object service, Object datanode, ExtendedBlock block) {
    event("TARGET_GUARD", id(datanode), block.getBlockPoolId(), block.getBlockId(),
          service != null, id(service));
  }
  public static void targetThrow(Throwable error, Object datanode, ExtendedBlock block) {
    event("TARGET_THROW", id(datanode), block.getBlockPoolId(), block.getBlockId(),
          error.getClass().getName(), error.getMessage());
  }
  public static void poolAdd(Object manager, Object service) {
    event("POOL_ADD", id(manager), id(service));
  }
  public static void poolRemove(Object manager, Object service) {
    event("POOL_REMOVE", id(manager), id(service));
  }
}
