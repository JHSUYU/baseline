import java.io.IOException;
import java.io.File;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.lang.instrument.Instrumentation;
import java.net.ConnectException;
import java.net.SocketTimeoutException;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import org.apache.hbase.thirdparty.com.google.protobuf.Descriptors;
import org.apache.hbase.thirdparty.com.google.protobuf.ServiceException;
import org.apache.hadoop.hbase.client.TableState;
import static net.bytebuddy.matcher.ElementMatchers.*;

/** Standalone graph-free I/O recorder and ordered fault injector for HBASE-04. */
public class HBase04CampaignAgent {
  public static final AtomicInteger FLUSH_INDEX = new AtomicInteger();
  public static final ThreadLocal<Context> CURRENT = new ThreadLocal<>();
  public static final ThreadLocal<Boolean> IN_META_READ = new ThreadLocal<>();
  public static final List<FaultSpec> PLAN = new ArrayList<>();
  public static final ConcurrentHashMap<String,AtomicInteger> GLOBAL_HITS =
    new ConcurrentHashMap<>();
  public static int nextFault = 0;

  public static final class FaultSpec {
    public final String id;
    public final String kind;
    public FaultSpec(String id, String kind) { this.id = id; this.kind = kind; }
  }

  public static final class Context {
    public final int flushIndex;
    public final String table;
    public int metaReads;
    public final Map<String,Integer> rpcHits = new HashMap<>();
    public Context(int flushIndex, String table) {
      this.flushIndex = flushIndex;
      this.table = table;
    }
  }

  public static void premain(String args, Instrumentation inst) {
    String planFile = System.getProperty("hbase04.campaign.plan", "");
    if (!planFile.isEmpty()) {
      try {
        for (String line : Files.readAllLines(Paths.get(planFile))) {
          String[] fields = line.trim().split("\\s+", 2);
          if (fields.length == 2 && !fields[0].startsWith("#"))
            PLAN.add(new FaultSpec(fields[0], fields[1]));
        }
      } catch (IOException error) { throw new IllegalStateException(error); }
    }
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.client.HBaseAdmin"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Flush.class).on(named("flushAsync").and(takesArguments(2))))
        .visit(Advice.to(IsEnabled.class).on(named("isTableEnabled").and(takesArguments(1)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.MetaTableAccessor"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(MetaRead.class).on(named("getTableState").and(takesArguments(2))))
        .visit(Advice.to(MetaWrite.class).on(named("updateTableState").and(takesArguments(2)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.ipc.AbstractRpcClient"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Rpc.class).on(named("callBlockingMethod").and(takesArguments(6)))))
      .installOn(inst);
  }

  public static String pointId(String stableKey, int ordinal) {
    try {
      byte[] digest = MessageDigest.getInstance("SHA-256")
        .digest((stableKey + "|" + ordinal).getBytes("UTF-8"));
      StringBuilder out = new StringBuilder();
      for (int i = 0; i < 10; i++) out.append(String.format("%02x", digest[i] & 255));
      return out.toString();
    } catch (Exception error) { throw new IllegalStateException(error); }
  }

  public static synchronized String takeIfNext(String id, boolean canApply) {
    if (!canApply || nextFault >= PLAN.size() || !PLAN.get(nextFault).id.equals(id))
      return "";
    return PLAN.get(nextFault++).kind;
  }

  public static int nextRpcHit(Context ctx, String key) {
    Integer prior = ctx.rpcHits.get(key);
    int next = prior == null ? 1 : prior + 1;
    ctx.rpcHits.put(key, next);
    return next;
  }

  public static int nextGlobalHit(String key) {
    return GLOBAL_HITS.computeIfAbsent(key, ignored -> new AtomicInteger()).incrementAndGet();
  }

  public static boolean inOriginalTest() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (frame.getClassName().equals("org.apache.hadoop.hbase.mob.TestMobStoreScanner")
          && frame.getMethodName().equals("testMobStoreScanner")) return true;
    }
    return false;
  }

  public static class Flush {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(0) Object table) {
      if (!inOriginalTest()) return;
      Context ctx = new Context(FLUSH_INDEX.getAndIncrement(), String.valueOf(table));
      CURRENT.set(ctx);
      System.err.println("HBASE04 TARGET_ENTER flushIndex=" + ctx.flushIndex +
        " table=" + ctx.table);
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Thrown Throwable error) {
      Context ctx = CURRENT.get();
      if (ctx == null) return;
      System.err.println("HBASE04 TARGET_EXIT flushIndex=" + ctx.flushIndex +
        " metaReads=" + ctx.metaReads + " exception=" +
        (error == null ? "none" : error.getClass().getName() + ":" + error.getMessage()));
      CURRENT.remove();
    }
  }

  public static class IsEnabled {
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Return boolean enabled, @Advice.Thrown Throwable error) {
      Context ctx = CURRENT.get();
      if (ctx == null) return;
      System.err.println("HBASE04 CHECK flushIndex=" + ctx.flushIndex +
        " enabled=" + enabled + " exception=" +
        (error == null ? "none" : error.getClass().getName()));
    }
  }

  public static class MetaRead {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(1) Object table) {
      Context ctx = CURRENT.get();
      if (ctx != null && ctx.table.equals(String.valueOf(table)))
        IN_META_READ.set(Boolean.TRUE);
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Argument(1) Object table,
                            @Advice.Thrown(readOnly = false) Throwable error) {
      Context ctx = CURRENT.get();
      if (ctx == null || !ctx.table.equals(String.valueOf(table))) return;
      int hit = ++ctx.metaReads;
      String family = "META_READ|" + ctx.flushIndex + "|" + ctx.table
        + "|MetaTableAccessor.getTableState";
      String id = pointId(family, hit);
      String kind = takeIfNext(id, error == null);
      boolean applied = kind.equals("IOException") || kind.equals("SocketTimeoutException");
      System.err.println("HBASE04 IO marker=META_READ id=" + id +
        " family=" + family + " ordinal=" + hit + " table=" + ctx.table +
        " flushIndex=" + ctx.flushIndex + " fault=" + kind + " applied=" + applied +
        " originalException=" + (error == null ? "none" : error.getClass().getName()));
      if (kind.equals("IOException"))
        error = new IOException("HBASE04 graphfree injected TableState read IOException");
      if (kind.equals("SocketTimeoutException"))
        error = new SocketTimeoutException(
          "HBASE04 graphfree injected TableState read SocketTimeoutException");
      IN_META_READ.remove();
    }
  }

  public static class MetaWrite {
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Argument(1) TableState state,
                            @Advice.Thrown(readOnly = false) Throwable error) {
      String table = state.getTableName().getNameAsString();
      String family = "META_WRITE|" + table + "|" + state.getState()
        + "|MetaTableAccessor.updateTableState";
      int hit = nextGlobalHit(family);
      String id = pointId(family, hit);
      String kind = takeIfNext(id, error == null);
      boolean applied = kind.equals("IOException");
      System.err.println("HBASE04 IO marker=META_WRITE id=" + id +
        " family=" + family + " ordinal=" + hit + " table=" + table +
        " state=" + state.getState() + " fault=" + kind + " applied=" + applied +
        " originalException=" + (error == null ? "none" : error.getClass().getName()));
      if (applied)
        error = new IOException("HBASE04 graphfree injected TableState write IOException");
    }
  }

