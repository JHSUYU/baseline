import static net.bytebuddy.matcher.ElementMatchers.named;
import static net.bytebuddy.matcher.ElementMatchers.takesArguments;

import java.io.IOException;
import java.lang.instrument.Instrumentation;
import java.net.ConnectException;
import java.net.SocketTimeoutException;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import org.apache.hbase.thirdparty.com.google.protobuf.Descriptors;
import org.apache.hbase.thirdparty.com.google.protobuf.ServiceException;
import org.apache.hadoop.hbase.master.RegionState.State;
import org.apache.hadoop.hbase.client.RegionInfo;
import org.apache.hadoop.hbase.util.Bytes;
import org.apache.hadoop.hbase.shaded.protobuf.generated.AdminProtos;

/** Case-local, graph-free exact target and production I/O identity recorder. */
public class HBase17FuzzAgent {
  public static final AtomicInteger B5 = new AtomicInteger();
  public static final AtomicInteger CONFIRM = new AtomicInteger();
  public static final AtomicInteger APPLIED = new AtomicInteger();
  public static final AtomicLong SEQUENCE = new AtomicLong();
  public static final Map<String, AtomicInteger> HITS = new ConcurrentHashMap<>();
  public static final String[] PLAN = System.getProperty("hbase17.fault.plan", "").split(";");
  public static int nextFault;

