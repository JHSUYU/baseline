package edu.uva.liftlab.mallory.solr31;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/** Observes real retry attempts. The standard FaultPlan decides each exact injection. */
public final class RetryAttemptHook {
  public static final String SITE =
      "org.apache.solr.common.cloud.SolrZkClient#lambda$getData$6"
      + "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Lorg/apache/zookeeper/data/Stat;)[B"
      + "@349:door:lowlevel-retry";
  private static final String COLLECTION = "forceleader_lower_terms_collection";
  private static final String PATH = "/collections/" + COLLECTION + "/state.json";
  private static final String REGION = "solr31:ZkStateReader.StateWatcher.refreshAndWatch";
  private static final String EXCEPTION =
      "org.apache.zookeeper.KeeperException$ConnectionLossException";
  private static final ConcurrentHashMap<String, AtomicLong> READ_ORDINALS =
      new ConcurrentHashMap<String, AtomicLong>();
  private static final ThreadLocal<Read> CURRENT = new ThreadLocal<Read>();

  private RetryAttemptHook() { }

  public static void beforeAttempt(Object client, String path, Object watcher, Object stat) {
    String node = Probe.currentNode();
    int epoch = Probe.currentEpoch();
    String occurrence = Probe.captureContext();
    if (client == null || stat == null || watcher == null || !PATH.equals(path)
        || node == null || "unknown".equals(node) || occurrence == null
        || !occurrence.contains(":" + REGION + ":")
        || !"org.apache.solr.common.cloud.ZkStateReader$StateWatcher"
            .equals(watcher.getClass().getName())) return;
    Object reader = field(watcher, "this$0");
    if (reader == null || client != call(reader, "getZkClient")
        || !COLLECTION.equals(field(watcher, "coll"))) return;
    try (Probe.NodeScope registered = Probe.withRegisteredNode(reader)) {
      if (!node.equals(Probe.currentNode()) || epoch != Probe.currentEpoch()) return;
    }
    Object keeper = field(client, "keeper");
    Object executor = field(client, "zkCmdExecutor");
    Object retryCount = field(executor, "retryCount");
    Object session = call(keeper, "getSessionId");
    if (!(retryCount instanceof Number) || !(session instanceof Number)
        || ((Number) retryCount).intValue() < 2) return;

    Read read = CURRENT.get();
    if (read == null || read.client != client || read.watcher != watcher
        || read.stat != stat || !read.occurrence.equals(occurrence)
        || !read.node.equals(node) || read.epoch != epoch) {
      String key = node + "|" + epoch + "|" + COLLECTION;
      long rank = READ_ORDINALS.computeIfAbsent(key, ignored -> new AtomicLong())
          .incrementAndGet();
      read = new Read(client, watcher, stat, reader, keeper, occurrence, node, epoch,
          rank, ((Number) session).longValue(), ((Number) retryCount).intValue());
      CURRENT.set(read);
    }
    read.attempt++;
    boolean stable = read.keeper == keeper && read.session == ((Number) session).longValue()
        && read.retryCount == ((Number) retryCount).intValue();
    record("attempt", read, stable, -1);
    if (!stable) return; // Fail closed on reconnect/session or executor changes.

    String selectedNode = System.getenv("MALLORY_SOLR31_RETRY_ACTOR");
    String selectedEpoch = System.getenv("MALLORY_SOLR31_RETRY_EPOCH");
    String selectedRank = System.getenv("MALLORY_SOLR31_RETRY_READ_ORDINAL");
    boolean healthyObservation = selectedNode == null && selectedEpoch == null
        && selectedRank == null;
    if (healthyObservation || selectedNode != null && selectedNode.equals(node)
        && selectedEpoch != null && selectedEpoch.equals(Integer.toString(epoch))
        && selectedRank != null && selectedRank.equals(Long.toString(read.rank)))
      Probe.beforeDoor(SITE, EXCEPTION);
  }

  public static void afterSuccess(Object client, String path, Object watcher, Object stat) {
    Read read = CURRENT.get();
    if (read != null && read.client == client && read.watcher == watcher
        && read.stat == stat && PATH.equals(path)) {
      Object version = call(stat, "getVersion");
      record("success", read, true, version instanceof Number
          ? ((Number) version).intValue() : -1);
    }
  }

  private static void record(String phase, Read read, boolean stable, int statVersion) {
    System.err.println("MALLORY_SOLR31_RETRY phase=" + phase
        + " ts=" + System.nanoTime() + " node=" + read.node + " epoch=" + read.epoch
        + " thread_id=" + Thread.currentThread().getId()
        + " occurrence=" + read.occurrence + " collection=" + COLLECTION
        + " path=" + PATH + " reader_id=" + id(read.reader)
        + " client_id=" + id(read.client) + " keeper_id=" + id(read.keeper)
        + " session_id=" + read.session + " read_ordinal=" + read.rank
        + " attempt=" + read.attempt + " retry_count=" + read.retryCount
        + " stable_session=" + stable + " stat_version=" + statVersion);
  }

  private static String id(Object value) {
    return value == null ? "null" : Integer.toHexString(System.identityHashCode(value));
  }

  private static Object field(Object receiver, String name) {
    if (receiver == null) return null;
    for (Class<?> type = receiver.getClass(); type != null; type = type.getSuperclass()) {
      try {
        Field field = type.getDeclaredField(name);
        field.setAccessible(true);
        return field.get(receiver);
      } catch (NoSuchFieldException ignored) {
        // Try the superclass.
      } catch (ReflectiveOperationException | RuntimeException failure) {
        return null;
      }
    }
    return null;
  }

  private static Object call(Object receiver, String name) {
    if (receiver == null) return null;
    try {
      Method method = receiver.getClass().getMethod(name);
      return method.invoke(receiver);
    } catch (ReflectiveOperationException | RuntimeException failure) {
      return null;
    }
  }

  private static final class Read {
    final Object client, watcher, stat, reader, keeper;
    final String occurrence, node;
    final int epoch, retryCount;
    final long rank, session;
    long attempt;
    Read(Object client, Object watcher, Object stat, Object reader, Object keeper,
        String occurrence, String node, int epoch, long rank, long session, int retryCount) {
      this.client = client; this.watcher = watcher; this.stat = stat;
      this.reader = reader; this.keeper = keeper; this.occurrence = occurrence;
      this.node = node; this.epoch = epoch; this.rank = rank;
      this.session = session; this.retryCount = retryCount;
    }
  }
}
