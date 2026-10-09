import java.io.IOException;
import java.lang.instrument.Instrumentation;
import java.net.ConnectException;
import java.net.SocketTimeoutException;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import org.apache.hbase.thirdparty.com.google.protobuf.Descriptors;
import org.apache.hbase.thirdparty.com.google.protobuf.ServiceException;
import org.apache.hadoop.hbase.master.assignment.RegionStateNode;

/** Case-local, graph-free observer for the HBASE-10 in-transition guard. */
public class HBase10Agent {
  public static final String TEST_TABLE = "testDisableAndMove";
  public static final ThreadLocal<String> STEP = new ThreadLocal<>();
  public static final ConcurrentHashMap<String, AtomicInteger> HITS =
    new ConcurrentHashMap<>();
  public static final AtomicInteger TARGET_HITS = new AtomicInteger();
  public static final List<Fault> PLAN = new ArrayList<>();
  public static int nextFault;

  public static final class Fault {
    public final String id;
    public final String kind;
    public Fault(String id, String kind) { this.id = id; this.kind = kind; }
  }

  public static void premain(String args, Instrumentation inst) {
    String planFile = System.getProperty("hbase10.fault.plan", "");
    if (!planFile.isEmpty()) {
      try {
        for (String line : Files.readAllLines(Paths.get(planFile))) {
          String[] fields = line.trim().split("\\s+", 2);
          if (fields.length == 2 && !fields[0].startsWith("#"))
            PLAN.add(new Fault(fields[0], fields[1]));
        }
      } catch (IOException e) { throw new IllegalStateException(e); }
    }
    new AgentBuilder.Default()
      .type(net.bytebuddy.matcher.ElementMatchers.named(
        "org.apache.hadoop.hbase.master.assignment.AssignmentManager"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Target.class).on(
          net.bytebuddy.matcher.ElementMatchers.named("preTransitCheck")
            .and(net.bytebuddy.matcher.ElementMatchers.takesArguments(2)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(net.bytebuddy.matcher.ElementMatchers.named(
        "org.apache.hadoop.hbase.client.HBaseAdmin"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(AdminStep.class).on(
          net.bytebuddy.matcher.ElementMatchers.named("move")
            .and(net.bytebuddy.matcher.ElementMatchers.takesArguments(2))
            .or(net.bytebuddy.matcher.ElementMatchers.named("assign")
              .and(net.bytebuddy.matcher.ElementMatchers.takesArguments(1)))
            .or(net.bytebuddy.matcher.ElementMatchers.named("unassign")
              .and(net.bytebuddy.matcher.ElementMatchers.takesArguments(1)))
            .or(net.bytebuddy.matcher.ElementMatchers.named("disableTableAsync")
              .and(net.bytebuddy.matcher.ElementMatchers.takesArguments(1))))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(net.bytebuddy.matcher.ElementMatchers.named(
        "org.apache.hadoop.hbase.ipc.AbstractRpcClient"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Rpc.class).on(
          net.bytebuddy.matcher.ElementMatchers.named("callBlockingMethod")
            .and(net.bytebuddy.matcher.ElementMatchers.takesArguments(6)))))
      .installOn(inst);
  }

  public static boolean inTest() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (frame.getClassName().equals("org.apache.hadoop.hbase.regionserver.TestRegionMove")
          && frame.getMethodName().equals("testDisableAndMove")) return true;
    }
    return false;
  }

  public static int hit(String key) {
    return HITS.computeIfAbsent(key, ignored -> new AtomicInteger()).incrementAndGet();
  }

  public static String id(String key, int ordinal) {
    try {
      byte[] digest = MessageDigest.getInstance("SHA-256")
        .digest((key + "|" + ordinal).getBytes("UTF-8"));
      StringBuilder result = new StringBuilder();
      for (int i = 0; i < 10; i++)
        result.append(String.format("%02x", digest[i] & 255));
      return result.toString();
    } catch (Exception e) { throw new IllegalStateException(e); }
  }

  public static synchronized String take(String pointId, boolean possible) {
    if (!possible || nextFault >= PLAN.size() || !PLAN.get(nextFault).id.equals(pointId))
      return "";
    return PLAN.get(nextFault++).kind;
  }

  public static class Target {
    @Advice.OnMethodEnter
    public static int enter(@Advice.Argument(0) RegionStateNode regionNode) {
      if (!regionNode.getTable().getNameAsString().equals(TEST_TABLE)) return -1;
      int ordinal = TARGET_HITS.incrementAndGet();
      Object procedure = regionNode.getProcedure();
      System.err.println("HBASE10 TARGET_ENTER ordinal=" + ordinal
        + " table=" + TEST_TABLE
        + " region=" + regionNode.getRegionInfo().getEncodedName()
        + " state=" + regionNode.getState()
        + " hasProcedure=" + (procedure != null));
      return ordinal;
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter int ordinal, @Advice.Thrown Throwable error) {
      if (ordinal < 0) return;
      boolean b1 = error != null && error.getMessage() != null
        && error.getMessage().contains("is currently in transition; pid=");
      System.err.println("HBASE10 TARGET_EXIT ordinal=" + ordinal
        + " b1Thrown=" + b1
        + " exception=" + (error == null ? "none" : error.getClass().getName()));
    }
  }

  public static class AdminStep {
    @Advice.OnMethodEnter
    public static String enter(@Advice.Origin("#m") String method) {
      if (!inTest()) return null;
      String step = method + "#" + hit("STEP|" + method);
      STEP.set(step);
      System.err.println("HBASE10 STEP_ENTER step=" + step);
      return step;
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter String step, @Advice.Thrown Throwable error) {
      if (step == null) return;
      System.err.println("HBASE10 STEP_EXIT step=" + step
        + " exception=" + (error == null ? "none" : error.getClass().getName()));
      STEP.remove();
    }
  }

  public static final class RpcPoint {
    public final String step;
    public final String method;
    public final String destination;
    public final int ordinal;
    public RpcPoint(String step, String method, String destination, int ordinal) {
      this.step = step;
      this.method = method;
      this.destination = destination;
      this.ordinal = ordinal;
    }
  }

  public static class Rpc {
    @Advice.OnMethodEnter
    public static RpcPoint enter(@Advice.Argument(0) Descriptors.MethodDescriptor descriptor,
                                 @Advice.Argument(5) Object address) throws ServiceException {
      String step = STEP.get();
      if (step == null) return null;
      String method = descriptor.getFullName();
      String base = step + "|" + method;
      int ordinal = hit("RPC|" + base);
      String family = "RPC_REQUEST|" + base;
      String pointId = id(family, ordinal);
      String kind = take(pointId, true);
      boolean applied = kind.equals("IOException") || kind.equals("ConnectException");
      System.err.println("HBASE10 IO marker=RPC_REQUEST id=" + pointId
        + " family=" + family + " ordinal=" + ordinal
        + " step=" + step + " method=" + method
        + " destination=" + address + " fault=" + kind + " applied=" + applied);
      if (kind.equals("IOException"))
        throw new ServiceException(new IOException("HBASE10 injected RPC request IOException"));
      if (kind.equals("ConnectException"))
        throw new ServiceException(new ConnectException("HBASE10 injected RPC request ConnectException"));
      return new RpcPoint(step, method, String.valueOf(address), ordinal);
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter RpcPoint point,
                            @Advice.Thrown(readOnly = false) Throwable error) {
      if (point == null) return;
      String family = "RPC_RESPONSE|" + point.step + "|" + point.method;
      String pointId = id(family, point.ordinal);
      String kind = take(pointId, error == null);
      boolean applied = kind.equals("IOException") || kind.equals("SocketTimeoutException");
      System.err.println("HBASE10 IO marker=RPC_RESPONSE id=" + pointId
        + " family=" + family + " ordinal=" + point.ordinal
        + " step=" + point.step + " method=" + point.method
        + " destination=" + point.destination + " fault=" + kind
        + " applied=" + applied
        + " originalException=" + (error == null ? "none" : error.getClass().getName()));
      if (kind.equals("IOException"))
        error = new ServiceException(new IOException("HBASE10 injected RPC response IOException"));
      if (kind.equals("SocketTimeoutException"))
        error = new ServiceException(new SocketTimeoutException(
          "HBASE10 injected RPC response SocketTimeoutException"));
    }
  }
}
