package edu.uva.liftlab.mallory.hbase.hbckconsume;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.lang.ref.ReferenceQueue;
import java.lang.ref.WeakReference;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.HashMap;
import java.util.Map;

/** Carries the exact completed scanner future's token to a consumed meta Result. */
public final class HbckScannerConsumeHooks {
  private static final ReferenceQueue<Object> STALE_RESULTS = new ReferenceQueue<>();
  private static final Map<IdentityRef, String> RESULTS = new HashMap<>();
  private static final String AMBIGUOUS = "<ambiguous>";

  private HbckScannerConsumeHooks() { }

  /** Called only on successful QueueingFuture.get() return. No token is inferred from time. */
  public static void futureValueReturned(Object future, Object value) {
    String token = publishedToken(future);
    if (token == null || value == null) return;
    try {
      if (!"org.apache.hadoop.hbase.util.Pair".equals(value.getClass().getName())) return;
      Method getFirst = value.getClass().getMethod("getFirst");
      Object first = getFirst.invoke(value);
      if (!(first instanceof Object[])) return;
      Object[] rows = (Object[]) first;
      if (!"[Lorg.apache.hadoop.hbase.client.Result;".equals(first.getClass().getName()))
        return;
      synchronized (RESULTS) {
        drainStale();
        for (Object row : rows) {
          if (row == null) continue;
          IdentityRef key = new IdentityRef(row, STALE_RESULTS);
          String previous = RESULTS.get(key);
          if (previous == null) RESULTS.put(key, token);
          else if (!previous.equals(token)) RESULTS.put(key, AMBIGUOUS);
        }
      }
    } catch (ReflectiveOperationException | RuntimeException ignored) {
      // Unknown Pair implementation or inaccessible future: leave the row unbound.
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

  private static String publishedToken(Object future) {
    if (future == null) return null;
    try {
      Class<?> hooks = Class.forName("edu.uva.liftlab.mallory.hbase.HBaseHooks", false,
          ClassLoader.getSystemClassLoader());
      Field tokenMapField = hooks.getDeclaredField("SCANNER_TOKENS");
      tokenMapField.setAccessible(true);
      Object tokenMapObject = tokenMapField.get(null);
      if (!(tokenMapObject instanceof Map)) return null;
      Object tokens;
      synchronized (tokenMapObject) { tokens = ((Map<?, ?>) tokenMapObject).get(future); }
      if (tokens == null) return null;
      Field published = tokens.getClass().getDeclaredField("resultPublished");
      published.setAccessible(true);
      if (!published.getBoolean(tokens)) return null;
      Field result = tokens.getClass().getDeclaredField("result");
      result.setAccessible(true);
      Object value = result.get(tokens);
      return value instanceof String && !((String) value).isEmpty() ? (String) value : null;
    } catch (ReflectiveOperationException | RuntimeException ignored) {
      return null;
    }
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
