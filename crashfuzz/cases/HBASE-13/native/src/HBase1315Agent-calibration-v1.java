import java.io.EOFException;
import java.io.IOException;
import java.lang.instrument.Instrumentation;
import java.net.ConnectException;
import java.net.SocketTimeoutException;
import java.util.concurrent.atomic.AtomicInteger;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import static net.bytebuddy.matcher.ElementMatchers.*;

/** Shared case-local probes for three checks in one original merge procedure JUnit. */
public class HBase1315Agent {
  public static final ThreadLocal<Boolean> ACTIVE = new ThreadLocal<Boolean>();
  public static final ThreadLocal<String> REGION = new ThreadLocal<String>();
  public static final AtomicInteger META_HITS = new AtomicInteger();

  public static void premain(String args, Instrumentation inst) {
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.master.assignment.MergeTableRegionsProcedure"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Prepare.class).on(named("prepareMergeRegion").and(takesArguments(1)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.MetaTableAccessor"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(MergeMeta.class).on(named("hasMergeRegions").and(takesArguments(2)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.master.assignment.RegionStates"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(RegionLookup.class).on(named("getRegionState")
          .and(takesArgument(0, String.class)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.master.RegionState"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Opened.class).on(named("isOpened").and(takesArguments(0)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.client.ClientServiceCallable"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(MetaRpc.class).on(named("doGet"))))
      .installOn(inst);
  }

  public static String planned(String door, int hit) {
    for (String step : System.getProperty("hbase1315.fault.plan", "").split(",")) {
      String[] fields = step.split(":", 3);
      if (fields.length == 3 && fields[0].equals(door)
          && fields[1].equals(Integer.toString(hit))) return fields[2];
    }
    return "";
  }

  public static IOException failure(String door, int hit, String kind) {
    String message = "HBASE1315 injected " + door + " hit=" + hit;
    if (kind.equals("IOException")) return new IOException(message);
    if (kind.equals("SocketTimeoutException")) return new SocketTimeoutException(message);
    if (kind.equals("EOFException")) return new EOFException(message);
    if (kind.equals("ConnectException")) return new ConnectException(message);
    throw new IllegalArgumentException("Unknown fault kind " + kind);
  }

  public static class Prepare {
    @Advice.OnMethodEnter
    public static void enter() {
      ACTIVE.set(Boolean.TRUE);
      System.err.println("HBASE1315 PREPARE_ENTER thread=" + Thread.currentThread().getName());
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Return boolean result, @Advice.Thrown Throwable error) {
      System.err.println("HBASE1315 PREPARE_EXIT result=" + result + " exception="
        + (error == null ? "none" : error.getClass().getName() + ":" + error.getMessage())
        + " thread=" + Thread.currentThread().getName());
      REGION.remove();
      ACTIVE.remove();
    }
  }

  public static class MergeMeta {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(1) org.apache.hadoop.hbase.client.RegionInfo region) {
      if (!Boolean.TRUE.equals(ACTIVE.get())) return;
      REGION.set(region.getEncodedName());
      System.err.println("HBASE1315 META_ENTER region=" + REGION.get() + " thread="
        + Thread.currentThread().getName());
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Return boolean hasMerge,
        @Advice.Thrown Throwable error) {
      if (!Boolean.TRUE.equals(ACTIVE.get())) return;
      System.err.println("HBASE1315 CHECK13 region=" + REGION.get() + " value=" + hasMerge
        + " exception=" + (error == null ? "none" : error.getClass().getName())
        + " thread=" + Thread.currentThread().getName());
    }
  }

  public static class RegionLookup {
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Return Object state, @Advice.Thrown Throwable error) {
      if (!Boolean.TRUE.equals(ACTIVE.get())) return;
      System.err.println("HBASE1315 CHECK14 region=" + REGION.get() + " null=" + (state == null)
        + " exception=" + (error == null ? "none" : error.getClass().getName())
        + " thread=" + Thread.currentThread().getName());
    }
  }

  public static class Opened {
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Return boolean opened, @Advice.Thrown Throwable error) {
      if (!Boolean.TRUE.equals(ACTIVE.get())) return;
      System.err.println("HBASE1315 CHECK15 region=" + REGION.get() + " value=" + opened
        + " exception=" + (error == null ? "none" : error.getClass().getName())
        + " thread=" + Thread.currentThread().getName());
    }
  }

  public static class MetaRpc {
    @Advice.OnMethodEnter
    public static void enter() throws org.apache.hbase.thirdparty.com.google.protobuf.ServiceException {
      if (!Boolean.TRUE.equals(ACTIVE.get())) return;
      boolean mergeRead = false;
      for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
        if (frame.getClassName().equals("org.apache.hadoop.hbase.MetaTableAccessor")
            && frame.getMethodName().equals("hasMergeRegions")) mergeRead = true;
      }
      if (!mergeRead) return;
      int hit = META_HITS.incrementAndGet();
      String kind = planned("META", hit);
      System.err.println("HBASE1315 IO door=META hit=" + hit + " region=" + REGION.get()
        + " matched=" + !kind.isEmpty() + " applied=" + !kind.isEmpty()
        + " fault=" + kind + " thread=" + Thread.currentThread().getName());
      if (!kind.isEmpty()) {
        throw new org.apache.hbase.thirdparty.com.google.protobuf.ServiceException(
          failure("META", hit, kind));
      }
    }
  }
}
