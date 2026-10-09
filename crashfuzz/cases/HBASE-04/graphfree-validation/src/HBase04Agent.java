import java.io.IOException;
import java.lang.instrument.Instrumentation;
import java.net.SocketTimeoutException;
import java.util.concurrent.atomic.AtomicInteger;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import static net.bytebuddy.matcher.ElementMatchers.*;

/** Standalone HBASE-04 identity replay probe; no GraphChecker classes or skeleton. */
public class HBase04Agent {
  public static final AtomicInteger FLUSH_INDEX = new AtomicInteger();
  public static final ThreadLocal<Context> CURRENT = new ThreadLocal<>();

  public static final class Context {
    public final int flushIndex;
    public final String table;
    public int metaReads;
    public Context(int flushIndex, String table) {
      this.flushIndex = flushIndex;
      this.table = table;
    }
  }

  public static void premain(String args, Instrumentation inst) {
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.client.HBaseAdmin"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Flush.class).on(named("flushAsync").and(takesArguments(2))))
        .visit(Advice.to(IsEnabled.class).on(named("isTableEnabled").and(takesArguments(1)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.MetaTableAccessor"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(MetaRead.class).on(named("getTableState").and(takesArguments(2)))))
      .installOn(inst);
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
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Argument(1) Object table,
                            @Advice.Thrown(readOnly = false) Throwable error) {
      Context ctx = CURRENT.get();
      if (ctx == null || !ctx.table.equals(String.valueOf(table))) return;
      int hit = ++ctx.metaReads;
      int wantedFlush = Integer.getInteger("hbase04.fault.flush", -1);
      int wantedHit = Integer.getInteger("hbase04.fault.hit", -1);
      String kind = System.getProperty("hbase04.fault.kind", "");
      boolean selected = ctx.flushIndex == wantedFlush && hit == wantedHit;
      String plan = System.getProperty("hbase04.fault.plan", "");
      for (String step : plan.split(",")) {
        String[] fields = step.split(":", 3);
        if (fields.length == 3
            && fields[0].equals(Integer.toString(ctx.flushIndex))
            && fields[1].equals(Integer.toString(hit))) {
          selected = true;
          kind = fields[2];
        }
      }
      boolean applied = selected && error == null && !kind.isEmpty();
      System.err.println("HBASE04 META_READ flushIndex=" + ctx.flushIndex +
        " hitOrdinal=" + hit + " table=" + ctx.table +
        " sourceMethod=MetaTableAccessor.getTableState" +
        " selected=" + selected + " applied=" + applied +
        " originalException=" + (error == null ? "none" : error.getClass().getName()));
      if (applied && kind.equals("IOException"))
        error = new IOException("HBASE04 graphfree injected TableState read IOException");
      if (applied && kind.equals("SocketTimeoutException"))
        error = new SocketTimeoutException(
          "HBASE04 graphfree injected TableState read SocketTimeoutException");
    }
  }
}
