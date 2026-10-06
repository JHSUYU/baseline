import static net.bytebuddy.matcher.ElementMatchers.named;
import static net.bytebuddy.matcher.ElementMatchers.takesArguments;

import java.lang.instrument.Instrumentation;
import java.util.concurrent.atomic.AtomicInteger;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import org.apache.hadoop.hbase.master.RegionState.State;
import org.apache.hadoop.hbase.master.assignment.RegionStateNode;

/** Case-local exact observer for confirmClosed's ABNORMALLY_CLOSED assertion. */
public class HBase17TargetAgent {
  private static final AtomicInteger B5_HITS = new AtomicInteger();
  private static final AtomicInteger CONFIRM_HITS = new AtomicInteger();
  private static final AtomicInteger INSTATE_HITS = new AtomicInteger();
  private static final AtomicInteger ABNORMAL_HITS = new AtomicInteger();

  public static int nextB5() { return B5_HITS.incrementAndGet(); }
  public static int nextConfirm() { return CONFIRM_HITS.incrementAndGet(); }
  public static void hitInState() { INSTATE_HITS.incrementAndGet(); }
  public static void hitAbnormal() { ABNORMAL_HITS.incrementAndGet(); }

  public static boolean calledByConfirmClosed() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (frame.getClassName().equals(
            "org.apache.hadoop.hbase.master.assignment.TransitRegionStateProcedure")
          && frame.getMethodName().equals("confirmClosed")) return true;
    }
    return false;
  }

  public static void premain(String args, Instrumentation inst) {
    Runtime.getRuntime().addShutdownHook(new Thread(() ->
      System.err.println("HBASE17 TOTAL confirmClosed=" + CONFIRM_HITS.get()
        + " exactB5=" + B5_HITS.get()
        + " isInState=" + INSTATE_HITS.get()
        + " abnormalExpected=" + ABNORMAL_HITS.get())));
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.master.assignment.RegionStateNode"))
      .transform((builder, type, loader, module, domain) -> builder.visit(
        Advice.to(IsInState.class).on(named("isInState").and(takesArguments(1)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.master.assignment.TransitRegionStateProcedure"))
      .transform((builder, type, loader, module, domain) -> builder.visit(
        Advice.to(ConfirmClosed.class).on(named("confirmClosed").and(takesArguments(2)))))
      .installOn(inst);
  }

  public static class IsInState {
    @Advice.OnMethodEnter
    public static int enter(@Advice.This RegionStateNode node,
                            @Advice.Argument(0) State[] expected) {
      HBase17TargetAgent.hitInState();
      if (expected == null || expected.length != 1
          || expected[0] != State.ABNORMALLY_CLOSED) return -1;
      HBase17TargetAgent.hitAbnormal();
      if (!HBase17TargetAgent.calledByConfirmClosed()) return -1;
      int ordinal = HBase17TargetAgent.nextB5();
      System.err.println("HBASE17 B5_ENTER ordinal=" + ordinal
        + " table=" + node.getTable().getNameAsString()
        + " region=" + node.getRegionInfo().getEncodedName()
        + " state=" + node.getState());
      return ordinal;
    }

    @Advice.OnMethodExit
    public static void exit(@Advice.Enter int ordinal, @Advice.Return boolean result) {
      if (ordinal < 0) return;
      System.err.println("HBASE17 B5_EXIT ordinal=" + ordinal + " outcome=" + result);
    }
  }

  public static class ConfirmClosed {
    @Advice.OnMethodEnter
    public static int enter(@Advice.Argument(1) RegionStateNode node) {
      int ordinal = HBase17TargetAgent.nextConfirm();
      System.err.println("HBASE17 CONFIRM_ENTER ordinal=" + ordinal
        + " table=" + node.getTable().getNameAsString()
        + " region=" + node.getRegionInfo().getEncodedName()
        + " state=" + node.getState());
      return ordinal;
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter int ordinal, @Advice.Thrown Throwable error) {
      System.err.println("HBASE17 CONFIRM_EXIT ordinal=" + ordinal
        + " exception=" + (error == null ? "none" : error.getClass().getName()));
    }
  }
}
