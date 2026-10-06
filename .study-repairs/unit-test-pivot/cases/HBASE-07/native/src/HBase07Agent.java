import java.io.EOFException;
import java.io.IOException;
import java.lang.instrument.Instrumentation;
import java.net.ConnectException;
import java.net.SocketTimeoutException;
import java.util.concurrent.atomic.AtomicInteger;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import static net.bytebuddy.matcher.ElementMatchers.*;

/** Independent probes for the original snapshot restore MiniHBaseCluster JUnit. */
public class HBase07Agent {
  public static final ThreadLocal<Boolean> FIRST_RESTORE = new ThreadLocal<Boolean>();
  public static final AtomicInteger MASTER_HITS = new AtomicInteger();
  public static final AtomicInteger EXISTS_HITS = new AtomicInteger();
  public static final AtomicInteger CHECK_HITS = new AtomicInteger();
  public static final AtomicInteger STATE_HITS = new AtomicInteger();

  public static void premain(String args, Instrumentation inst) {
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.client.HBaseAdmin"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Restore.class).on(named("restoreSnapshot").and(takesArguments(3))))
        .visit(Advice.to(Disabled.class).on(named("isTableDisabled").and(takesArguments(1)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.client.MasterCallable"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(SnapshotMasterCall.class).on(named("call").and(takesArguments(1)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.client.ClientServiceCallable"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(MetaGet.class).on(named("doGet"))))
      .installOn(inst);
  }

  public static String faultAt(String door, int hit) {
    for (String step : System.getProperty("hbase07.fault.plan", "").split(",")) {
      String[] fields = step.split(":", 3);
      if (fields.length == 3 && fields[0].equals(door)
          && fields[1].equals(Integer.toString(hit))) return fields[2];
    }
    return "";
  }

  public static IOException exception(String door, int hit, String kind) {
    String message = "HBASE07 injected " + door + " hit=" + hit;
    if (kind.equals("IOException")) return new IOException(message);
    if (kind.equals("SocketTimeoutException")) return new SocketTimeoutException(message);
    if (kind.equals("EOFException")) return new EOFException(message);
    if (kind.equals("ConnectException")) return new ConnectException(message);
    throw new IllegalArgumentException("Unknown fault kind " + kind);
  }

  public static class Restore {
    @Advice.OnMethodEnter
    public static Boolean enter(@Advice.Argument(0) Object snapshot) {
      Boolean prior = FIRST_RESTORE.get();
      if (String.valueOf(snapshot).startsWith("snaptb0-")) {
        FIRST_RESTORE.set(Boolean.TRUE);
        System.err.println("HBASE07 TARGET_ENTER snapshot=" + snapshot + " thread="
          + Thread.currentThread().getName());
      }
      return prior;
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter Boolean prior, @Advice.Argument(0) Object snapshot,
        @Advice.Thrown Throwable error) {
      if (!String.valueOf(snapshot).startsWith("snaptb0-")) return;
      System.err.println("HBASE07 TARGET_EXIT exception="
        + (error == null ? "none" : error.getClass().getName() + ":" + error.getMessage())
        + " thread=" + Thread.currentThread().getName());
      if (prior == null) FIRST_RESTORE.remove(); else FIRST_RESTORE.set(prior);
    }
  }

  public static class Disabled {
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Argument(0) Object table, @Advice.Return boolean disabled,
        @Advice.Thrown Throwable error) {
      if (!Boolean.TRUE.equals(FIRST_RESTORE.get())) return;
      System.err.println("HBASE07 GUARD_TABLE_DISABLED table=" + table + " value=" + disabled
        + " exception=" + (error == null ? "none" : error.getClass().getName())
        + " thread=" + Thread.currentThread().getName());
    }
  }

  public static class SnapshotMasterCall {
    @Advice.OnMethodEnter
    public static void enter() throws IOException {
      if (!Boolean.TRUE.equals(FIRST_RESTORE.get())) return;
      boolean snapshots = false;
      for (StackTraceElement f : Thread.currentThread().getStackTrace()) {
        if (f.getClassName().equals("org.apache.hadoop.hbase.client.HBaseAdmin")
            && f.getMethodName().equals("listSnapshots")) snapshots = true;
      }
      if (!snapshots) return;
      int hit = MASTER_HITS.incrementAndGet();
      String chosen = faultAt("MASTER", hit);
      System.err.println("HBASE07 IO door=MASTER hit=" + hit + " matched=" + !chosen.isEmpty()
        + " applied=" + !chosen.isEmpty() + " fault=" + chosen
        + " thread=" + Thread.currentThread().getName());
      if (!chosen.isEmpty()) throw exception("MASTER", hit, chosen);
    }
  }

  public static class MetaGet {
    @Advice.OnMethodEnter
    public static void enter() throws org.apache.hbase.thirdparty.com.google.protobuf.ServiceException {
      if (!Boolean.TRUE.equals(FIRST_RESTORE.get())) return;
      boolean exists = false;
      boolean check = false;
      boolean state = false;
      for (StackTraceElement f : Thread.currentThread().getStackTrace()) {
        if (f.getClassName().equals("org.apache.hadoop.hbase.client.HBaseAdmin")) {
          if (f.getMethodName().equals("tableExists")) exists = true;
          if (f.getMethodName().equals("checkTableExists")) check = true;
        }
        if (f.getClassName().equals("org.apache.hadoop.hbase.client.ConnectionImplementation")
            && f.getMethodName().equals("isTableDisabled")) state = true;
      }
      String door = state ? "STATE" : check ? "CHECK" : exists ? "EXISTS" : "";
      if (door.isEmpty()) return;
      AtomicInteger counter = state ? STATE_HITS : check ? CHECK_HITS : EXISTS_HITS;
      int hit = counter.incrementAndGet();
      String chosen = faultAt(door, hit);
      System.err.println("HBASE07 IO door=" + door + " hit=" + hit
        + " matched=" + !chosen.isEmpty() + " applied=" + !chosen.isEmpty()
        + " fault=" + chosen + " thread=" + Thread.currentThread().getName());
      if (!chosen.isEmpty()) {
        throw new org.apache.hbase.thirdparty.com.google.protobuf.ServiceException(
          exception(door, hit, chosen));
      }
    }
  }
}
