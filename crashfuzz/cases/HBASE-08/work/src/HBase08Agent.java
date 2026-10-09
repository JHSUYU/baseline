import java.lang.instrument.Instrumentation;
import java.util.HashMap;
import java.util.Map;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import static net.bytebuddy.matcher.ElementMatchers.*;

/** Case-local probes. All I/O selectors come from the preceding run's observed events. */
public final class HBase08Agent {
  private static final Map<String, Integer> hits = new HashMap<>();
  private static long eventSequence;
  private static int nextFault;
  private static final String[] faults = System.getProperty("hbase08.fault.plan", "").split(";");

  public static void premain(String args, Instrumentation inst) {
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.master.ClusterSchemaServiceImpl"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Target.class).on(named("getNamespace").and(takesArguments(1)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.ZKNamespaceManager"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(CacheGet.class).on(named("get").and(takesArguments(1)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.zookeeper.ZKUtil"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(ZkCreate.class).on(named("createWithParents").and(takesArguments(2))))
        .visit(Advice.to(ZkWrite.class).on(named("updateExistingNodeData").and(takesArguments(4))))
        .visit(Advice.to(ZkChildren.class).on(named("getChildDataAndWatchForNewChildren").and(takesArguments(2)))))
      .installOn(inst);
  }

  public static String caller() {
    for (StackTraceElement f : Thread.currentThread().getStackTrace()) {
      if (f.getClassName().equals("org.apache.hadoop.hbase.ZKNamespaceManager"))
        return f.getMethodName() + ":" + f.getLineNumber();
    }
    return null;
  }

  public static synchronized void io(String family, String path)
      throws org.apache.zookeeper.KeeperException {
    String site = caller();
    if (site == null) return;
    String key = family + "~" + path + "~" + site;
    int hit = hits.containsKey(key) ? hits.get(key) + 1 : 1;
    hits.put(key, hit);
    long seq = ++eventSequence;
    String selector = key + "~" + hit;
    System.err.println("HBASE08 IO seq=" + seq + " selector=" + selector);
    if (nextFault >= faults.length || faults[nextFault].isEmpty()) return;
    String[] step = faults[nextFault].split("~", 5);
    if (step.length != 5 || !selector.equals(step[0] + "~" + step[1] + "~" + step[2] + "~" + step[3])) return;
    nextFault++;
    String kind = step[4];
    System.err.println("HBASE08 FAULT_MATCHED seq=" + seq + " step=" + nextFault + " selector=" + selector + " kind=" + kind);
    org.apache.zookeeper.KeeperException.Code code;
    if (kind.equals("CONNECTIONLOSS")) code = org.apache.zookeeper.KeeperException.Code.CONNECTIONLOSS;
    else if (kind.equals("OPERATIONTIMEOUT")) code = org.apache.zookeeper.KeeperException.Code.OPERATIONTIMEOUT;
    else if (kind.equals("SYSTEMERROR")) code = org.apache.zookeeper.KeeperException.Code.SYSTEMERROR;
    else throw new IllegalArgumentException("Unsupported fault kind: " + kind);
    System.err.println("HBASE08 FAULT_APPLIED seq=" + seq + " step=" + nextFault + " selector=" + selector + " kind=" + kind);
    throw org.apache.zookeeper.KeeperException.create(code, path);
  }

  public static final class Target {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(0) String name) {
      System.err.println("HBASE08 TARGET_ENTER name=" + name);
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Argument(0) String name, @Advice.Thrown Throwable thrown) {
      System.err.println("HBASE08 TARGET_EXIT name=" + name + " exception="
          + (thrown == null ? "none" : thrown.getClass().getName()));
    }
  }

  public static final class CacheGet {
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Argument(0) String name, @Advice.Return Object result) {
      System.err.println("HBASE08 CACHE_GET name=" + name + " found=" + (result != null));
    }
  }
  public static final class ZkCreate {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(1) String path) throws org.apache.zookeeper.KeeperException {
      io("ZK_CREATE", path);
    }
  }
  public static final class ZkWrite {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(1) String path) throws org.apache.zookeeper.KeeperException {
      io("ZK_WRITE", path);
    }
  }
  public static final class ZkChildren {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(1) String path) throws org.apache.zookeeper.KeeperException {
      io("ZK_CHILDREN_READ", path);
    }
  }
}
