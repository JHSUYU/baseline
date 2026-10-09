package baseline.solr09;

import java.io.BufferedWriter;
import java.io.FileWriter;
import java.io.IOException;
import java.util.ArrayList;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import org.apache.zookeeper.KeeperException;
import org.apache.solr.common.cloud.SolrZkClient;

/** Exact I/O identity and selected-check events for the original cluster JUnit. */
public final class FeedbackProbe {
  private static final class Fault {
    final String operation;
    final String pathPart;
    final String caller;
    final String actor;
    final int ordinal;
    final boolean relative;
    final String afterFaultId;
    final int seedGlobalOrdinal;
    int seen;
    int globalSeen;
    boolean applied;

    Fault(String spec) {
      String[] parts = spec.split("\\|", -1);
      if (parts.length != 5 && parts.length != 7)
        throw new IllegalArgumentException("Invalid fault: " + spec);
      operation = parts[0];
      pathPart = parts[1];
      relative = parts[2].startsWith("@");
      ordinal = Integer.parseInt(relative ? parts[2].substring(1) : parts[2]);
      if (!parts[3].startsWith("caller="))
        throw new IllegalArgumentException("Fault selector needs exact caller: " + spec);
      caller = parts[3];
      if (!parts[4].startsWith("actor="))
        throw new IllegalArgumentException("Fault selector needs logical actor: " + spec);
      actor = parts[4];
      if (ordinal <= 0) throw new IllegalArgumentException("ordinal must be positive");
      if (relative != (parts.length == 7))
        throw new IllegalArgumentException("Relative fault needs phase anchor: " + spec);
      afterFaultId = relative ? parts[5].replaceFirst("^after=", "") : "";
      seedGlobalOrdinal = relative ? Integer.parseInt(parts[6].replaceFirst("^seed_global=", "")) : 0;
      if (relative && (!parts[5].startsWith("after=F") ||
          !parts[6].startsWith("seed_global=") || seedGlobalOrdinal <= 0))
        throw new IllegalArgumentException("Invalid relative fault anchor: " + spec);
    }
  }

  private static final List<Fault> FAULTS = parseFaults();
  private static final BufferedWriter TRACE = openTrace();
  private static long sequence;
  private static int nextFault;
  private static String lastAppliedFaultId = "<none>";
  private static final Map<Object, String> NODE_BY_CLIENT = new IdentityHashMap<>();
  private static volatile Object targetOverseerClient;
  private static volatile String targetOverseerNode;
  private static volatile String targetReplicaNode;
  private static volatile String targetCore;

  private FeedbackProbe() {}

  private static List<Fault> parseFaults() {
    List<Fault> faults = new ArrayList<>();
    String value = System.getProperty("solr09.faults", "");
    if (!value.isEmpty()) for (String item : value.split(";")) faults.add(new Fault(item));
    return faults;
  }

