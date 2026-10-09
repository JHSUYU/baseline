import java.io.EOFException;
import java.io.IOException;
import java.lang.instrument.Instrumentation;
import java.net.ConnectException;
import java.net.SocketTimeoutException;
import java.util.concurrent.atomic.AtomicInteger;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import static net.bytebuddy.matcher.ElementMatchers.*;

/** Independent runtime probes for one original MiniHBaseCluster JUnit. */
public class HBase01Agent {
  public static final ThreadLocal<Integer> IN_LOOKUP = new ThreadLocal<Integer>();
  public static final ThreadLocal<Boolean> IN_RELOCATE = new ThreadLocal<Boolean>();
  public static final AtomicInteger SCAN_HITS = new AtomicInteger();
  public static final AtomicInteger GET_HITS = new AtomicInteger();

  public static void premain(String args, Instrumentation inst) {
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.client.ConnectionImplementation"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Lookup.class).on(named("locateRegionInMeta").and(takesArguments(5))))
        .visit(Advice.to(Relocate.class).on(named("relocateRegion").and(takesArguments(3))))
        .visit(Advice.to(DeadServer.class).on(named("isDeadServer").and(takesArguments(1)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.client.ClientScanner"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(ScanResponse.class).on(named("next").and(takesArguments(0)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.client.ClientServiceCallable"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(MetaGetRpc.class).on(named("doGet"))))
      .installOn(inst);
  }

  public static String faultAt(String door, int hit) {
    String plan = System.getProperty("hbase01.fault.plan", "");
    for (String step : plan.split(",")) {
      String[] fields = step.split(":", 3);
      if (fields.length == 3 && fields[0].equals(door)
          && fields[1].equals(Integer.toString(hit))) return fields[2];
    }
    return "";
  }

  public static IOException exception(String door, int hit, String kind) {
    String message = "HBASE01 injected " + door + " hit=" + hit;
    if (kind.equals("IOException")) return new IOException(message);
    if (kind.equals("SocketTimeoutException")) return new SocketTimeoutException(message);
    if (kind.equals("EOFException")) return new EOFException(message);
    if (kind.equals("ConnectException")) return new ConnectException(message);
    throw new IllegalArgumentException("Unknown fault kind " + kind);
  }

  public static boolean selected(Object table) {
    return String.valueOf(table).startsWith("testMetaLookupThreadPoolCreated");
  }

  public static class Relocate {
    @Advice.OnMethodEnter
    public static Boolean enter(@Advice.Argument(0) Object table) {
      Boolean prior = IN_RELOCATE.get();
      if (selected(table)) IN_RELOCATE.set(Boolean.TRUE);
      return prior;
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter Boolean prior, @Advice.Argument(0) Object table) {
      if (selected(table)) {
        if (prior == null) IN_RELOCATE.remove(); else IN_RELOCATE.set(prior);
      }
    }
  }

  public static class Lookup {
    @Advice.OnMethodEnter
    public static Integer enter(@Advice.Argument(0) Object table) {
      Integer prior = IN_LOOKUP.get();
      if (!selected(table)) return prior;
      IN_LOOKUP.set(prior == null ? 1 : prior + 1);
      System.err.println("HBASE01 TARGET_ENTER table=" + table + " thread="
        + Thread.currentThread().getName());
      return prior;
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter Integer prior, @Advice.Argument(0) Object table,
        @Advice.Thrown Throwable error) {
      if (!selected(table)) return;
      System.err.println("HBASE01 TARGET_EXIT exception="
        + (error == null ? "none" : error.getClass().getName() + ":" + error.getMessage())
        + " thread=" + Thread.currentThread().getName());
      if (prior == null) IN_LOOKUP.remove(); else IN_LOOKUP.set(prior);
    }
  }

  public static class DeadServer {
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Argument(0) Object server, @Advice.Return boolean dead,
        @Advice.Thrown Throwable error) {
      if (IN_LOOKUP.get() == null) return;
      System.err.println("HBASE01 GUARD_DEAD_SERVER server=" + server + " value=" + dead
        + " exception=" + (error == null ? "none" : error.getClass().getName())
        + " thread=" + Thread.currentThread().getName());
    }
  }

  public static class ScanResponse {
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.This Object scanner, @Advice.Thrown(readOnly = false) Throwable error) {
      if (IN_LOOKUP.get() == null
          || !scanner.getClass().getName().equals("org.apache.hadoop.hbase.client.ReversedClientScanner")) return;
      int hit = SCAN_HITS.incrementAndGet();
      String chosen = faultAt("SCAN", hit);
      boolean apply = !chosen.isEmpty() && error == null;
      System.err.println("HBASE01 IO door=SCAN hit=" + hit + " matched=" + !chosen.isEmpty()
        + " applied=" + apply + " fault=" + chosen + " original_exception="
        + (error == null ? "none" : error.getClass().getName())
        + " thread=" + Thread.currentThread().getName());
      if (apply) error = exception("SCAN", hit, chosen);
    }
  }

  public static class MetaGetRpc {
    @Advice.OnMethodEnter
    public static void enter() throws org.apache.hbase.thirdparty.com.google.protobuf.ServiceException {
      boolean inTableState = false;
      boolean inRelocate = false;
      for (StackTraceElement f : Thread.currentThread().getStackTrace()) {
        if (f.getClassName().equals("org.apache.hadoop.hbase.MetaTableAccessor")
            && f.getMethodName().equals("getTableState")) inTableState = true;
        if (f.getClassName().equals("org.apache.hadoop.hbase.client.ConnectionImplementation")
            && f.getMethodName().equals("relocateRegion")) inRelocate = true;
      }
      if (!inTableState || !inRelocate || !Boolean.TRUE.equals(IN_RELOCATE.get())) return;
      int hit = GET_HITS.incrementAndGet();
      String chosen = faultAt("GET", hit);
      System.err.println("HBASE01 IO door=GET hit=" + hit + " matched=" + !chosen.isEmpty()
        + " applied=" + !chosen.isEmpty() + " fault=" + chosen
        + " thread=" + Thread.currentThread().getName());
      if (!chosen.isEmpty()) {
        throw new org.apache.hbase.thirdparty.com.google.protobuf.ServiceException(
          exception("GET", hit, chosen));
      }
    }
  }
}
