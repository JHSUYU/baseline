package edu.uva.liftlab.mallory.hbase.masterbinding;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.lang.reflect.Field;

/** Bind a manager's actual ZKWatcher to the already registered MiniCluster master. */
public final class MasterTrackerHooks {
  private MasterTrackerHooks() { }

  public static void bindWatcherFromManager(Object manager) {
    if (manager == null) return;
    try {
      Object master = field(manager, "master");
      Object watcher = field(manager, "watcher");
      if (master == null || watcher == null) return;
      try (Probe.NodeScope ignored = Probe.withRegisteredNode(master)) {
        if ("unknown".equals(Probe.currentNode())) return;
        Probe.registerCurrentNode(watcher);
      }
    } catch (ReflectiveOperationException | RuntimeException ignored) {
      // A missing or conflicting runtime identity stays unbound; never infer it from a hostname.
    }
  }

  private static Object field(Object receiver, String name) throws ReflectiveOperationException {
    for (Class<?> type = receiver.getClass(); type != null; type = type.getSuperclass()) {
      try {
        Field field = type.getDeclaredField(name);
        field.setAccessible(true);
        return field.get(receiver);
      } catch (NoSuchFieldException ignored) { }
    }
    throw new NoSuchFieldException(name);
  }
}
