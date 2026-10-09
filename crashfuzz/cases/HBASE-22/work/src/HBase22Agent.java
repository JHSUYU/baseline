import java.lang.instrument.Instrumentation;
import java.util.HashMap;
import java.util.Map;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import static net.bytebuddy.matcher.ElementMatchers.*;

/** Case-local probes. All I/O selectors come from the preceding run's observed events. */
public final class HBase22Agent {
  private static final Map<String, Integer> hits = new HashMap<>();
  public static final ThreadLocal<String> targetTable = new ThreadLocal<>();
  public static final ThreadLocal<Integer> targetRegions = new ThreadLocal<>();
  public static final ThreadLocal<Integer> targetGuardHits = new ThreadLocal<>();
  public static final ThreadLocal<Long> targetCall = new ThreadLocal<>();
  public static final java.util.concurrent.atomic.AtomicLong targetCallIds =
      new java.util.concurrent.atomic.AtomicLong();
  private static long eventSequence;
  private static int nextFault;
  private static final String[] faults = System.getProperty("hbase22.fault.plan", "").split(";");

  public static void premain(String args, Instrumentation inst) {
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.namespace.NamespaceStateManager"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Target.class).on(named("checkAndUpdateNamespaceTableCount").and(takesArguments(2)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.master.TableNamespaceManager"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(RegionGuard.class).on(named("getMaxRegions").and(takesArguments(1)))))
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
        .visit(Advice.to(ZkChildren.class).on(named("getChildDataAndWatchForNewChildren").and(takesArguments(2))))
        .visit(Advice.to(ZkGetData.class).on(named("getDataAndWatch").and(takesArguments(2)))))
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
    System.err.println("HBASE22 IO seq=" + seq + " selector=" + selector);
    if (nextFault >= faults.length || faults[nextFault].isEmpty()) return;
    String[] step = faults[nextFault].split("~", 5);
    if (step.length != 5 || !selector.equals(step[0] + "~" + step[1] + "~" + step[2] + "~" + step[3])) return;
    nextFault++;
    String kind = step[4];
    System.err.println("HBASE22 FAULT_MATCHED seq=" + seq + " step=" + nextFault + " selector=" + selector + " kind=" + kind);
    org.apache.zookeeper.KeeperException.Code code;
    if (kind.equals("CONNECTIONLOSS")) code = org.apache.zookeeper.KeeperException.Code.CONNECTIONLOSS;
    else if (kind.equals("OPERATIONTIMEOUT")) code = org.apache.zookeeper.KeeperException.Code.OPERATIONTIMEOUT;
    else if (kind.equals("SYSTEMERROR")) code = org.apache.zookeeper.KeeperException.Code.SYSTEMERROR;
    else throw new IllegalArgumentException("Unsupported fault kind: " + kind);
    System.err.println("HBASE22 FAULT_APPLIED seq=" + seq + " step=" + nextFault + " selector=" + selector + " kind=" + kind);
    throw org.apache.zookeeper.KeeperException.create(code, path);
  }

  public static final class Target {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(0) org.apache.hadoop.hbase.TableName table,
                             @Advice.Argument(1) int numRegions) {
      targetTable.set(table.getNameAsString());
      targetRegions.set(numRegions);
      targetGuardHits.set(0);
      targetCall.set(targetCallIds.incrementAndGet());
      System.err.println("HBASE22 TARGET_ENTER call=" + targetCall.get()
          + " table=" + targetTable.get()
          + " regions=" + numRegions);
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Argument(0) org.apache.hadoop.hbase.TableName table,
                            @Advice.Argument(1) int numRegions,
                            @Advice.Thrown Throwable thrown) {
      String message = thrown == null ? "" : String.valueOf(thrown.getMessage());
      String outcome = thrown == null ? "normal"
          : message.contains(" is not allowed to have ") ? "region_quota"
          : message.contains(" cannot be created as it would exceed maximum number of tables")
              ? "table_quota" : "other_exception";
      System.err.println("HBASE22 TARGET_EXIT call=" + targetCall.get()
          + " table=" + table.getNameAsString()
          + " regions=" + numRegions + " exception="
          + (thrown == null ? "none" : thrown.getClass().getName())
          + " outcome=" + outcome + " guard_hits=" + targetGuardHits.get());
      targetTable.remove();
      targetRegions.remove();
      targetGuardHits.remove();
      targetCall.remove();
    }
  }

  public static final class RegionGuard {
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Return long max, @Advice.Thrown Throwable thrown) {
      if (targetTable.get() != null && thrown == null) {
        targetGuardHits.set(targetGuardHits.get() + 1);
        System.err.println("HBASE22 REGION_GUARD call=" + targetCall.get()
            + " table=" + targetTable.get()
            + " regions=" + targetRegions.get() + " max=" + max);
      }
    }
  }

  public static final class CacheGet {
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Argument(0) String name, @Advice.Return Object result) {
      System.err.println("HBASE22 CACHE_GET name=" + name + " found=" + (result != null));
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
  public static final class ZkGetData {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(1) String path) throws org.apache.zookeeper.KeeperException {
      io("ZK_GET_DATA", path);
    }
  }
}