  private static BufferedWriter openTrace() {
    String path = System.getProperty("solr09.trace", "");
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

  private static String safe(String text) {
    return text == null ? "<null>" : text.replace('\t', '_').replace('\n', '_');
  }

  /** Register a concrete Solr node before its asynchronous ZooKeeper callbacks. */
  public static synchronized void registerNode(SolrZkClient client, String nodeName) {
    NODE_BY_CLIENT.put(client, nodeName);
    event("ACTOR_REGISTERED", "client_id=" + System.identityHashCode(client)
        + "\tnode=" + safe(nodeName));
  }

  /** Bind the selected command's reader and replica roles before submitting UNLOAD. */
  public static synchronized void bindTargetReader(SolrZkClient overseerClient,
                                                   String overseerNode,
                                                   String replicaNode,
                                                   String core) {
    targetOverseerClient = overseerClient;
    targetOverseerNode = overseerNode;
    targetReplicaNode = replicaNode;
    targetCore = core;
    event("TARGET_ACTORS_BOUND", "overseer_client_id="
        + System.identityHashCode(overseerClient)
        + "\toverseer_node=" + safe(overseerNode)
        + "\treplica_node=" + safe(replicaNode)
        + "\tcore=" + safe(core));
  }

  private static String actorForClient(Object client) {
    if (client == targetOverseerClient) return "target_overseer";
    String node = NODE_BY_CLIENT.get(client);
    if (node == null) return "unregistered_client";
    if (node.equals(targetReplicaNode)) return "target_replica_node";
    return "other_node";
  }

  private static String stableCaller() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      String className = frame.getClassName();
      if (className.startsWith("org.apache.solr.") &&
          !className.equals("org.apache.solr.common.cloud.SolrZkClient")) {
        return className + "#" + frame.getMethodName() + ":" + frame.getLineNumber();
      }
    }
    return "<external>";
  }

  public static synchronized void io(String operation, String path, SolrZkClient client)
      throws KeeperException.ConnectionLossException {
    String identity = operation + "\t" + safe(path);
    String callsite = "caller=" + stableCaller();
    String actor = "actor=" + actorForClient(client);
    String node = "\tnode=" + safe(NODE_BY_CLIENT.get(client));
    String runtime = "\tclient_id=" + System.identityHashCode(client)
        + "\tthread=" + safe(Thread.currentThread().getName());
    event("IO_OBSERVED", identity + "\t" + callsite + "\t" + actor + node + runtime);
    int activeFault = nextFault;
    for (int index = 0; index < FAULTS.size(); index++) {
      Fault fault = FAULTS.get(index);
      if (operation.equals(fault.operation) && path != null
          && path.equals(fault.pathPart) && callsite.equals(fault.caller)
          && actor.equals(fault.actor)) {
        fault.globalSeen++;
        if (!fault.relative || index == activeFault) fault.seen++;
      }
    }
    if (nextFault < FAULTS.size()) {
      Fault fault = FAULTS.get(nextFault);
      if (operation.equals(fault.operation) && path != null
          && path.equals(fault.pathPart) && fault.seen == fault.ordinal
          && callsite.equals(fault.caller) && actor.equals(fault.actor)) {
        if (fault.relative && !fault.afterFaultId.equals(lastAppliedFaultId))
          throw new IllegalStateException("Fault phase anchor mismatch: " + fault.afterFaultId);
        fault.applied = true;
        String details = identity + "\tordinal="
            + (fault.relative ? "@" : "") + fault.ordinal
            + "\trelative_count=" + (fault.relative ? fault.seen : 0)
            + "\tglobal_hit_ordinal=" + fault.globalSeen
            + "\tseed_global=" + fault.seedGlobalOrdinal
            + "\tprevious_fault_id=" + lastAppliedFaultId
            + "\tfault_id=F" + nextFault
            + "\tplan_index=" + nextFault + "\t" + callsite + "\t" + actor
            + node + runtime;
        event("IO_MATCHED", details);
        event("IO_APPLIED_CONNECTION_LOSS", details);
        lastAppliedFaultId = "F" + nextFault;
        nextFault++;
        throw new KeeperException.ConnectionLossException();
      }
    }
  }

  /** Observe the actual CoreAdmin HTTP request, just before network I/O. */
  public static synchronized void httpPost(String qt, String action, String core,
                                           String nodeName, String url) throws IOException {
    String operation = "HTTP_POST";
    boolean selectedReplica = core != null && core.equals(targetCore)
        && nodeName != null && nodeName.equals(targetReplicaNode)
        && "UNLOAD".equals(action);
    String path = safe(qt) + "?action=" + safe(action) + "&core="
        + (selectedReplica ? "<target>" : safe(core));
    String identity = operation + "\t" + path;
    String callsite = "caller=" + stableCaller();
    String actor = "actor=" + (selectedReplica ? "target_replica_http" : "other_http");
    String endpoint = "\tnode=" + safe(nodeName) + "\turl=" + safe(url)
        + "\tactual_core=" + safe(core)
        + "\tthread=" + safe(Thread.currentThread().getName());
    event("IO_OBSERVED", identity + "\t" + callsite + "\t" + actor + endpoint);
    int activeFault = nextFault;
    for (int index = 0; index < FAULTS.size(); index++) {
      Fault fault = FAULTS.get(index);
      if (operation.equals(fault.operation) && path.equals(fault.pathPart)
          && callsite.equals(fault.caller) && actor.equals(fault.actor)) {
        fault.globalSeen++;
        if (!fault.relative || index == activeFault) fault.seen++;
      }
    }
    if (nextFault < FAULTS.size()) {
      Fault fault = FAULTS.get(nextFault);
      if (operation.equals(fault.operation) && path.equals(fault.pathPart)
          && fault.seen == fault.ordinal && callsite.equals(fault.caller)
          && actor.equals(fault.actor)) {
        if (fault.relative && !fault.afterFaultId.equals(lastAppliedFaultId))
          throw new IllegalStateException("Fault phase anchor mismatch: " + fault.afterFaultId);
        String details = identity + "\tordinal="
            + (fault.relative ? "@" : "") + fault.ordinal
            + "\trelative_count=" + (fault.relative ? fault.seen : 0)
            + "\tglobal_hit_ordinal=" + fault.globalSeen
            + "\tseed_global=" + fault.seedGlobalOrdinal
            + "\tprevious_fault_id=" + lastAppliedFaultId
            + "\tfault_id=F" + nextFault
            + "\tplan_index=" + nextFault + "\t" + callsite + "\t" + actor
            + endpoint;
        event("IO_MATCHED", details);
        event("IO_APPLIED_IO_EXCEPTION", details);
        lastAppliedFaultId = "F" + nextFault;
        nextFault++;
        throw new IOException("Injected CoreAdmin HTTP I/O failure at " + path);
      }
    }
  }

  public static synchronized void targetCheck(boolean couldNotRemove,
                                               String collection, String shard,
                                               String replicaName, String core,
                                               boolean nodeLive,
                                               SolrZkClient overseerClient,
                                               String overseerNode) {
    if (overseerClient != targetOverseerClient)
      throw new IllegalStateException("Selected guard changed Overseer reader identity");
    String identity = "SOLR-09\t" + safe(collection) + "\t" + safe(shard)
        + "\t" + safe(replicaName) + "\t" + safe(core)
        + "\tnode_live=" + nodeLive
        + "\toverseer_client_id=" + System.identityHashCode(overseerClient)
        + "\toverseer_node=" + safe(overseerNode)
        + "\treplica_node=" + safe(targetReplicaNode);
    event("TARGET_CHECK", (couldNotRemove ? "not_removed" : "removed")
        + "\t" + identity);
    if (couldNotRemove) event("TARGET_EXCEPTION", identity);
  }
}
