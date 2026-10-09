package edu.uva.liftlab.mallory.hbase.zkmonitor;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.WeakHashMap;

/** Exact same-tracker monitor transfers for HBase's ZKNodeTracker. */
public final class TrackerMonitorHooks {
  private static final Map<Object, IdentityHashMap<Thread, Waiter>> WAITERS =
      new WeakHashMap<Object, IdentityHashMap<Thread, Waiter>>();

  private TrackerMonitorHooks() { }

  /** Bind the callback to the watcher registered from its actual MiniCluster server. */
  public static Scope enterCallback(Object tracker) {
    Object watcher = null;
    try {
      for (Class<?> type = tracker.getClass(); type != null; type = type.getSuperclass()) {
        try {
          Field field = type.getDeclaredField("watcher");
          field.setAccessible(true);
          watcher = field.get(tracker);
          break;
        } catch (NoSuchFieldException ignored) { }
      }
    } catch (ReflectiveOperationException | RuntimeException ignored) {
      // Missing owner remains unknown. A guessed server name would create a false edge.
    }
    return new Scope(Probe.withRegisteredNode(watcher));
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
    @Override public void close() { node.close(); }
  }
}
