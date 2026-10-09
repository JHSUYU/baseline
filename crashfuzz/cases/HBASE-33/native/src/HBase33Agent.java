import java.lang.instrument.Instrumentation;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import static net.bytebuddy.matcher.ElementMatchers.*;

/** Direct healthy-path probe for the original token JUnit. */
public class HBase33Agent {
  public static final AtomicBoolean TEST_ACTIVE = new AtomicBoolean();

  public static void premain(String args, Instrumentation inst) {
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.security.token.TestTokenAuthentication"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(TestScope.class).on(named("testTokenCreation").and(takesArguments(0)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.security.token.AuthenticationTokenSecretManager"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Retrieve.class).on(named("retrievePassword").and(takesArguments(1)))))
      .installOn(inst);
  }

  public static class TestScope {
    @Advice.OnMethodEnter
    public static void enter() {
      TEST_ACTIVE.set(true);
      System.err.println("HBASE33 TEST_ENTER method=testTokenCreation");
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Thrown Throwable error) {
      System.err.println("HBASE33 TEST_EXIT exception="
        + (error == null ? "none" : error.getClass().getName()));
      TEST_ACTIVE.set(false);
    }
  }

  public static class Retrieve {
    @Advice.OnMethodEnter
    public static boolean enter(
        @Advice.Argument(0) org.apache.hadoop.hbase.security.token.AuthenticationTokenIdentifier id,
        @Advice.FieldValue("allKeys") Map<Integer, ?> allKeys) {
      boolean active = TEST_ACTIVE.get();
      if (active) System.err.println("HBASE33 TARGET_ENTER keyId=" + id.getKeyId()
        + " keyPresent=" + allKeys.containsKey(id.getKeyId())
        + " thread=" + Thread.currentThread().getName());
      return active;
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter boolean active, @Advice.Thrown Throwable error) {
      if (active) System.err.println("HBASE33 TARGET_EXIT exception="
        + (error == null ? "none" : error.getClass().getName()));
    }
  }
}
