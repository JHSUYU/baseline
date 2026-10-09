import java.lang.instrument.Instrumentation;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import static net.bytebuddy.matcher.ElementMatchers.*;

/** Direct healthy-path probe for the original token JUnit. */
public class HBase34Agent {
  public static final AtomicBoolean TEST_ACTIVE = new AtomicBoolean();
  public static final AtomicInteger SASL_HITS = new AtomicInteger();
  public static final ThreadLocal<String> ACTIVE_CHANNEL = new ThreadLocal<String>();

  public static String planned(int hit) {
    for (String entry : System.getProperty("hbase34.fault.plan", "").split(",")) {
      String[] parts = entry.split(":", 3);
      if (parts.length == 3 && parts[0].equals("SASL_IN")
          && parts[1].equals(Integer.toString(hit))) return parts[2];
    }
    return "";
  }

  public static java.io.IOException failure(int hit, String kind) {
    String message = "HBASE34 injected SASL_IN hit=" + hit;
    if (kind.equals("IOException")) return new java.io.IOException(message);
    if (kind.equals("EOFException")) return new java.io.EOFException(message);
    if (kind.equals("SocketTimeoutException")) return new java.net.SocketTimeoutException(message);
    if (kind.equals("ConnectException")) return new java.net.ConnectException(message);
    if (kind.equals("DoNotRetryIOException"))
      return new org.apache.hadoop.hbase.DoNotRetryIOException(message);
    throw new IllegalArgumentException("Unknown SASL fault kind " + kind);
  }

  public static void premain(String args, Instrumentation inst) {
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.security.token.TestGenerateDelegationToken"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(TestScope.class).on(named("testOnlyToken").and(takesArguments(0))))
        .visit(Advice.to(TestTokenCall.class).on(named("testToken").and(takesArguments(0)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.security.token.TokenProvider"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(WhoAmI.class).on(named("whoAmI").and(takesArguments(3)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.security.token.AuthenticationTokenSecretManager"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Retrieve.class).on(named("retrievePassword").and(takesArguments(1)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.ipc.NettyHBaseSaslRpcServerHandler"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(SaslInbound.class).on(named("channelRead0").and(takesArguments(2)))))
      .installOn(inst);
  }

  public static class TestScope {
    @Advice.OnMethodEnter
    public static void enter() {
      TEST_ACTIVE.set(true);
      System.err.println("HBASE34 TEST_ENTER method=testOnlyToken");
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Thrown Throwable error) {
      System.err.println("HBASE34 TEST_EXIT exception="
        + (error == null ? "none" : error.getClass().getName()));
      TEST_ACTIVE.set(false);
    }
  }

  public static class TestTokenCall {
    @Advice.OnMethodEnter
    public static void enter() {
      System.err.println("HBASE34 TEST_TOKEN_ENTER");
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Thrown Throwable error) {
      System.err.println("HBASE34 TEST_TOKEN_EXIT exception="
        + (error == null ? "none" : error.getClass().getName()));
    }
  }

  public static class WhoAmI {
    @Advice.OnMethodEnter
    public static void enter() {
      if (TEST_ACTIVE.get()) System.err.println("HBASE34 WHOAMI_SERVICE_ENTER thread="
        + Thread.currentThread().getName());
    }
  }

  public static class Retrieve {
    @Advice.OnMethodEnter
    public static boolean enter(
        @Advice.Argument(0) org.apache.hadoop.hbase.security.token.AuthenticationTokenIdentifier id,
        @Advice.FieldValue("allKeys") Map<Integer, ?> allKeys) {
      boolean active = TEST_ACTIVE.get();
      if (active) System.err.println("HBASE34 TARGET_ENTER keyId=" + id.getKeyId()
        + " keyPresent=" + allKeys.containsKey(id.getKeyId())
        + " channel=" + ACTIVE_CHANNEL.get()
        + " thread=" + Thread.currentThread().getName());
      return active;
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter boolean active, @Advice.Thrown Throwable error) {
      if (active) System.err.println("HBASE34 TARGET_EXIT exception="
        + (error == null ? "none" : error.getClass().getName() + ":" + error.getMessage()));
    }
  }

  public static class SaslInbound {
    @Advice.OnMethodEnter
    public static boolean enter(
        @Advice.Argument(0) org.apache.hbase.thirdparty.io.netty.channel.ChannelHandlerContext ctx,
        @Advice.Argument(1) org.apache.hbase.thirdparty.io.netty.buffer.ByteBuf msg)
        throws java.io.IOException {
      if (!TEST_ACTIVE.get()) return false;
      int hit = SASL_HITS.incrementAndGet();
      String channel = ctx.channel().id().asShortText();
      ACTIVE_CHANNEL.set(channel);
      String kind = planned(hit);
      boolean applied = !kind.isEmpty();
      System.err.println("HBASE34 IO door=SASL_IN hit=" + hit
        + " channel=" + channel + " bytes=" + msg.readableBytes()
        + " applied=" + applied + " fault=" + kind
        + " thread=" + Thread.currentThread().getName());
      if (applied) {
        ACTIVE_CHANNEL.remove();
        throw failure(hit, kind);
      }
      return true;
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter boolean active, @Advice.Thrown Throwable error) {
      if (!active) return;
      System.err.println("HBASE34 IO_EXIT door=SASL_IN channel=" + ACTIVE_CHANNEL.get()
        + " exception=" + (error == null ? "none" : error.getClass().getName()));
      ACTIVE_CHANNEL.remove();
    }
  }
}
