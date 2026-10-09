import java.lang.instrument.Instrumentation;
import java.io.EOFException;
import java.io.IOException;
import java.net.ConnectException;
import java.net.SocketTimeoutException;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicBoolean;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import static net.bytebuddy.matcher.ElementMatchers.*;

/** Case-local probe for the original cluster JUnit's confirmOpened calls. */
public class HBase18Agent {
  public static final ThreadLocal<String> ACTIVE_REGION = new ThreadLocal<String>();
  public static final ThreadLocal<Long> ACTIVE_PROC = new ThreadLocal<Long>();
  public static final AtomicInteger OPEN_HITS = new AtomicInteger();
  public static final AtomicBoolean TEST_ACTIVE = new AtomicBoolean();

  public static void premain(String args, Instrumentation inst) {
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.master.assignment.TestExceptionInAssignRegion"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(TestScope.class).on(named("testExceptionInAssignRegion")
          .and(takesArguments(0)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.master.assignment.TransitRegionStateProcedure"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(ConfirmOpened.class)
          .on(named("confirmOpened").and(takesArguments(2)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .with(AgentBuilder.RedefinitionStrategy.RETRANSFORMATION)
      .type(named("org.apache.hadoop.hbase.master.assignment.AssignmentManager"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(ImmediateMax.class)
          .on(named("getAssignRetryImmediatelyMaxAttempts").and(takesArguments(0)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.master.procedure.RSProcedureDispatcher$ExecuteProceduresRemoteCall"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(OpenRpc.class).on(named("sendRequest").and(takesArguments(2)))))
      .installOn(inst);
  }

  public static String planned(int hit) {
    for (String item : System.getProperty("hbase18.fault.plan", "").split(",")) {
      String[] fields = item.split(":", 3);
      if (fields.length == 3 && fields[0].equals("OPEN_RPC")
          && fields[1].equals(Integer.toString(hit))) return fields[2];
    }
    return "";
  }

  public static IOException failure(int hit, String kind) {
    String message = "HBASE18 injected OPEN_RPC hit=" + hit;
    if (kind.equals("IOException")) return new IOException(message);
    if (kind.equals("SocketTimeoutException")) return new SocketTimeoutException(message);
    if (kind.equals("EOFException")) return new EOFException(message);
    if (kind.equals("ConnectException")) return new ConnectException(message);
    if (kind.equals("DoNotRetryIOException"))
      return new org.apache.hadoop.hbase.DoNotRetryIOException(message);
    throw new IllegalArgumentException("Unknown fault kind " + kind);
  }

  public static class ConfirmOpened {
    @Advice.OnMethodEnter
    public static boolean enter(@Advice.This Object procedure,
        @Advice.Argument(1) org.apache.hadoop.hbase.master.assignment.RegionStateNode node) {
      String table = node.getRegionInfo().getTable().getNameAsString();
      if (!table.equals(System.getProperty("hbase18.target.table",
          "testRecoveryAndDoubleExecutionUnassignAndAssign"))) return false;
      long procId = ((org.apache.hadoop.hbase.procedure2.Procedure<?>) procedure).getProcId();
      ACTIVE_REGION.set(node.getRegionInfo().getEncodedName());
      ACTIVE_PROC.set(procId);
      System.err.println("HBASE18 TARGET_ENTER proc=" + procId
        + " region=" + node.getRegionInfo().getEncodedName()
        + " regionId=" + node.getRegionInfo().getRegionId()
        + " state=" + node.getState()
        + " thread=" + Thread.currentThread().getName());
      return true;
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter boolean selected, @Advice.Return Object flow,
        @Advice.Thrown Throwable error) {
      if (!selected) return;
      System.err.println("HBASE18 TARGET_EXIT flow=" + flow + " exception="
        + (error == null ? "none" : error.getClass().getName() + ":" + error.getMessage())
        + " proc=" + ACTIVE_PROC.get() + " region=" + ACTIVE_REGION.get()
        + " thread=" + Thread.currentThread().getName());
      ACTIVE_REGION.remove();
      ACTIVE_PROC.remove();
    }
  }

  public static class TestScope {
    @Advice.OnMethodEnter
    public static void enter() {
      TEST_ACTIVE.set(true);
      System.err.println("HBASE18 TEST_ENTER method=testExceptionInAssignRegion");
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Thrown Throwable error) {
      System.err.println("HBASE18 TEST_EXIT exception="
        + (error == null ? "none" : error.getClass().getName()));
      TEST_ACTIVE.set(false);
    }
  }

  public static class ImmediateMax {
    @Advice.OnMethodExit
    public static void exit(@Advice.Return int max) {
      if (ACTIVE_REGION.get() == null) return;
      System.err.println("HBASE18 GUARD_MAX proc=" + ACTIVE_PROC.get()
        + " region=" + ACTIVE_REGION.get() + " max=" + max
        + " thread=" + Thread.currentThread().getName());
    }
  }

  public static class OpenRpc {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(1)
        org.apache.hadoop.hbase.shaded.protobuf.generated.AdminProtos.ExecuteProceduresRequest request)
        throws IOException {
      if (!TEST_ACTIVE.get()) return;
      for (org.apache.hadoop.hbase.shaded.protobuf.generated.AdminProtos.OpenRegionRequest open
          : request.getOpenRegionList()) {
        for (org.apache.hadoop.hbase.shaded.protobuf.generated.AdminProtos.OpenRegionRequest.RegionOpenInfo info
            : open.getOpenInfoList()) {
          String table = info.getRegion().getTableName().getQualifier().toStringUtf8();
          if (!table.equals(System.getProperty("hbase18.target.table",
              "testRecoveryAndDoubleExecutionUnassignAndAssign"))) continue;
          long regionId = info.getRegion().getRegionId();
          int hit = OPEN_HITS.incrementAndGet();
          String kind = planned(hit);
          System.err.println("HBASE18 IO door=OPEN_RPC hit=" + hit + " table=" + table
            + " regionId=" + regionId + " openProcId=" + info.getOpenProcId()
            + " matched=" + !kind.isEmpty()
            + " applied=" + !kind.isEmpty() + " fault=" + kind
            + " thread=" + Thread.currentThread().getName());
          if (!kind.isEmpty()) throw failure(hit, kind);
        }
      }
    }
  }
}
