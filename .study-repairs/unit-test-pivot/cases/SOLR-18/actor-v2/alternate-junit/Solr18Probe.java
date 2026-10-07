package research.solr18;

import java.io.FileOutputStream;
import java.io.IOException;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;
import org.apache.solr.common.cloud.Aliases;
import org.apache.solr.common.cloud.ZkStateReader;
import org.apache.zookeeper.KeeperException;

/** Separate graph-free runtime events for an original API alias JUnit. */
public final class Solr18Probe {
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final String TRACE = System.getProperty("solr18.trace");
  private static final Path OUTPUT = TRACE == null ? null : Paths.get(TRACE);
  private static final String[] PLAN = System.getProperty("solr18.plan", "").isEmpty()
      ? new String[0] : System.getProperty("solr18.plan").split("\\|\\|\\|");
  private static final Map<String, Integer> ORDINALS = new HashMap<>();
  private static int nextFault;

  private Solr18Probe() {}

  private static synchronized void event(String name, Object... fields) {
    if (OUTPUT == null) return;
    StringBuilder row = new StringBuilder();
    row.append(SEQUENCE.incrementAndGet()).append('\t').append(name).append('\t')
       .append(Thread.currentThread().getName());
    for (Object field : fields) row.append('\t').append(field);
    row.append('\n');
    try (FileOutputStream stream = new FileOutputStream(OUTPUT.toFile(), true)) {
      stream.write(row.toString().getBytes(StandardCharsets.UTF_8));
    } catch (IOException e) {
      // ZooKeeper callbacks may be interrupted. Recording cannot change them.
      System.err.println("SOLR18_PROBE_WRITE_ERROR\t" + e);
    }
  }

  private static int id(Object object) { return object == null ? 0 : System.identityHashCode(object); }
  private static String actor(Object client) {
    return client == null ? "UNBOUND" : "ZKCLIENT@" + Integer.toHexString(id(client));
  }
  private static String managerActor(Object manager) {
    try {
      Field outer = manager.getClass().getDeclaredField("this$0");
      outer.setAccessible(true);
      Object reader = outer.get(manager);
      return reader instanceof ZkStateReader
          ? actor(((ZkStateReader) reader).getZkClient()) : "UNBOUND";
    } catch (ReflectiveOperationException | SecurityException error) {
      return "UNBOUND";
    }
  }
  private static String role() {
    String raw = Thread.currentThread().getName();
    if (raw.contains("TEST-")) return "TEST";
    if (raw.contains("SUITE-")) return "SUITE";
    if (raw.contains("EventThread")) return "ZK_EVENT";
    return raw.replaceAll(":\\d+", ":port").replaceAll("\\d+", "N");
  }

  public static void testStarted() { event("TEST_STARTED"); }
  public static void testFinished() { event("TEST_FINISHED"); }
  public static void applyModification(Object manager) {
    String origin = "OTHER";
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (frame.getClassName().equals("org.apache.solr.cloud.api.collections.CreateAliasCmd")
          && frame.getMethodName().equals("callCreatePlainAlias")) {
        origin = "CREATE_ALIAS_CMD";
        break;
      }
    }
    event("APPLY_MODIFICATION", id(manager), origin, "actor=" + managerActor(manager));
  }

  public static void guard(Object manager, Aliases oldAliases, Aliases newAliases, int cmp) {
    event("TARGET_GUARD", id(manager), id(oldAliases), id(newAliases),
          oldAliases.getZNodeVersion(), newAliases.getZNodeVersion(), cmp,
          "actor=" + managerActor(manager));
  }
  public static void equalResult(boolean equal, Object manager, Aliases oldAliases,
                                 Aliases newAliases, int cmp) {
    event("TARGET_EQUAL_CHECK", id(manager), id(oldAliases), id(newAliases),
          oldAliases.getZNodeVersion(), newAliases.getZNodeVersion(), cmp, equal,
          "actor=" + managerActor(manager));
  }
  public static void targetThrow(Throwable error, Object manager, Aliases oldAliases,
                                 Aliases newAliases, int cmp) {
    event("TARGET_THROW", id(manager), id(oldAliases), id(newAliases),
          oldAliases.getZNodeVersion(), newAliases.getZNodeVersion(), cmp,
          error.getClass().getName(), error.getMessage(),
          "actor=" + managerActor(manager));
  }

  public static synchronized void aliasIo(String operation, String path, Object client)
      throws KeeperException {
    if (path == null) return;
    String site = "SolrZkClient." + operation + ":" + path + ":" + role();
    int ordinal = ORDINALS.containsKey(site) ? ORDINALS.get(site) + 1 : 1;
    ORDINALS.put(site, ordinal);
    event("IO", site, ordinal, "actor=" + actor(client));
    String selector = site + "@@" + ordinal;
    if (nextFault < PLAN.length && PLAN[nextFault].equals(selector)) {
      event("FAULT_MATCHED", site, ordinal, nextFault, "actor=" + actor(client));
      event("FAULT_APPLIED", site, ordinal, nextFault, "actor=" + actor(client));
      nextFault++;
      throw new KeeperException.ConnectionLossException();
    }
  }
}
