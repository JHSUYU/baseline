import static net.bytebuddy.matcher.ElementMatchers.named;
import static net.bytebuddy.matcher.ElementMatchers.takesArguments;

import java.lang.instrument.Instrumentation;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import org.apache.zookeeper.KeeperException;

/** Original-JUnit reachability observer; never injects a fault. */
public class HBase27TargetAgent {
  public static final AtomicInteger WAIT_ENTRIES = new AtomicInteger();
  public static final AtomicInteger GUARD_EVALUATIONS = new AtomicInteger();
  public static final AtomicInteger TARGET_THROWS = new AtomicInteger();
  public static final ThreadLocal<Object> ACTIVE_RS = new ThreadLocal<>();
  public static final Map<String, AtomicInteger> IO_HITS = new ConcurrentHashMap<>();
  public static final String FAULT_SELECTOR = System.getProperty("hbase27.fault.selector", "");

  public static String trackerNode(Object tracker) {
    try { return String.valueOf(tracker.getClass().getMethod("getNode").invoke(tracker)); }
    catch (ReflectiveOperationException e) { return "unknown:" + tracker.getClass().getName(); }
  }

  public static String stopped(Object server) {
    try { return String.valueOf(server.getClass().getMethod("isStopped").invoke(server)); }
    catch (ReflectiveOperationException e) { return "unknown"; }
  }

  public static String caller() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (frame.getClassName().equals("org.apache.hadoop.hbase.zookeeper.ZKNodeTracker"))
        return "ZKNodeTracker." + frame.getMethodName();
    }
    return "OTHER";
  }

  public static String watcherRole(Object watcher) {
    String identity = String.valueOf(watcher);
    if (identity.startsWith("regionserver:")) return "REGIONSERVER";
    if (identity.startsWith("master:")) return "MASTER";
    return "OTHER";
  }

  public static String selector(String role, String path, String caller) {
    String family = "ZK_RESPONSE~" + role + "~" + path + "~" + caller;
    int occurrence = IO_HITS.computeIfAbsent(family, unused -> new AtomicInteger())
      .incrementAndGet();
    return family + "~" + occurrence;
  }

  public static void premain(String args, Instrumentation inst) {
    Runtime.getRuntime().addShutdownHook(new Thread(() -> System.err.println(
      "HBASE27 SUMMARY waitEntries=" + WAIT_ENTRIES.get()
        + " guardEvaluations=" + GUARD_EVALUATIONS.get()
        + " targetThrows=" + TARGET_THROWS.get())));
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.regionserver.HRegionServer"))
      .transform((builder, type, loader, module, domain) -> builder.visit(
        Advice.to(Wait.class).on(named("blockAndCheckIfStopped").and(takesArguments(1)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.zookeeper.ZKNodeTracker"))
      .transform((builder, type, loader, module, domain) -> builder.visit(
        Advice.to(TrackerBlock.class).on(named("blockUntilAvailable")
          .and(takesArguments(2)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.zookeeper.ZKUtil"))
      .transform((builder, type, loader, module, domain) -> builder.visit(
        Advice.to(ZkRead.class).on(named("getDataAndWatch").and(takesArguments(2)))))
      .installOn(inst);
  }

  public static class Wait {
    @Advice.OnMethodEnter
    public static int enter(@Advice.This Object server, @Advice.Argument(0) Object tracker) {
      ACTIVE_RS.set(server);
      int ordinal = WAIT_ENTRIES.incrementAndGet();
      System.err.println("HBASE27 WAIT_ENTER ordinal=" + ordinal + " tracker="
        + trackerNode(tracker) + " stopped=" + stopped(server));
      return ordinal;
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter int ordinal, @Advice.Thrown Throwable error) {
      if (error != null && error.getClass().getName().equals("java.io.IOException")
          && "Received the shutdown message while waiting.".equals(error.getMessage())) {
        TARGET_THROWS.incrementAndGet();
        System.err.println("HBASE27 TARGET_THROW ordinal=" + ordinal
          + " exception=" + error.getClass().getName()
          + " message=" + error.getMessage());
      }
      System.err.println("HBASE27 WAIT_EXIT ordinal=" + ordinal + " exception="
        + (error == null ? "none" : error.getClass().getName()));
      ACTIVE_RS.remove();
    }
  }

  public static class TrackerBlock {
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.This Object tracker, @Advice.Return byte[] data,
        @Advice.Thrown Throwable error) {
      Object server = ACTIVE_RS.get();
      if (server == null || error != null || data != null) return;
      int ordinal = GUARD_EVALUATIONS.incrementAndGet();
      // In HRegionServer source, the stopped guard immediately follows this null return.
      System.err.println("HBASE27 GUARD_EVAL ordinal=" + ordinal + " tracker="
        + trackerNode(tracker) + " stoppedSnapshot=" + stopped(server));
    }
  }

  public static class ZkRead {
    @Advice.OnMethodEnter
    public static ReadPoint enter(@Advice.Argument(0) Object watcher,
        @Advice.Argument(1) String path) {
      if (!path.endsWith("/master") && !path.endsWith("/running")) return null;
      String role = watcherRole(watcher);
      String site = caller();
      return new ReadPoint(selector(role, path, site), path, role, site);
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter ReadPoint point,
        @Advice.Thrown(readOnly = false) Throwable error) {
      if (point == null) return;
      String original = error == null ? "none" : error.getClass().getName();
      System.err.println("HBASE27 IO selector=" + point.selector
        + " originalError=" + original + " thread="
        + Thread.currentThread().getName().replace(' ', '_'));
      if (!point.selector.equals(FAULT_SELECTOR) || error != null) return;
      System.err.println("HBASE27 FAULT_MATCHED selector=" + point.selector
        + " kind=KEEPER_CONNECTIONLOSS");
      error = KeeperException.create(KeeperException.Code.CONNECTIONLOSS, point.path);
      System.err.println("HBASE27 FAULT_APPLIED selector=" + point.selector
        + " kind=KEEPER_CONNECTIONLOSS");
    }
  }

  public static class ReadPoint {
    public final String selector;
    public final String path;
    public final String role;
    public final String site;
    public ReadPoint(String selector, String path, String role, String site) {
      this.selector = selector;
      this.path = path;
      this.role = role;
      this.site = site;
    }
  }
}
