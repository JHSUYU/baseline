package edu.uva.liftlab.mallory.hbase.tokenmanager;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.lang.reflect.Field;

/** Bind an HBase token manager to the MiniCluster server that owns its exact ZKWatcher. */
public final class TokenManagerActorHooks {
  private TokenManagerActorHooks() { }

  public static Probe.NodeScope enter(Object manager) {
    Object watcher = null;
    try {
      // AuthenticationTokenSecretManager constructs ZKSecretWatcher with the RPC
      // server's ZKWatcher. ZKSecretWatcher inherits that same object from ZKListener.
      Object listener = field(manager, "zkWatcher");
      watcher = field(listener, "watcher");
    } catch (ReflectiveOperationException | RuntimeException ignored) {
      // An unsupported implementation stays unknown. Never infer a server from a
      // thread name, hostname, timing, or another manager's watcher.
    }
    return Probe.withRegisteredNode(watcher);
  }

  private static Object field(Object receiver, String name) throws ReflectiveOperationException {
    if (receiver == null) throw new NoSuchFieldException(name);
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
