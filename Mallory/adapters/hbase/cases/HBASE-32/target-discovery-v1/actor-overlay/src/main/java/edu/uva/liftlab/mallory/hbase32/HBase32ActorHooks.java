package edu.uva.liftlab.mallory.hbase32;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.lang.reflect.Field;

/** Bind a replica flush handler to its registered owning MiniCluster RegionServer. */
public final class HBase32ActorHooks {
  private HBase32ActorHooks() { }

  public static Probe.NodeScope enter(Object handler) {
    Object server = null;
    if (handler != null) {
      for (Class<?> type = handler.getClass(); type != null; type = type.getSuperclass()) {
        try {
          Field field = type.getDeclaredField("server");
          field.setAccessible(true);
          server = field.get(handler);
          break;
        } catch (NoSuchFieldException ignored) {
          // EventHandler declares this inherited field.
        } catch (ReflectiveOperationException | RuntimeException failure) {
          break;
        }
      }
    }
    // Unknown owners remain unknown and emit NODE_IDENTITY_GAP; never infer an RS from thread name.
    return Probe.withRegisteredNode(server);
  }
}
