package baseline.solr103940;

import java.io.BufferedWriter;
import java.io.FileWriter;
import java.io.IOException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import org.apache.zookeeper.KeeperException;

/** Actor-bound I/O and the three exact production guards. No test workload is changed. */
public final class FeedbackProbe {
  private static final class Fault {
    final String operation, path, caller, actor, after;
    final int ordinal, seedGlobal;
    final boolean relative;
    int seen, globalSeen;

    Fault(String spec) {
      String[] fields = spec.split("\\|", -1);
      if (fields.length != 5 && fields.length != 7)
        throw new IllegalArgumentException("Expected OP|path|ordinal|caller=...|actor=...: " + spec);
      operation = fields[0];
      path = fields[1];
      relative = fields[2].startsWith("@");
      ordinal = Integer.parseInt(relative ? fields[2].substring(1) : fields[2]);
      caller = fields[3];
      actor = fields[4];
      if (operation.isEmpty() || path.isEmpty() || ordinal <= 0 ||
          !caller.startsWith("caller=") || !actor.matches("actor=jetty:node[1-4]"))
        throw new IllegalArgumentException("Invalid actor-bound selector: " + spec);
      if (relative != (fields.length == 7))
        throw new IllegalArgumentException("Relative selector requires after and seed_global: " + spec);
      after = relative ? fields[5] : "";
      seedGlobal = relative ? Integer.parseInt(fields[6].replaceFirst("^seed_global=", "")) : 0;
      if (relative && (!after.matches("after=F[0-9]+") ||
          !fields[6].startsWith("seed_global=") || seedGlobal <= 0))
        throw new IllegalArgumentException("Invalid phase anchor: " + spec);
    }
  }

  private static final Map<Object, String> NODE_BY_CLIENT = new IdentityHashMap<>();
  private static final Map<Object, Object> MANAGER_BY_CLIENT = new IdentityHashMap<>();
  private static final Map<String, String> ROLE_BY_NODE = new HashMap<>();
  private static final List<Fault> FAULTS = parseFaults();
  private static final BufferedWriter TRACE = openTrace();
  private static long sequence;
  private static int nextFault;
  private static String lastApplied = "<none>";

  private FeedbackProbe() {}

  private static List<Fault> parseFaults() {
    List<Fault> faults = new ArrayList<>();
    String value = System.getProperty("solr103940.v2.faults", "");
    if (!value.isEmpty()) for (String item : value.split(";")) faults.add(new Fault(item));
    return faults;
  }

  private static BufferedWriter openTrace() {
    String path = System.getProperty("solr103940.v2.trace", "");
    if (path.isEmpty()) return null;
    try { return new BufferedWriter(new FileWriter(path)); }
    catch (IOException error) { throw new ExceptionInInitializerError(error); }
  }

  private static void event(String kind, String payload) {
    long current = ++sequence;
    if (TRACE == null) return;
    try {
      TRACE.write(current + "\t" + System.nanoTime() + "\t" + kind + "\t" + payload + "\n");
      TRACE.flush();
    } catch (IOException error) { throw new IllegalStateException(error); }
  }

  private static String safe(String value) {
    return value == null ? "<null>" : value.replace('\t', '_').replace('\n', '_');
  }

  /** ZkController supplies the actual SolrZkClient receiver and its reader's AliasesManager. */
  public static synchronized void registerNode(Object client, Object manager, String node) {
    if (client == null || manager == null || node == null)
      throw new IllegalArgumentException("Incomplete SolrZkClient/AliasesManager registration");
    NODE_BY_CLIENT.put(client, node);
    MANAGER_BY_CLIENT.put(client, manager);
    event("ACTOR_REGISTERED", "client_id=" + System.identityHashCode(client) +
        "\tmanager_id=" + System.identityHashCode(manager) + "\tnode=" + safe(node));
  }

  /** The MiniSolrCloudCluster passes its node1..node4 instance name, independent of ephemeral ports. */
  public static synchronized void registerJettyRole(String role, String node) {
    if (!role.matches("node[1-4]") || node == null)
      throw new IllegalArgumentException("Invalid Jetty role: " + role + " / " + node);
    String prior = ROLE_BY_NODE.put(node, role);
    if (prior != null && !prior.equals(role))
      throw new IllegalStateException("One runtime node acquired two Jetty roles");
    event("JETTY_ROLE_BOUND", "role=" + role + "\tnode=" + safe(node));
  }

