import java.io.EOFException;
import java.io.IOException;
import java.lang.instrument.Instrumentation;
import java.net.ConnectException;
import java.net.SocketTimeoutException;
import java.util.concurrent.atomic.AtomicInteger;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import static net.bytebuddy.matcher.ElementMatchers.*;

/** confirmClosed entry/exit and request-scoped RPC probes for the original RS crash JUnit. */
public class HBase16Agent {
  public static final ThreadLocal<Boolean> ACTIVE = new ThreadLocal<Boolean>();
  public static final ThreadLocal<String> REGION = new ThreadLocal<String>();
  public static final ThreadLocal<Long> PROC = new ThreadLocal<Long>();
  public static final AtomicInteger CLOSE_HITS = new AtomicInteger();
  public static final ThreadLocal<Boolean> MOVE_ACTIVE = new ThreadLocal<Boolean>();
  public static final ThreadLocal<String> MOVE_REGION = new ThreadLocal<String>();
  public static final AtomicInteger MOVE_HITS = new AtomicInteger();

  public static void premain(String args, Instrumentation inst) {
    new AgentBuilder.Default()
      .with(AgentBuilder.RedefinitionStrategy.RETRANSFORMATION)
      .type(named("org.apache.hadoop.hbase.master.assignment.RegionStateNode"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(StateCheck.class).on(named("isInState").and(takesArguments(1)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.master.assignment.CloseRegionProcedure"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(CloseChild.class).on(named("newRemoteOperation")
          .and(takesArguments(1)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.master.assignment.TransitRegionStateProcedure"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Confirm.class).on(named("confirmClosed").and(takesArguments(2)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.master.procedure.RSProcedureDispatcher$ExecuteProceduresRemoteCall"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(CloseRpc.class).on(named("sendRequest").and(takesArguments(2)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .with(AgentBuilder.RedefinitionStrategy.RETRANSFORMATION)
      .type(named("org.apache.hadoop.hbase.client.HBaseAdmin"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Move.class).on(named("move").and(takesArguments(2)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .with(AgentBuilder.RedefinitionStrategy.RETRANSFORMATION)
      .type(named("org.apache.hadoop.hbase.client.MasterCallable"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(MoveMasterRpc.class).on(named("call").and(takesArguments(1)))))
      .installOn(inst);
  }

  public static String planned(int hit) {
    for (String step : System.getProperty("hbase16.fault.plan", "").split(",")) {
      String[] fields = step.split(":", 3);
      if (fields.length == 3 && fields[0].equals("CLOSE_RPC")
          && fields[1].equals(Integer.toString(hit))) return fields[2];
    }
    return "";
  }

  public static IOException failure(int hit, String kind) {
    String message = "HBASE16 injected CLOSE_RPC hit=" + hit;
    if (kind.equals("IOException")) return new IOException(message);
    if (kind.equals("SocketTimeoutException")) return new SocketTimeoutException(message);
    if (kind.equals("EOFException")) return new EOFException(message);
    if (kind.equals("ConnectException")) return new ConnectException(message);
    throw new IllegalArgumentException("Unknown fault kind " + kind);
  }

  public static String movePlanned(int hit) {
    for (String step : System.getProperty("hbase16.fault.plan", "").split(",")) {
      String[] fields = step.split(":", 3);
      if (fields.length == 3 && fields[0].equals("MOVE_MASTER_RPC")
          && fields[1].equals(Integer.toString(hit))) return fields[2];
    }
    return "";
  }

  public static IOException moveFailure(int hit, String kind) {
    String message = "HBASE16 injected MOVE_MASTER_RPC hit=" + hit;
    if (kind.equals("IOException")) return new IOException(message);
    if (kind.equals("SocketTimeoutException")) return new SocketTimeoutException(message);
    if (kind.equals("EOFException")) return new EOFException(message);
    if (kind.equals("ConnectException")) return new ConnectException(message);
    throw new IllegalArgumentException("Unknown fault kind " + kind);
  }

  public static class Move {
    @Advice.OnMethodEnter
    public static boolean enter(@Advice.Argument(0) byte[] encoded) {
      boolean fromTestMove = false;
      for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
        if (frame.getClassName().equals(
            "org.apache.hadoop.hbase.master.assignment.TestCloseRegionWhileRSCrash")
            && frame.getMethodName().startsWith("lambda$testRetryBackoff")) {
          fromTestMove = true;
        }
      }
      if (!fromTestMove) return false;
      String region = new String(encoded, java.nio.charset.StandardCharsets.UTF_8);
      MOVE_ACTIVE.set(Boolean.TRUE);
      MOVE_REGION.set(region);
      System.err.println("HBASE16 MOVE_ENTER encoded=" + region
        + " thread=" + Thread.currentThread().getName());
      return true;
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter boolean selected, @Advice.Thrown Throwable error) {
      if (!selected) return;
      System.err.println("HBASE16 MOVE_EXIT encoded=" + MOVE_REGION.get() + " exception="
        + (error == null ? "none" : error.getClass().getName())
        + " thread=" + Thread.currentThread().getName());
      MOVE_ACTIVE.remove();
      MOVE_REGION.remove();
    }
  }

  public static class MoveMasterRpc {
    @Advice.OnMethodEnter
    public static void enter() throws IOException {
      if (!Boolean.TRUE.equals(MOVE_ACTIVE.get())) return;
      int hit = MOVE_HITS.incrementAndGet();
      String kind = movePlanned(hit);
      System.err.println("HBASE16 IO door=MOVE_MASTER_RPC hit=" + hit
        + " encoded=" + MOVE_REGION.get() + " matched=" + !kind.isEmpty()
        + " applied=" + !kind.isEmpty() + " fault=" + kind
        + " thread=" + Thread.currentThread().getName());
      if (!kind.isEmpty()) throw moveFailure(hit, kind);
    }
  }

  public static class Confirm {
    @Advice.OnMethodEnter
    public static Boolean enter(@Advice.This Object proc,
        @Advice.Argument(1) org.apache.hadoop.hbase.master.assignment.RegionStateNode node) {
      Boolean prior = ACTIVE.get();
      String region = node.getRegionInfo().getRegionNameAsString();
      if (region.startsWith("Backoff,")) {
        ACTIVE.set(Boolean.TRUE);
        REGION.set(region);
        PROC.set(((org.apache.hadoop.hbase.procedure2.Procedure<?>) proc).getProcId());
        System.err.println("HBASE16 TARGET_ENTER proc=" + PROC.get() + " region=" + region
          + " encoded=" + node.getRegionInfo().getEncodedName()
          + " thread=" + Thread.currentThread().getName());
      }
      return prior;
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter Boolean prior, @Advice.Return Object flow,
        @Advice.Thrown Throwable error) {
      if (!Boolean.TRUE.equals(ACTIVE.get())) return;
      System.err.println("HBASE16 TARGET_EXIT proc=" + PROC.get() + " region=" + REGION.get()
        + " flow=" + flow + " exception="
        + (error == null ? "none" : error.getClass().getName() + ":" + error.getMessage())
        + " thread=" + Thread.currentThread().getName());
      if (prior == null) ACTIVE.remove(); else ACTIVE.set(prior);
      REGION.remove();
      PROC.remove();
    }
  }

  public static class CloseChild {
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.This Object close, @Advice.Thrown Throwable error) {
      if (error != null) return;
      org.apache.hadoop.hbase.procedure2.Procedure<?> proc =
        (org.apache.hadoop.hbase.procedure2.Procedure<?>) close;
      System.err.println("HBASE16 CLOSE_CHILD child=" + proc.getProcId()
        + " parent=" + proc.getParentProcId()
        + " thread=" + Thread.currentThread().getName());
    }
  }

  public static class StateCheck {
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Argument(0) org.apache.hadoop.hbase.master.RegionState.State[] states,
        @Advice.Return boolean result, @Advice.Thrown Throwable error) {
      if (!Boolean.TRUE.equals(ACTIVE.get()) || states.length != 1) return;
      String state = states[0].name();
      if (!state.equals("CLOSED") && !state.equals("CLOSING")) return;
      System.err.println("HBASE16 GUARD proc=" + PROC.get() + " region=" + REGION.get()
        + " state=" + state + " value=" + result + " exception="
        + (error == null ? "none" : error.getClass().getName())
        + " thread=" + Thread.currentThread().getName());
    }
  }

  public static class CloseRpc {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(1)
        org.apache.hadoop.hbase.shaded.protobuf.generated.AdminProtos.ExecuteProceduresRequest request)
        throws IOException {
      for (org.apache.hadoop.hbase.shaded.protobuf.generated.AdminProtos.CloseRegionRequest close
          : request.getCloseRegionList()) {
        String region = close.getRegion().getValue().toStringUtf8();
        if (!region.startsWith("Backoff,")) continue;
        int hit = CLOSE_HITS.incrementAndGet();
        String kind = planned(hit);
        System.err.println("HBASE16 IO door=CLOSE_RPC hit=" + hit + " child="
          + close.getCloseProcId() + " region=" + region
          + " matched=" + !kind.isEmpty() + " applied=" + !kind.isEmpty()
          + " fault=" + kind + " thread=" + Thread.currentThread().getName());
        if (!kind.isEmpty()) throw failure(hit, kind);
      }
    }
  }
}
