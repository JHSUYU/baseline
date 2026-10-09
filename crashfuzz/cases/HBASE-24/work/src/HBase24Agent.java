import java.lang.instrument.Instrumentation;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import static net.bytebuddy.matcher.ElementMatchers.*;

/** Runtime-only probes for the original MiniZKCluster JUnit. */
public final class HBase24Agent {
  private static final Map<String, Integer> hits = new HashMap<>();
  private static final Map<org.apache.hadoop.hbase.zookeeper.ZKWatcher, String> members =
      new IdentityHashMap<>();
  public static final AtomicLong targetIds = new AtomicLong();
  public static final ThreadLocal<Long> activeTarget = new ThreadLocal<>();
  private static long ioSequence;
  private static int nextFault;
  private static final String[] faults = System.getProperty("hbase24.fault.plan", "").split(";");

  public static void premain(String args, Instrumentation inst) {
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.procedure.ZKProcedureMemberRpcs"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(RegisterMember.class).on(named("start").and(takesArguments(2))))
        .visit(Advice.to(Target.class).on(named("startNewSubprocedure").and(takesArguments(1)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.shaded.protobuf.ProtobufUtil"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Magic.class).on(named("isPBMagicPrefix").and(takesArguments(1)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.zookeeper.ZKUtil"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Children.class).on(named("listChildrenAndWatchForNewChildren").and(takesArguments(2))))
        .visit(Advice.to(Exists.class).on(named("watchAndCheckExists").and(takesArguments(2))))
        .visit(Advice.to(Data.class).on(named("getData").and(takesArguments(2)))))
      .installOn(inst);
  }

  private static String site() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (frame.getClassName().equals("org.apache.hadoop.hbase.procedure.ZKProcedureMemberRpcs"))
        return frame.getMethodName() + ":" + frame.getLineNumber();
    }
    return null;
  }

  public static synchronized void register(org.apache.hadoop.hbase.zookeeper.ZKWatcher watcher,
      String member) {
    members.put(watcher, member);
  }

  public static synchronized void io(String family, String path,
      org.apache.hadoop.hbase.zookeeper.ZKWatcher watcher)
      throws org.apache.zookeeper.KeeperException {
    String caller = site();
    if (caller == null || path == null ||
        !(path.contains("/testSimple/") || path.contains("/coordination test - 4 cohort members/")))
      return;
    String member = members.get(watcher);
    if (member == null) return;
    String key = family + "~" + member + "@" + path.replace(" ", "%20") + "~" + caller;
    int hit = hits.containsKey(key) ? hits.get(key) + 1 : 1;
    hits.put(key, hit);
    String selector = key + "~" + hit;
    long seq = ++ioSequence;
    System.err.println("HBASE24 IO seq=" + seq + " selector=" + selector);
    if (nextFault >= faults.length || faults[nextFault].isEmpty()) return;
    String[] step = faults[nextFault].split("~", 5);
    if (step.length != 5 || !selector.equals(step[0] + "~" + step[1] + "~" + step[2] + "~" + step[3]))
      return;
    String kind = step[4];
    org.apache.zookeeper.KeeperException.Code code;
    if (kind.equals("CONNECTIONLOSS")) code = org.apache.zookeeper.KeeperException.Code.CONNECTIONLOSS;
    else if (kind.equals("OPERATIONTIMEOUT")) code = org.apache.zookeeper.KeeperException.Code.OPERATIONTIMEOUT;
    else if (kind.equals("SYSTEMERROR")) code = org.apache.zookeeper.KeeperException.Code.SYSTEMERROR;
    else throw new IllegalArgumentException("Unsupported fault kind " + kind);
    ++nextFault;
    System.err.println("HBASE24 FAULT_APPLIED seq=" + seq + " step=" + nextFault
        + " selector=" + selector + " kind=" + kind);
    throw org.apache.zookeeper.KeeperException.create(code, path);
  }

  public static final class RegisterMember {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(0) String member,
        @Advice.FieldValue("zkController") org.apache.hadoop.hbase.procedure.ZKProcedureUtil controller) {
      register(controller.getWatcher(), member);
    }
  }

  public static final class Target {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(0) String path,
        @Advice.FieldValue("memberName") String member) {
      long id = targetIds.incrementAndGet();
      activeTarget.set(id);
      System.err.println("HBASE24 TARGET_ENTER call=" + id + " member=" + member + " path=" + path);
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Thrown Throwable thrown) {
      System.err.println("HBASE24 TARGET_EXIT call=" + activeTarget.get()
          + " thrown=" + (thrown == null ? "none" : thrown.getClass().getName()));
      activeTarget.remove();
    }
  }

  public static final class Magic {
    @Advice.OnMethodExit
    public static void exit(@Advice.Argument(0) byte[] bytes, @Advice.Return boolean valid) {
      Long call = activeTarget.get();
      if (call != null)
        System.err.println("HBASE24 MAGIC_CHECK call=" + call + " valid=" + valid
            + " length=" + (bytes == null ? -1 : bytes.length));
    }
  }

  public static final class Children {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(0) org.apache.hadoop.hbase.zookeeper.ZKWatcher watcher,
        @Advice.Argument(1) String path) throws org.apache.zookeeper.KeeperException {
      io("ZK_CHILDREN", path, watcher);
    }
  }
  public static final class Exists {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(0) org.apache.hadoop.hbase.zookeeper.ZKWatcher watcher,
        @Advice.Argument(1) String path) throws org.apache.zookeeper.KeeperException {
      io("ZK_EXISTS", path, watcher);
    }
  }
  public static final class Data {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(0) org.apache.hadoop.hbase.zookeeper.ZKWatcher watcher,
        @Advice.Argument(1) String path) throws org.apache.zookeeper.KeeperException {
      io("ZK_DATA", path, watcher);
    }
  }
}
