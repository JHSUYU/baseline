import java.lang.instrument.Instrumentation;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import static net.bytebuddy.matcher.ElementMatchers.*;

/** Case-local probes at the real ZooKeeper read and the selected production check. */
public final class HBase37Agent {
  public static final class ReadContext {
    public final String path;
    public final String actor;
    public final String callsite;
    public ReadContext(String path, String actor, String callsite) {
      this.path = path;
      this.actor = actor;
      this.callsite = callsite;
    }
  }

  public static final ThreadLocal<ReadContext> read = new ThreadLocal<>();
  public static final ThreadLocal<Long> target = new ThreadLocal<>();
  public static final ThreadLocal<Boolean> guardRead = new ThreadLocal<>();
  public static final ThreadLocal<Boolean> testBody = new ThreadLocal<>();
  public static final Map<String, Integer> hits = new HashMap<>();
  public static final AtomicLong targetIds = new AtomicLong();
  private static long ioSequence;
  private static int nextFault;
  private static final String[] faults = System.getProperty("hbase37.fault.plan", "").split(";");

  public static void premain(String args, Instrumentation inst) {
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.regionserver.http.TestRSStatusPage"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(TestPhase.class).on(named("testStatusPage").and(takesArguments(0)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.zookeeper.MasterAddressTracker"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Target.class).on(named("getMasterInfoPort")
          .and(takesArguments(1)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.zookeeper.ZKUtil"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(ZKRead.class).on(named("getData").and(takesArguments(2))))
        .visit(Advice.to(WatchExists.class).on(named("watchAndCheckExists")
          .and(takesArguments(2))))
        .visit(Advice.to(CheckExists.class).on(named("checkExists")
          .and(takesArguments(2))))
        .visit(Advice.to(Create.class).on(named("createEphemeralNodeAndWatch")
          .and(takesArguments(3))))
        .visit(Advice.to(Delete.class).on(named("deleteNode")
          .and(takesArguments(2)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.zookeeper.ZooKeeper"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(WireRead.class).on(named("getData").and(takesArguments(3))
          .and(takesArgument(1, named("org.apache.zookeeper.Watcher"))))))
      .installOn(inst);
  }

  public static String actor(org.apache.hadoop.hbase.zookeeper.ZKWatcher watcher) {
    String id = watcher.getRecoverableZooKeeper().getIdentifier();
    if (id.startsWith("master:")) return "master";
    if (id.startsWith("regionserver:")) return "regionserver";
    if (id.startsWith("connection to cluster:")) return "client";
    return "other";
  }

  public static String caller() {
    StackTraceElement[] frames = Thread.currentThread().getStackTrace();
    for (StackTraceElement frame : frames) {
      String c = frame.getClassName();
      if (c.equals("org.apache.hadoop.hbase.zookeeper.MasterAddressTracker")
          || c.equals("org.apache.hadoop.hbase.master.ActiveMasterManager"))
        return frame.getClassName().substring(frame.getClassName().lastIndexOf('.') + 1)
          + "." + frame.getMethodName() + ":" + frame.getLineNumber();
    }
    for (StackTraceElement frame : frames) {
      String c = frame.getClassName();
      if (c.startsWith("org.apache.hadoop.hbase.")
          && !c.equals("org.apache.hadoop.hbase.zookeeper.ZKUtil")
          && !c.equals("org.apache.hadoop.hbase.zookeeper.RecoverableZooKeeper"))
        return c.substring(c.lastIndexOf('.') + 1)
          + "." + frame.getMethodName() + ":" + frame.getLineNumber();
    }
    return "other";
  }

  public static void io(String path) throws org.apache.zookeeper.KeeperException {
    ReadContext ctx = read.get();
    if (ctx == null || !ctx.path.equals(path)) return;
    io("ZK_GET_DATA", path, ctx.actor, ctx.callsite);
  }

  public static void io(String family, String path,
      org.apache.hadoop.hbase.zookeeper.ZKWatcher watcher)
      throws org.apache.zookeeper.KeeperException {
    if (path == null || !path.equals(watcher.getZNodePaths().masterAddressZNode)) return;
    io(family, path, actor(watcher), caller());
  }

  public static synchronized void io(String family, String path, String actor, String callsite)
      throws org.apache.zookeeper.KeeperException {
    String key = family + "~" + actor + "@" + path + "~" + callsite;
    int hit = hits.containsKey(key) ? hits.get(key) + 1 : 1;
    hits.put(key, hit);
    String selector = key + "~" + hit;
    long seq = ++ioSequence;
    System.err.println("HBASE37 IO seq=" + seq + " selector=" + selector);
    if (nextFault >= faults.length || faults[nextFault].isEmpty()) return;
    String[] step = faults[nextFault].split("~", 5);
    if (step.length != 5 || !selector.equals(step[0] + "~" + step[1] + "~"
        + step[2] + "~" + step[3])) return;
    org.apache.zookeeper.KeeperException.Code code;
    if (step[4].equals("NONODE")) code = org.apache.zookeeper.KeeperException.Code.NONODE;
    else if (step[4].equals("CONNECTIONLOSS"))
      code = org.apache.zookeeper.KeeperException.Code.CONNECTIONLOSS;
    else if (step[4].equals("OPERATIONTIMEOUT"))
      code = org.apache.zookeeper.KeeperException.Code.OPERATIONTIMEOUT;
    else throw new IllegalArgumentException("Unsupported fault kind " + step[4]);
    ++nextFault;
    System.err.println("HBASE37 FAULT_APPLIED seq=" + seq + " step=" + nextFault
      + " selector=" + selector + " kind=" + step[4]);
    throw org.apache.zookeeper.KeeperException.create(code, path);
  }

  public static final class TestPhase {
    @Advice.OnMethodEnter
    public static void enter() { testBody.set(Boolean.TRUE); }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit() { testBody.remove(); }
  }

  public static final class Target {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(0) org.apache.hadoop.hbase.zookeeper.ZKWatcher watcher) {
      if (!Boolean.TRUE.equals(testBody.get())) return;
      long call = targetIds.incrementAndGet();
      target.set(call);
      guardRead.set(Boolean.FALSE);
      System.err.println("HBASE37 TARGET_ENTER call=" + call + " actor=" + actor(watcher)
        + " path=" + watcher.getZNodePaths().masterAddressZNode);
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Thrown Throwable thrown) {
      Long call = target.get();
      if (call == null) return;
      boolean exact = thrown instanceof java.io.IOException
        && "Can't get master address from ZooKeeper; znode data == null".equals(thrown.getMessage());
      System.err.println("HBASE37 TARGET_EXIT call=" + call + " guard="
        + Boolean.TRUE.equals(guardRead.get()) + " exact_exception=" + exact
        + " thrown=" + (thrown == null ? "none" : thrown.getClass().getName()));
      target.remove();
      guardRead.remove();
    }
  }

