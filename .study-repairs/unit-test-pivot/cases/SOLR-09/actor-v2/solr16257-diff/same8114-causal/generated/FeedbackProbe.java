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
    if (Boolean.getBoolean("solr09.diagnostic.read_actual")) {
      try {
        org.apache.zookeeper.data.Stat stat = new org.apache.zookeeper.data.Stat();
        byte[] raw = overseerClient.getData("/collections/" + collection + "/state.json",
            null, stat, true);
        String json = new String(raw, java.nio.charset.StandardCharsets.UTF_8);
        event("ZK_ACTUAL_STATE", "collection=" + safe(collection)
            + "\treplica=" + safe(replicaName)
            + "\treplica_present=" + json.contains("\"" + replicaName + "\"")
            + "\tzk_version=" + stat.getVersion()
            + "\traw_json=" + safe(json));
      } catch (Exception error) {
        event("ZK_ACTUAL_STATE_ERROR", error.getClass().getName()
            + ":" + safe(error.getMessage()));
      }
    }
    if (couldNotRemove) event("TARGET_EXCEPTION", identity);
  }
  /** Diagnostic only: inspect both existing maps without refreshing either. */
  public static synchronized void readerMapState(
      org.apache.solr.common.cloud.ZkStateReader reader,
      String collection, String shard, String replicaName) {
    if (!Boolean.getBoolean("solr09.diagnostic.read_actual")) return;
    try {
      java.lang.reflect.Field watchesField = reader.getClass().getDeclaredField("collectionWatches");
      java.lang.reflect.Field cachedField = reader.getClass().getDeclaredField("watchedCollectionStates");
      watchesField.setAccessible(true);
      cachedField.setAccessible(true);
      java.util.Map<?, ?> watches = (java.util.Map<?, ?>) watchesField.get(reader);
      java.util.Map<?, ?> cached = (java.util.Map<?, ?>) cachedField.get(reader);
      Object watch = watches.get(collection);
      int watcherCount = -1;
      int coreRefCount = -1;
      if (watch != null) {
        java.lang.reflect.Field stateWatchersField = watch.getClass().getDeclaredField("stateWatchers");
        java.lang.reflect.Field coreRefCountField = watch.getClass().getDeclaredField("coreRefCount");
        stateWatchersField.setAccessible(true);
        coreRefCountField.setAccessible(true);
        watcherCount = ((java.util.Set<?>) stateWatchersField.get(watch)).size();
        coreRefCount = coreRefCountField.getInt(watch);
      }
      org.apache.solr.common.cloud.DocCollection state =
          (org.apache.solr.common.cloud.DocCollection) cached.get(collection);
      org.apache.solr.common.cloud.Slice slice = state == null ? null : state.getSlice(shard);
      boolean replicaPresent = slice != null && slice.getReplica(replicaName) != null;
      event("READER_MAP_STATE", "collection=" + safe(collection)
          + "\twatch_present=" + watches.containsKey(collection)
          + "\tcached_present=" + (state != null)
          + "\tcached_replica_present=" + replicaPresent
          + "\tcached_version=" + (state == null ? -1 : state.getZNodeVersion())
          + "\twatcher_count=" + watcherCount
          + "\tcore_ref_count=" + coreRefCount
          + "\treader_id=" + System.identityHashCode(reader)
          + "\tclient_id=" + System.identityHashCode(reader.getZkClient()));
    } catch (Exception error) {
      event("READER_MAP_STATE_ERROR", error.getClass().getName()
          + ":" + safe(error.getMessage()));
    }
  }

  /** Diagnostic only: read the selected core's on-disk instance and data paths. */
  public static synchronized void coreDirectoryState(String core) {
    if (!Boolean.getBoolean("solr09.diagnostic.read_actual")) return;
    java.io.File scratch = new java.io.File(System.getProperty("java.io.tmpdir"));
    java.io.File[] suites = scratch.listFiles();
    if (suites == null) return;
    for (java.io.File suite : suites) {
      java.io.File[] temps = suite.listFiles();
      if (temps == null) continue;
      for (java.io.File temp : temps) {
        if (!temp.getName().startsWith("tempDir")) continue;
        java.io.File[] nodes = temp.listFiles();
        if (nodes == null) continue;
        for (java.io.File node : nodes) {
          if (!node.getName().matches("node[0-9]+")) continue;
          java.io.File instance = new java.io.File(node, core);
          java.io.File data = new java.io.File(instance, "data");
          event("CORE_DIR_STATE", "core=" + safe(core)
              + "\tinstance=" + safe(instance.getAbsolutePath())
              + "\tinstance_exists=" + instance.exists()
              + "\tdata_exists=" + data.exists());
        }
      }
    }
  }

  /** Diagnostic only: inspect the selected reader immediately before timeout cleanup. */
  public static synchronized void preTimeoutState(
      org.apache.solr.common.cloud.ZkStateReader reader, String collection) {
    if (!Boolean.getBoolean("solr09.diagnostic.read_actual")
        || reader.getZkClient() != targetOverseerClient) return;
    try {
      java.lang.reflect.Field watchesField = reader.getClass().getDeclaredField("collectionWatches");
      java.lang.reflect.Field cachedField = reader.getClass().getDeclaredField("watchedCollectionStates");
      watchesField.setAccessible(true);
      cachedField.setAccessible(true);
      java.util.Map<?, ?> watches = (java.util.Map<?, ?>) watchesField.get(reader);
      java.util.Map<?, ?> cached = (java.util.Map<?, ?>) cachedField.get(reader);
      Object watch = watches.get(collection);
      int watcherCount = -1;
      int coreRefCount = -1;
      if (watch != null) {
        java.lang.reflect.Field stateWatchersField = watch.getClass().getDeclaredField("stateWatchers");
        java.lang.reflect.Field coreRefCountField = watch.getClass().getDeclaredField("coreRefCount");
        stateWatchersField.setAccessible(true);
        coreRefCountField.setAccessible(true);
        watcherCount = ((java.util.Set<?>) stateWatchersField.get(watch)).size();
        coreRefCount = coreRefCountField.getInt(watch);
      }
      org.apache.solr.common.cloud.DocCollection state =
          (org.apache.solr.common.cloud.DocCollection) cached.get(collection);
      boolean corePresent = false;
      if (state != null) {
        for (org.apache.solr.common.cloud.Slice slice : state.getSlices()) {
          for (org.apache.solr.common.cloud.Replica replica : slice.getReplicas()) {
            if (replica.getCoreName().equals(targetCore)) corePresent = true;
          }
        }
      }
      event("PRE_TIMEOUT_READER_STATE", "collection=" + safe(collection)
          + "\tcore=" + safe(targetCore)
          + "\twatch_present=" + (watch != null)
          + "\twatcher_count=" + watcherCount
          + "\tcore_ref_count=" + coreRefCount
          + "\tcached_present=" + (state != null)
          + "\tcached_core_present=" + corePresent
          + "\tcached_version=" + (state == null ? -1 : state.getZNodeVersion())
          + "\treader_id=" + System.identityHashCode(reader)
          + "\tclient_id=" + System.identityHashCode(reader.getZkClient()));
    } catch (Exception error) {
      event("PRE_TIMEOUT_READER_STATE_ERROR", error.getClass().getName()
          + ":" + safe(error.getMessage()));
    }
  }

  /** Observe each bounded same-reader refresh without changing the selected guard. */
  public static synchronized void causalRefresh(String phase,
      org.apache.solr.common.cloud.ZkStateReader reader, String collection, int attempt,
      boolean cachePresent, long remainingLatch) {
    event("CAUSAL_REFRESH", "phase=" + safe(phase)
        + "\tcollection=" + safe(collection)
        + "\tattempt=" + attempt
        + "\tcache_present=" + cachePresent
        + "\tlatch_count=" + remainingLatch
        + "\treader_id=" + System.identityHashCode(reader)
        + "\tclient_id=" + System.identityHashCode(reader.getZkClient()));
  }

}