  public static final class RpcPoint {
    public final int flushIndex;
    public final String table;
    public final String stage;
    public final String method;
    public final String destination;
    public final int ordinal;
    public final String baseKey;
    public RpcPoint(Context ctx, String stage, String method, String destination,
                    int ordinal, String baseKey) {
      this.flushIndex = ctx.flushIndex;
      this.table = ctx.table;
      this.stage = stage;
      this.method = method;
      this.destination = destination;
      this.ordinal = ordinal;
      this.baseKey = baseKey;
    }
  }

  public static class Rpc {
    @Advice.OnMethodEnter
    public static RpcPoint enter(@Advice.Argument(0) Descriptors.MethodDescriptor md,
                                 @Advice.Argument(5) Object address)
      throws ServiceException {
      Context ctx = CURRENT.get();
      if (ctx == null) return null;
      String stage = Boolean.TRUE.equals(IN_META_READ.get()) ? "meta" : "flush";
      String method = md.getFullName();
      String destination = String.valueOf(address);
      String base = ctx.flushIndex + "|" + ctx.table + "|" + stage + "|" + method;
      int hit = nextRpcHit(ctx, base);
      String family = "RPC_REQUEST|" + base;
      String id = pointId(family, hit);
      String kind = takeIfNext(id, true);
      boolean applied = kind.equals("ConnectException") || kind.equals("IOException");
      System.err.println("HBASE04 IO marker=RPC_REQUEST id=" + id +
        " family=" + family + " ordinal=" + hit + " table=" + ctx.table +
        " flushIndex=" + ctx.flushIndex + " stage=" + stage +
        " method=" + method + " destination=" + destination +
        " fault=" + kind + " applied=" + applied);
      if (kind.equals("ConnectException"))
        throw new ServiceException(new ConnectException(
          "HBASE04 graphfree injected RPC request ConnectException"));
      if (kind.equals("IOException"))
        throw new ServiceException(new IOException(
          "HBASE04 graphfree injected RPC request IOException"));
      return new RpcPoint(ctx, stage, method, destination, hit, base);
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter RpcPoint point,
                            @Advice.Thrown(readOnly = false) Throwable error) {
      if (point == null) return;
      String family = "RPC_RESPONSE|" + point.baseKey;
      String id = pointId(family, point.ordinal);
      String kind = takeIfNext(id, error == null);
      boolean applied = kind.equals("SocketTimeoutException") || kind.equals("IOException");
      System.err.println("HBASE04 IO marker=RPC_RESPONSE id=" + id +
        " family=" + family + " ordinal=" + point.ordinal +
        " table=" + point.table + " flushIndex=" + point.flushIndex +
        " stage=" + point.stage + " method=" + point.method +
        " destination=" + point.destination + " fault=" + kind +
        " applied=" + applied + " originalException=" +
        (error == null ? "none" : error.getClass().getName()));
      if (kind.equals("SocketTimeoutException"))
        error = new ServiceException(new SocketTimeoutException(
          "HBASE04 graphfree injected RPC response SocketTimeoutException"));
      if (kind.equals("IOException"))
        error = new ServiceException(new IOException(
          "HBASE04 graphfree injected RPC response IOException"));
    }
  }
}