  public static final class ZKRead {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(0) org.apache.hadoop.hbase.zookeeper.ZKWatcher watcher,
        @Advice.Argument(1) String path) {
      if (path != null && path.equals(watcher.getZNodePaths().masterAddressZNode))
        read.set(new ReadContext(path, actor(watcher), caller()));
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Argument(1) String path, @Advice.Return byte[] data,
        @Advice.Thrown Throwable thrown) {
      ReadContext ctx = read.get();
      if (ctx == null || !ctx.path.equals(path)) return;
      Long call = target.get();
      if (call != null && thrown == null) {
        guardRead.set(Boolean.TRUE);
        System.err.println("HBASE37 TARGET_READ call=" + call + " data_null=" + (data == null)
          + " path=" + ctx.path);
      }
      read.remove();
    }
  }

  public static final class WireRead {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(0) String path) throws org.apache.zookeeper.KeeperException {
      io(path);
    }
  }

  public static final class WatchExists {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(0) org.apache.hadoop.hbase.zookeeper.ZKWatcher watcher,
        @Advice.Argument(1) String path) throws org.apache.zookeeper.KeeperException {
      io("ZK_WATCH_EXISTS", path, watcher);
    }
  }

  public static final class CheckExists {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(0) org.apache.hadoop.hbase.zookeeper.ZKWatcher watcher,
        @Advice.Argument(1) String path) throws org.apache.zookeeper.KeeperException {
      io("ZK_CHECK_EXISTS", path, watcher);
    }
  }

  public static final class Create {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(0) org.apache.hadoop.hbase.zookeeper.ZKWatcher watcher,
        @Advice.Argument(1) String path) throws org.apache.zookeeper.KeeperException {
      io("ZK_CREATE", path, watcher);
    }
  }

  public static final class Delete {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(0) org.apache.hadoop.hbase.zookeeper.ZKWatcher watcher,
        @Advice.Argument(1) String path) throws org.apache.zookeeper.KeeperException {
      io("ZK_DELETE", path, watcher);
    }
  }
}
