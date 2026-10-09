package baseline.solr19v2;

import java.io.FileWriter;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Iterator;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import org.apache.solr.common.params.SolrParams;
import org.apache.zookeeper.KeeperException;

/** Case-local, observation-only lineage recorder for the original JUnit. */
public final class ActorProbe {
  private static long sequence;
  private static int nextJettyRole;
  private static final Map<Object, String> ZK_CLIENT_ROLE = new IdentityHashMap<>();
  private static final Map<String, String> ROLE_BY_NODE = new java.util.HashMap<>();
  private static final Map<String, String> OWNER_BY_CORE = new java.util.HashMap<>();
  private static final Map<String, String> PRODUCER_BY_CORE = new java.util.HashMap<>();
  private static final List<Fault> FAULTS = parseFaults();
  private static int nextFault;

  private static final class Fault {
    final String operation, path, caller, actor;
    final int ordinal;
    int seen;

    Fault(String spec) {
      String[] parts = spec.split("\\|", -1);
      if (parts.length != 5) throw new IllegalArgumentException("Expected OP|PATH|CALLER|ACTOR|ORDINAL: " + spec);
      operation = parts[0];
      path = parts[1];
      caller = parts[2];
      actor = parts[3];
      ordinal = Integer.parseInt(parts[4]);
      if (ordinal <= 0 || actor.equals("UNBOUND") || operation.isEmpty() || path.isEmpty() || caller.isEmpty())
        throw new IllegalArgumentException("Invalid actor-aware I/O selector: " + spec);
    }
  }

  private static List<Fault> parseFaults() {
    List<Fault> faults = new ArrayList<>();
    String value = System.getProperty("solr19v2.faults", "");
    if (!value.isEmpty()) for (String spec : value.split(";")) faults.add(new Fault(spec));
    return faults;
  }

  private ActorProbe() {}

  private static String clean(Object value) {
    if (value == null) return "<null>";
    return String.valueOf(value).replace('\\', '/').replace('\t', ' ').replace('\n', ' ').replace('\r', ' ');
  }

  private static boolean selected(Object core) {
    return core != null && String.valueOf(core).startsWith("testAddMultipleReplicas_");
  }

  private static synchronized void emit(String phase, Object core, Object actor, Object endpoint,
                                        Object standard, Object override, Object effective,
                                        Object detail) {
    if (!selected(core) && !phase.startsWith("IO_") && !phase.startsWith("FAULT_") && !phase.equals("ZK_BIND")) return;
    String destination = System.getProperty("solr19v2.trace");
    if (destination == null || destination.isEmpty()) return;
    try (FileWriter out = new FileWriter(destination, true)) {
      out.write(++sequence + "\t" + System.nanoTime() + "\t" + clean(Thread.currentThread().getName())
          + "\t" + phase + "\t" + clean(core) + "\t" + clean(actor) + "\t" + clean(endpoint)
          + "\t" + clean(standard) + "\t" + clean(override) + "\t" + clean(effective)
          + "\t" + clean(detail) + "\n");
    } catch (IOException ignored) {
      // The recorder must not change the original test's control flow.
    }
  }

  private static String properties(SolrParams params) {
    List<String> entries = new ArrayList<>();
    Iterator<String> names = params.getParameterNamesIterator();
    while (names.hasNext()) {
      String name = names.next();
      if (name.startsWith("property.")) entries.add(name + "=" + params.get(name));
    }
    Collections.sort(entries);
    return String.join(";", entries);
  }

  public static void sender(String kind, SolrParams params, String node, String baseUrl,
                            Object producerClient) {
    String producerRole;
    synchronized (ActorProbe.class) {
      producerRole = ZK_CLIENT_ROLE.get(producerClient);
      OWNER_BY_CORE.put(params.get("name"), node);
      PRODUCER_BY_CORE.put(params.get("name"), producerRole);
    }
    emit("SEND_" + kind, params.get("name"), node, baseUrl, params.get("coreNodeName"),
        params.get("property.coreNodeName"), "", properties(params) + "|sourceRole="
            + (producerRole == null ? "UNBOUND" : producerRole));
  }

  public static void receiver(SolrParams params, Map<String, String> coreParams, String node) {
    emit("RECEIVE_CREATE", params.get("name"), node, "", params.get("coreNodeName"),
        params.get("property.coreNodeName"), coreParams.get("coreNodeName"), properties(params));
  }

  public static void descriptor(String phase, String name, Object instanceDir,
                                String input, String effective) {
    emit("DESCRIPTOR_" + phase, name, "", instanceDir, input, "", effective, "");
  }

  public static void file(String name, Object path, boolean exists, String before) {
    emit("EXTRA_PROPERTIES_FILE", name, "", path, before, "", "", exists);
  }

  public static void fileOpen(String name, Object path) {
    emit("FILE_OPEN", name, "", path, "", "", "", caller());
  }

  public static void target(String name, String node, Object instanceDir,
                            String standard, String effective, boolean missing) {
    emit("TARGET_GUARD", name, node, instanceDir, standard, "", effective,
        missing ? "missing" : "present");
  }

  private static String caller() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      String className = frame.getClassName();
      if (className.startsWith("org.apache.solr.") &&
          !className.equals("org.apache.solr.common.cloud.SolrZkClient")) {
        return className + "#" + frame.getMethodName() + ":" + frame.getLineNumber();
      }
    }
    return "<external>";
  }

  public static synchronized void bindZkClient(Object client, String nodeName, String zkEndpoint) {
    String role = "JETTY_" + (++nextJettyRole);
    ZK_CLIENT_ROLE.put(client, role);
    ROLE_BY_NODE.put(nodeName, role);
    emit("ZK_BIND", nodeName, role, zkEndpoint, "", "", "", "client=" + System.identityHashCode(client));
  }

  private static String resolveActor(String actor) {
    if (actor.startsWith("OWNER_OF_CORE:")) {
      return ROLE_BY_NODE.get(OWNER_BY_CORE.get(actor.substring("OWNER_OF_CORE:".length())));
    }
    if (actor.startsWith("PRODUCER_OF_CORE:")) {
      return PRODUCER_BY_CORE.get(actor.substring("PRODUCER_OF_CORE:".length()));
    }
    return actor;
  }

  public static synchronized void io(String operation, String path, String zkEndpoint, Object client)
      throws KeeperException.ConnectionLossException {
    String role;
    role = ZK_CLIENT_ROLE.get(client);
    String callsite = caller();
    emit("IO_" + operation, path, role == null ? "UNBOUND" : role,
        zkEndpoint, "", "", "", callsite);
    if (role == null || nextFault >= FAULTS.size()) return;
    Fault fault = FAULTS.get(nextFault);
    if (!operation.equals(fault.operation) || path == null || !path.equals(fault.path)
        || !callsite.equals(fault.caller) || !role.equals(resolveActor(fault.actor))) return;
    if (++fault.seen != fault.ordinal) return;
    String detail = "index=" + nextFault + ";ordinal=" + fault.ordinal
        + ";actorSpec=" + fault.actor + ";caller=" + callsite;
    emit("FAULT_MATCHED", path, role, zkEndpoint, "", "", "", detail);
    nextFault++;
    emit("FAULT_APPLIED_CONNECTION_LOSS", path, role, zkEndpoint, "", "", "", detail);
    throw new KeeperException.ConnectionLossException();
  }
}