  private static String stableCaller() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      String name = frame.getClassName();
      if (name.startsWith("org.apache.solr.") &&
          !name.equals("org.apache.solr.common.cloud.SolrZkClient"))
        return name + "#" + frame.getMethodName() + ":" + frame.getLineNumber();
    }
    return "<external>";
  }

  public static synchronized void io(String operation, String path, Object receiver)
      throws KeeperException.ConnectionLossException {
    String node = NODE_BY_CLIENT.get(receiver);
    String role = node == null ? null : ROLE_BY_NODE.get(node);
    String caller = "caller=" + stableCaller();
    String actor = "actor=" + (role == null ? "unbound" : "jetty:" + role);
    String identity = operation + "\t" + safe(path);
    String runtime = "\tnode=" + safe(node) + "\tclient_id=" +
        System.identityHashCode(receiver) + "\tmanager_id=" +
        (MANAGER_BY_CLIENT.containsKey(receiver)
            ? System.identityHashCode(MANAGER_BY_CLIENT.get(receiver)) : -1) +
        "\tthread=" + safe(Thread.currentThread().getName());
    event("IO_OBSERVED", identity + "\t" + caller + "\t" + actor + runtime);
    int active = nextFault;
    for (int index = 0; index < FAULTS.size(); index++) {
      Fault fault = FAULTS.get(index);
      if (operation.equals(fault.operation) && fault.path.equals(path) &&
          fault.caller.equals(caller) && fault.actor.equals(actor)) {
        fault.globalSeen++;
        if (!fault.relative || index == active) fault.seen++;
      }
    }
    if (active >= FAULTS.size()) return;
    Fault fault = FAULTS.get(active);
    if (!operation.equals(fault.operation) || !fault.path.equals(path) ||
        !fault.caller.equals(caller) || !fault.actor.equals(actor) ||
        fault.seen != fault.ordinal) return;
    if (fault.relative && !fault.after.equals("after=" + lastApplied))
      throw new IllegalStateException("Fault phase mismatch: " + fault.after);
    String details = identity + "\tordinal=" + (fault.relative ? "@" : "") +
        fault.ordinal + "\trelative_count=" + (fault.relative ? fault.seen : 0) +
        "\tglobal_hit_ordinal=" + fault.globalSeen + "\tseed_global=" +
        fault.seedGlobal + "\tprevious_fault_id=" + lastApplied +
        "\tfault_id=F" + active + "\tplan_index=" + active +
        "\t" + caller + "\t" + actor + runtime;
    event("IO_MATCHED", details);
    event("IO_APPLIED_CONNECTION_LOSS", details);
    lastApplied = "F" + active;
    nextFault++;
    throw new KeeperException.ConnectionLossException();
  }

  /** Assert the guard and I/O refer to the same real reader/alias manager. */
  public static synchronized void targetCheck(boolean missing, String site, String alias,
                                              String context, Object client, Object manager,
                                              String node) {
    if (!NODE_BY_CLIENT.containsKey(client) ||
        !node.equals(NODE_BY_CLIENT.get(client)) ||
        MANAGER_BY_CLIENT.get(client) != manager)
      throw new IllegalStateException("Selected guard has unbound or mismatched alias reader");
    String role = ROLE_BY_NODE.get(node);
    if (role == null) throw new IllegalStateException("Selected guard has no Jetty role");
    String identity = site + "\t" + safe(alias) + "\t" + safe(context) +
        "\tactor=jetty:" + role + "\tnode=" + safe(node) +
        "\tclient_id=" + System.identityHashCode(client) +
        "\tmanager_id=" + System.identityHashCode(manager) +
        "\tlast_fault=" + lastApplied;
    event("TARGET_CHECK", (missing ? "missing" : "present") + "\t" + identity);
    if (missing) event("TARGET_EXCEPTION", identity);
  }
}
