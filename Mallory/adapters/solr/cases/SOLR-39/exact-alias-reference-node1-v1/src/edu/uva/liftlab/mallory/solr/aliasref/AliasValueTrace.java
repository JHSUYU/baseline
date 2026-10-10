package edu.uva.liftlab.mallory.solr.aliasref;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.lang.reflect.Method;
import java.util.IdentityHashMap;

/** Records exact Java reference identity without changing the shared Mallory core. */
public final class AliasValueTrace {
  private static final IdentityHashMap<Object, Long> IDS = new IdentityHashMap<Object, Long>();
  private static long nextId;

  private AliasValueTrace() { }

  public static void read(Object owner, Object value) {
    try { record("read", owner, value); }
    catch (RuntimeException ignored) { /* Observation must not change the field read. */ }
  }

  public static void write(Object owner, Object value) {
    try { record("write", owner, value); }
    catch (RuntimeException ignored) { /* Observation must not change the field write. */ }
  }

  private static synchronized long id(Object object) {
    if (object == null) return 0;
    Long known = IDS.get(object);
    if (known == null) {
      known = Long.valueOf(++nextId);
      IDS.put(object, known);
    }
    return known.longValue();
  }

  private static int zkVersion(Object aliases) {
    if (aliases == null) return -1;
    try {
      Method getter = aliases.getClass().getMethod("getZNodeVersion");
      return ((Number) getter.invoke(aliases)).intValue();
    } catch (ReflectiveOperationException | RuntimeException ignored) {
      return -2;
    }
  }

  private static String quoted(String value) {
    if (value == null) return "null";
    return "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"")
        .replace("\n", "\\n").replace("\r", "\\r") + "\"";
  }

  private static synchronized void record(String kind, Object owner, Object value) {
    if (!"1".equals(System.getenv("MALLORY_ALIAS_REF_TRACE"))) return;
    System.err.println("MALLORY_ALIAS_REF {\"kind\":" + quoted(kind)
        + ",\"node\":" + quoted(Probe.currentNode())
        + ",\"epoch\":" + Probe.currentEpoch()
        + ",\"thread_id\":" + Thread.currentThread().getId()
        + ",\"ts_ns\":" + System.nanoTime()
        + ",\"context\":" + quoted(Probe.captureContext())
        + ",\"owner_ref\":" + id(owner)
        + ",\"aliases_ref\":" + id(value)
        + ",\"zk_version\":" + zkVersion(value) + "}");
  }
}
