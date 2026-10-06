import java.lang.instrument.Instrumentation;
import java.util.concurrent.atomic.AtomicInteger;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import org.apache.hadoop.hbase.regionserver.HRegionServer;
import static net.bytebuddy.matcher.ElementMatchers.*;

/** Read-only graph-free runtime probe for the stale-startcode guard. */
public class HBase31Probe {
  public static final String TABLE = "testDisableAndMove";
  public static final ThreadLocal<Boolean> TABLE_REQUEST = new ThreadLocal<>();
  public static final AtomicInteger TARGET_HITS = new AtomicInteger();
  public static volatile boolean TEST_ACTIVE;

  public static void premain(String args, Instrumentation inst) {
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.regionserver.TestRegionMove"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(TestWindow.class).on(named("testDisableAndMove").and(takesArguments(0)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.regionserver.RSRpcServices"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(RequestWrapper.class).on(named("throwOnWrongStartCode")
          .and(takesArguments(1)).and(not(takesArgument(0, long.class)))))
        .visit(Advice.to(Target.class).on(named("throwOnWrongStartCode")
          .and(takesArguments(1)).and(takesArgument(0, long.class)))))
      .installOn(inst);
  }

  public static class TestWindow {
    @Advice.OnMethodEnter
    public static void enter() {
      TEST_ACTIVE = true;
      System.err.println("HBASE31 TEST_ENTER");
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit() {
      System.err.println("HBASE31 TEST_EXIT");
      TEST_ACTIVE = false;
    }
  }

  public static class RequestWrapper {
    @Advice.OnMethodEnter
    public static Boolean enter(@Advice.Argument(0) Object request) {
      Boolean previous = TABLE_REQUEST.get();
      boolean mentioned = String.valueOf(request).contains(TABLE);
      TABLE_REQUEST.set(Boolean.TRUE.equals(previous) || mentioned);
      if (TEST_ACTIVE)
        System.err.println("HBASE31 REQUEST type=" + request.getClass().getSimpleName()
          + " mentionsTable=" + mentioned
          + " relevantContext=" + TABLE_REQUEST.get());
      return previous;
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter Boolean previous) {
      if (previous == null) TABLE_REQUEST.remove();
      else TABLE_REQUEST.set(previous);
    }
  }

  public static class Target {
    @Advice.OnMethodEnter
    public static int enter(@Advice.Argument(0) long requested,
                            @Advice.FieldValue("regionServer") HRegionServer server) {
      int ordinal = TARGET_HITS.incrementAndGet();
      long actual = server.getServerName().getStartcode();
      System.err.println("HBASE31 TARGET_ENTER ordinal=" + ordinal
        + " duringTest=" + TEST_ACTIVE
        + " relevantTable=" + Boolean.TRUE.equals(TABLE_REQUEST.get())
        + " requestedStartCode=" + requested
        + " actualStartCode=" + actual
        + " mismatch=" + (requested != actual));
      return ordinal;
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter int ordinal, @Advice.Thrown Throwable error) {
      System.err.println("HBASE31 TARGET_EXIT ordinal=" + ordinal
        + " exception=" + (error == null ? "none" : error.getClass().getName())
        + " cause=" + (error == null || error.getCause() == null
          ? "none" : error.getCause().getClass().getName()));
    }
  }
}
