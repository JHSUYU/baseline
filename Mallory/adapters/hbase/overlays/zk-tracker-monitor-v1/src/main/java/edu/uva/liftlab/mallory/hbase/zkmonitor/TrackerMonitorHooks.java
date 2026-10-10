package edu.uva.liftlab.mallory.hbase.zkmonitor;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;

/** Exact same-tracker monitor transfers for HBase's ZKNodeTracker. */
public final class TrackerMonitorHooks {
  private static final ThreadLocal<String> CONSTRUCTING_NODE = new ThreadLocal<String>();
  private static final Map<Object, IdentityHashMap<Thread, Waiter>> WAITERS =
      new IdentityHashMap<Object, IdentityHashMap<Thread, Waiter>>();

  private TrackerMonitorHooks() { }

  /** The MiniCluster factory knows the index before it constructs the server and its trackers. */
  public static FactoryScope enterConstruction(int index, String role) {
    if (index < 0 || !("rs".equals(role) || "master".equals(role)))
      throw new IllegalArgumentException("Expected a MiniCluster server role and index");
    String previous = CONSTRUCTING_NODE.get();
    String node = role + index;
    CONSTRUCTING_NODE.set(node);
    return new FactoryScope(previous, Probe.withNode(node, 0));
  }

  /** Bind a tracker operation through its exact abortable or watcher receiver. */
  public static Scope enterCallback(Object tracker) {
    Object abortable = field(tracker, "abortable");
    Object watcher = field(tracker, "watcher");
    String constructing = CONSTRUCTING_NODE.get();
    // In HBase 2.6.6, HRegionServer constructs both trackers with itself as abortable.
    // Its ZKWatcher has the same abortable; the factory scope supplies the real index.
    if (constructing != null && constructing.equals(Probe.currentNode()) && abortable != null
        && abortable == field(watcher, "abortable")) return new Scope(null);
    Probe.NodeScope owner = Probe.withRegisteredNode(abortable);
    if (!"unknown".equals(Probe.currentNode())) return new Scope(owner);
    owner.close();
    return new Scope(Probe.withRegisteredNode(watcher));
  }

  private static Object field(Object receiver, String name) {
    if (receiver == null) return null;
    try {
      for (Class<?> type = receiver.getClass(); type != null; type = type.getSuperclass()) {
        try {
          Field field = type.getDeclaredField(name);
          field.setAccessible(true);
          return field.get(receiver);
        } catch (NoSuchFieldException ignored) { }
      }
    } catch (ReflectiveOperationException | RuntimeException ignored) { }
    return null;
  }

  /** Called while holding the exact tracker monitor, just before Object.wait. */
  public static void beforeWait(Object tracker) {
    if (!Thread.holdsLock(tracker) || "unknown".equals(Probe.currentNode())) return;
    synchronized (WAITERS) {
      IdentityHashMap<Thread, Waiter> byThread = WAITERS.get(tracker);
      if (byThread == null) {
        byThread = new IdentityHashMap<Thread, Waiter>();
        WAITERS.put(tracker, byThread);
      }
      byThread.put(Thread.currentThread(), new Waiter());
    }
  }

  /**
   * Publish only to threads currently inside wait on this exact tracker. The caller must hold
   * the tracker monitor after a real data write or notifyAll; the consumer reacquires it before
   * calling afterWait. Each waiter gets a unique token because the graph requires one consumer.
   */
  public static void publish(Object tracker, String site) {
    if (!Thread.holdsLock(tracker) || "unknown".equals(Probe.currentNode())) return;
    List<String> tokens = new ArrayList<String>();
    synchronized (WAITERS) {
      IdentityHashMap<Thread, Waiter> byThread = WAITERS.get(tracker);
      if (byThread == null) return;
      for (Waiter waiter : byThread.values()) {
        if (waiter.token != null) continue;
        String token = Probe.newTaskToken();
        waiter.token = token;
        tokens.add(token);
      }
    }
    for (String token : tokens) Probe.taskSubmit(token, site);
  }

  /** Called after Object.wait returns and has reacquired the same monitor. */
  public static boolean afterWait(Object tracker) {
    Waiter waiter = remove(tracker);
    if (!Thread.holdsLock(tracker) || waiter == null || waiter.token == null) return false;
    try (Probe.ContextScope ignored = Probe.taskClaim(waiter.token,
        "hbase:ZKNodeTracker.blockUntilAvailable:monitor-reacquire")) { }
    return true;
  }

  /** An interrupted wait did not consume a callback. */
  public static void cancelledWait(Object tracker) { remove(tracker); }

  private static Waiter remove(Object tracker) {
    synchronized (WAITERS) {
      IdentityHashMap<Thread, Waiter> byThread = WAITERS.get(tracker);
      if (byThread == null) return null;
      Waiter waiter = byThread.remove(Thread.currentThread());
      if (byThread.isEmpty()) WAITERS.remove(tracker);
      return waiter;
    }
  }

  private static final class Waiter { String token; }

  public static final class Scope implements AutoCloseable {
    private final Probe.NodeScope node;
    private Scope(Probe.NodeScope node) { this.node = node; }
    @Override public void close() { if (node != null) node.close(); }
  }

  public static final class FactoryScope implements AutoCloseable {
    private final String previous;
    private final Probe.NodeScope node;
    private FactoryScope(String previous, Probe.NodeScope node) {
      this.previous = previous;
      this.node = node;
    }
    @Override public void close() {
      node.close();
      if (previous == null) CONSTRUCTING_NODE.remove();
      else CONSTRUCTING_NODE.set(previous);
    }
  }
}
