package edu.uva.liftlab.mallory.hbase.hbckconsume;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.lang.ref.ReferenceQueue;
import java.lang.ref.WeakReference;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Collections;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.WeakHashMap;

/** One worker-published handoff token per exact Result object consumed by the meta visitor. */
public final class HbckScannerConsumeHooks {
  private static final ReferenceQueue<Object> STALE_RESULTS = new ReferenceQueue<>();
  private static final Map<IdentityRef, String> RESULTS = new HashMap<>();
  private static final Map<Object, Boolean> PUBLISHED_FUTURES =
      Collections.synchronizedMap(new WeakHashMap<Object, Boolean>());
  private static final String AMBIGUOUS = "<ambiguous>";

  private HbckScannerConsumeHooks() { }

  /** Called by the worker after its future.result is set and before waiter notification. */
  public static void publishFutureRows(Object future) {
    if (future == null) return;
    try {
      Field obtained = future.getClass().getDeclaredField("resultObtained");
      obtained.setAccessible(true);
      if (!obtained.getBoolean(future)) return;
      Field result = future.getClass().getDeclaredField("result");
      result.setAccessible(true);
      Object value = result.get(future);
      if (value == null) return;
      if (!"org.apache.hadoop.hbase.util.Pair".equals(value.getClass().getName())) return;
      Method getFirst = value.getClass().getMethod("getFirst");
      Object first = getFirst.invoke(value);
      if (!(first instanceof Object[])) return;
      Object[] rows = (Object[]) first;
      if (!"[Lorg.apache.hadoop.hbase.client.Result;".equals(first.getClass().getName()))
        return;
      synchronized (PUBLISHED_FUTURES) {
        if (PUBLISHED_FUTURES.put(future, Boolean.TRUE) != null) return;
      }
      IdentityHashMap<Object, Boolean> seen = new IdentityHashMap<>();
      for (Object row : rows) {
        if (row == null) continue;
        if (seen.put(row, Boolean.TRUE) != null) {
          synchronized (RESULTS) { RESULTS.put(new IdentityRef(row, STALE_RESULTS), AMBIGUOUS); }
        }
      }
      synchronized (RESULTS) {
        drainStale();
        for (Object row : rows) {
          if (row == null || seen.get(row) == null) continue;
          IdentityRef key = new IdentityRef(row, STALE_RESULTS);
          String previous = RESULTS.get(key);
          if (AMBIGUOUS.equals(previous)) continue;
          if (previous != null) {
            RESULTS.put(key, AMBIGUOUS);
            continue;
          }
          String token = Probe.newTaskToken();
          RESULTS.put(key, token);
          Probe.taskSubmit(token, "hbase:QueueingFuture.row-published");
        }
      }
    } catch (ReflectiveOperationException | RuntimeException ignored) {
      // Unsuccessful future or unknown Pair implementation: leave rows unbound.
    }
  }

  /** The visitor receives this exact Result object; remove its one-use identity mapping. */
  public static Probe.ContextScope enterConsumedResult(Object row) {
    if (row == null) return null;
    String token;
    synchronized (RESULTS) {
      drainStale();
      token = RESULTS.remove(new IdentityRef(row, null));
    }
    return token == null || AMBIGUOUS.equals(token) ? null
        : Probe.taskClaim(token, "hbase:MetaTableAccessor.scanMeta.visitor-result");
  }

  public static void leaveConsumedResult(Probe.ContextScope scope) {
    if (scope != null) scope.close();
  }

  private static void drainStale() {
    IdentityRef stale;
    while ((stale = (IdentityRef) STALE_RESULTS.poll()) != null) RESULTS.remove(stale);
  }

  private static final class IdentityRef extends WeakReference<Object> {
    private final int hash;
    IdentityRef(Object value, ReferenceQueue<Object> queue) {
      super(value, queue);
      hash = System.identityHashCode(value);
    }
    @Override public int hashCode() { return hash; }
    @Override public boolean equals(Object other) {
      return this == other || (other instanceof IdentityRef && get() != null
          && get() == ((IdentityRef) other).get());
    }
  }
}