  public static void premain(String args, Instrumentation inst) {
    Runtime.getRuntime().addShutdownHook(new Thread(() -> System.err.println(
      "HBASE17 SUMMARY exactB5=" + B5.get() + " confirm=" + CONFIRM.get()
        + " applied=" + APPLIED.get() + " planLength="
        + (PLAN.length == 1 && PLAN[0].isEmpty() ? 0 : PLAN.length))));
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.master.assignment.RegionStateNode"))
      .transform((builder, type, loader, module, domain) -> builder.visit(
        Advice.to(InState.class).on(named("isInState").and(takesArguments(1)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.master.assignment.TransitRegionStateProcedure"))
      .transform((builder, type, loader, module, domain) -> builder.visit(
        Advice.to(ConfirmClosed.class).on(named("confirmClosed").and(takesArguments(2)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.ipc.AbstractRpcClient"))
      .transform((builder, type, loader, module, domain) -> builder.visit(
        Advice.to(Rpc.class).on(named("callBlockingMethod").and(takesArguments(6)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.client.HTable"))
      .transform((builder, type, loader, module, domain) -> builder.visit(
        Advice.to(MetaPut.class).on(named("put").and(takesArguments(1)))))
      .installOn(inst);
  }

  public static boolean calledByConfirmClosed() {
    for (StackTraceElement f : Thread.currentThread().getStackTrace())
      if (f.getClassName().equals(
          "org.apache.hadoop.hbase.master.assignment.TransitRegionStateProcedure")
          && f.getMethodName().equals("confirmClosed")) return true;
    return false;
  }

  public static String state(Object node) {
    try { return String.valueOf(node.getClass().getMethod("getState").invoke(node)); }
    catch (ReflectiveOperationException e) { return "unknown"; }
  }

  public static String role() {
    String name = Thread.currentThread().getName();
    if (name.startsWith("RSProcDispatcher")) return "MASTER_DISPATCH";
    if (name.startsWith("PEWorker")) return "MASTER_PROC";
    if (name.startsWith("RpcServer")) return "SERVER_RPC";
    if (name.equals("main")) return "TEST";
    return "OTHER";
  }

  public static String callsite() {
    for (StackTraceElement f : Thread.currentThread().getStackTrace()) {
      String c = f.getClassName();
      if (c.startsWith("org.apache.hadoop.hbase.util.RSProcDispatcher")
          || c.equals("org.apache.hadoop.hbase.master.assignment.RegionStateStore")
          || c.startsWith("org.apache.hadoop.hbase.master.procedure.RSProcedureDispatcher")
          || c.equals("org.apache.hadoop.hbase.client.HBaseAdmin")
          || c.equals("org.apache.hadoop.hbase.regionserver.RSRpcServices"))
        return c.substring(c.lastIndexOf('.') + 1) + "." + f.getMethodName()
          + ":" + f.getLineNumber();
    }
    return "OTHER";
  }

  public static int ordinal(String family) {
    return HITS.computeIfAbsent(family, unused -> new AtomicInteger()).incrementAndGet();
  }

  public static synchronized String take(String selector, boolean possible) {
    if (!possible || nextFault >= PLAN.length || PLAN[nextFault].isEmpty()) return "";
    String requested = PLAN[nextFault];
    int split = requested.lastIndexOf('~');
    if (split < 0 || !selector.equals(requested.substring(0, split))) return "";
    String kind = requested.substring(split + 1);
    nextFault++;
    System.err.println("HBASE17 FAULT_MATCHED seq=" + SEQUENCE.get()
      + " step=" + nextFault + " selector=" + selector + " kind=" + kind);
    return kind;
  }

  public static void applied(String selector, String kind) {
    APPLIED.incrementAndGet();
    System.err.println("HBASE17 FAULT_APPLIED seq=" + SEQUENCE.get()
      + " step=" + nextFault + " selector=" + selector + " kind=" + kind);
  }

  public static String event(String phase, String resource, String site, String role,
      int occurrence, String originalError, String peer) {
    String family = phase + "~" + resource + "~" + site + "~" + role;
    String selector = family + "~" + occurrence;
    long seq = SEQUENCE.incrementAndGet();
    System.err.println("HBASE17 IO seq=" + seq + " selector=" + selector
      + " originalError=" + originalError + " peer=" + peer);
    return selector;
  }

  public static String operation(Object request) {
    if (!(request instanceof AdminProtos.ExecuteProceduresRequest)) return "CALL";
    AdminProtos.ExecuteProceduresRequest req =
      (AdminProtos.ExecuteProceduresRequest) request;
    if (req.getCloseRegionCount() > 0) {
      try {
        byte[] name = req.getCloseRegion(0).getRegion().getValue().toByteArray();
        byte[][] parts = RegionInfo.parseRegionName(name);
        return "CLOSE_" + Bytes.toStringBinary(parts[0]) + "_"
          + Bytes.toStringBinary(parts[1]);
      } catch (Exception e) { return "CLOSE_REGION"; }
    }
    if (req.getOpenRegionCount() > 0) return "OPEN_REGION";
    if (req.getProcCount() > 0) return "PROCEDURE";
    return "EMPTY";
  }

  public static class InState {
    @Advice.OnMethodEnter
    public static int enter(@Advice.This Object node, @Advice.Argument(0) State[] expected) {
      if (expected == null || expected.length != 1
          || expected[0] != State.ABNORMALLY_CLOSED || !calledByConfirmClosed()) return -1;
      int count = B5.incrementAndGet();
      System.err.println("HBASE17 B5_ENTER ordinal=" + count + " state=" + state(node));
      return count;
    }
    @Advice.OnMethodExit
    public static void exit(@Advice.Enter int count, @Advice.Return boolean result) {
      if (count >= 0)
        System.err.println("HBASE17 B5_EXIT ordinal=" + count + " outcome=" + result);
    }
  }

  public static class ConfirmClosed {
    @Advice.OnMethodEnter
    public static int enter(@Advice.Argument(1) Object node) {
      int count = CONFIRM.incrementAndGet();
      System.err.println("HBASE17 CONFIRM_ENTER ordinal=" + count + " state=" + state(node));
      return count;
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter int count, @Advice.Thrown Throwable error) {
      System.err.println("HBASE17 CONFIRM_EXIT ordinal=" + count + " exception="
        + (error == null ? "none" : error.getClass().getName()));
    }
  }

  public static class RpcPoint {
    public final String method;
    public final String site;
    public final String role;
    public final String peer;
    public final int occurrence;
    public RpcPoint(String method, String site, String role, String peer, int occurrence) {
      this.method = method;
      this.site = site;
      this.role = role;
      this.peer = peer;
      this.occurrence = occurrence;
    }
  }

  public static boolean relevantRpc(String method) {
    return method.contains("ExecuteProcedures")
      || method.contains("ReportRegionStateTransition")
      || method.contains("MoveRegion")
      || method.contains("Mutate")
      || method.contains("Multi");
  }

  public static class Rpc {
    @Advice.OnMethodEnter
    public static RpcPoint enter(@Advice.Argument(0) Descriptors.MethodDescriptor descriptor,
        @Advice.Argument(2) Object request, @Advice.Argument(5) Object destination)
        throws ServiceException {
      String method = descriptor.getFullName();
      if (!relevantRpc(method)) return null;
      method = method + "#" + operation(request);
      String site = callsite();
      String role = role();
      String peer = String.valueOf(destination).replace(' ', '_');
      int occurrence = ordinal("RPC~" + method + "~" + site + "~" + role);
      String selector = event("RPC_REQUEST", method, site, role, occurrence, "none", peer);
      String kind = take(selector, true);
      if (kind.equals("IO")) {
        applied(selector, kind);
        throw new ServiceException(new IOException("HBASE17 injected RPC request IOException"));
      }
      if (kind.equals("CONNECT")) {
        applied(selector, kind);
        throw new ServiceException(new ConnectException("HBASE17 injected RPC request ConnectException"));
      }
      return new RpcPoint(method, site, role, peer, occurrence);
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter RpcPoint point,
        @Advice.Thrown(readOnly = false) Throwable error) {
      if (point == null) return;
      String original = error == null ? "none" : error.getClass().getName();
      String selector = event("RPC_RESPONSE", point.method, point.site, point.role,
        point.occurrence, original, point.peer);
      String kind = take(selector, error == null);
      if (kind.equals("IO")) {
        applied(selector, kind);
        error = new ServiceException(new IOException("HBASE17 injected RPC response IOException"));
      } else if (kind.equals("TIMEOUT")) {
        applied(selector, kind);
        error = new ServiceException(new SocketTimeoutException(
          "HBASE17 injected RPC response SocketTimeoutException"));
      }
    }
  }

  public static class MetaPut {
    @Advice.OnMethodEnter
    public static void enter() throws IOException {
      String site = callsite();
      if (!site.startsWith("RegionStateStore.")) return;
      String role = role();
      int occurrence = ordinal("META_PUT~hbase:meta~" + site + "~" + role);
      String selector = event("META_PUT", "hbase:meta", site, role, occurrence,
        "none", "local");
      String kind = take(selector, true);
      if (kind.equals("IO")) {
        applied(selector, kind);
        throw new IOException("HBASE17 injected hbase:meta put IOException");
      }
    }
  }
}
