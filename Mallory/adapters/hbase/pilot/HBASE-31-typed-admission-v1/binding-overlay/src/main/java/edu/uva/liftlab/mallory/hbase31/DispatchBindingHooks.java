package edu.uva.liftlab.mallory.hbase31;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.lang.reflect.Field;

/** The exact remote call belongs to its enclosing dispatcher's registered master. */
public final class DispatchBindingHooks {
  private DispatchBindingHooks() { }

  public static Probe.NodeScope enterSendRequest(Object remoteCall) {
    Object master = null;
    try {
      Object dispatcher = field(remoteCall, "this$0");
      master = field(dispatcher, "master");
    } catch (ReflectiveOperationException | RuntimeException ignored) {
      // Missing ownership evidence leaves this worker unattributed.
    }
    Probe.NodeScope scope = Probe.withRegisteredNode(master);
    if (Probe.currentNode().matches("master[0-9]+")) return scope;
    scope.close();
    return Probe.withNode("unknown", 0);
  }

  private static Object field(Object receiver, String name) throws ReflectiveOperationException {
    if (receiver == null) return null;
    for (Class<?> type = receiver.getClass(); type != null; type = type.getSuperclass()) {
      try {
        Field value = type.getDeclaredField(name);
        value.setAccessible(true);
        return value.get(receiver);
      } catch (NoSuchFieldException ignored) { }
    }
    throw new NoSuchFieldException(name);
  }
}
