import java.io.IOException;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;

/** A bytecode/JSON smoke. It does not start a Hadoop service or JUnit. */
public final class OfflineProbeSmoke {
  public static void main(String[] args) throws Exception {
    Class.forName("org.apache.hadoop.hdfs.server.datanode.BPOfferService", false,
        OfflineProbeSmoke.class.getClassLoader());
    Class<?> contextClass = Class.forName("RecoveryProbe$Context");
    Constructor<?> constructor = contextClass.getDeclaredConstructor();
    constructor.setAccessible(true);
    Object context = constructor.newInstance();
    set(contextClass, context, "source", "dn1");
    set(contextClass, context, "episode", 1);
    set(contextClass, context, "bpid", "BP-a");
    set(contextClass, context, "blockId", 42L);
    set(contextClass, context, "recoveryId", 1002L);
    set(contextClass, context, "attempt", 1);
    set(contextClass, context, "root", "dn1/block:42/attempt:1");
    set(contextClass, context, "commandToken", "direct:1/dn1/block:42/attempt:1");
    Field current = RecoveryProbe.class.getDeclaredField("CURRENT");
    current.setAccessible(true);
    @SuppressWarnings("unchecked")
    ThreadLocal<Object> local = (ThreadLocal<Object>) current.get(null);
    local.set(context);
    RecoveryProbe.targetCheck(29, "BP-a", new Object(), null);
    RecoveryProbe.targetThrow(29, new IOException("synthetic target JSON"));
    Method io = RecoveryProbe.class.getDeclaredMethod("io", String.class, String.class,
        boolean.class, String.class);
    io.setAccessible(true);
    io.invoke(null, "FAULT:HADOOP_IPC:REQUEST", "synthetic-ipc", true,
        "initReplicaRecovery");
  }

  private static void set(Class<?> type, Object object, String field, Object value)
      throws Exception {
    Field handle = type.getDeclaredField(field);
    handle.setAccessible(true);
    handle.set(object, value);
  }
}
