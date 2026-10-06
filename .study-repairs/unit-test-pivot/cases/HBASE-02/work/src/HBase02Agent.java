import java.io.IOException;
import java.io.EOFException;
import java.lang.instrument.Instrumentation;
import java.net.ConnectException;
import java.net.SocketTimeoutException;
import java.util.Properties;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import static net.bytebuddy.matcher.ElementMatchers.*;

/** A graph-free, case-local probe for the original HBase JUnit workload. */
public class HBase02Agent {
  public static void premain(String args, Instrumentation inst) {
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.client.ConnectionImplementation"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Relocate.class).on(named("relocateRegion").and(takesArguments(3))))
        .visit(Advice.to(Disabled.class).on(named("isTableDisabled").and(takesArguments(1)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.MetaTableAccessor"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(TableStateGet.class).on(named("getTableState").and(takesArguments(2)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.client.ClientServiceCallable"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(MetaRpcGet.class).on(named("doGet"))))
      .installOn(inst);
  }

  public static class Relocate {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(0) Object table) {
      System.err.println("HBASE02 TARGET_ENTER table=" + table);
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Thrown Throwable error) {
      System.err.println("HBASE02 TARGET_EXIT exception=" +
        (error == null ? "none" : error.getClass().getName() + ":" + error.getMessage()));
    }
  }

  public static class Disabled {
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Return boolean disabled, @Advice.Thrown Throwable error) {
      System.err.println("HBASE02 GUARD_TABLE_DISABLED value=" + disabled + " exception=" +
        (error == null ? "none" : error.getClass().getName()));
    }
  }

  public static class TableStateGet {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(1) Object table) {
      StackTraceElement[] stack = Thread.currentThread().getStackTrace();
      for (StackTraceElement f : stack) {
        if (f.getClassName().equals("org.apache.hadoop.hbase.client.ConnectionImplementation")
            && f.getMethodName().equals("relocateRegion")) {
          System.err.println("HBASE02 TABLE_STATE_GET table=" + table);
          break;
        }
      }
    }
  }

  public static class MetaRpcGet {
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
      if (!inTableState || !inRelocate) return;
      Properties p = System.getProperties();
      int hit;
      synchronized (p) {
        hit = Integer.parseInt(p.getProperty("hbase02.hit", "0")) + 1;
        p.setProperty("hbase02.hit", Integer.toString(hit));
      }
      String plan = System.getProperty("hbase02.fault.plan", "");
      String chosen = "";
      for (String step : plan.split(",")) {
        String[] fields = step.split(":", 2);
        if (fields.length == 2 && fields[0].equals(Integer.toString(hit))) chosen = fields[1];
      }
      System.err.println("HBASE02 META_RPC_GET hit=" + hit + " matched=" + !chosen.isEmpty() +
        " applied=" + !chosen.isEmpty() + " fault=" + chosen);
      if (chosen.equals("IOException")) {
        throw new org.apache.hbase.thirdparty.com.google.protobuf.ServiceException(
          new IOException("HBASE02 injected meta table-state Get fault hit=" + hit));
      }
      if (chosen.equals("SocketTimeoutException")) {
        throw new org.apache.hbase.thirdparty.com.google.protobuf.ServiceException(
          new SocketTimeoutException("HBASE02 injected meta table-state Get timeout hit=" + hit));
      }
      if (chosen.equals("EOFException")) {
        throw new org.apache.hbase.thirdparty.com.google.protobuf.ServiceException(
          new EOFException("HBASE02 injected meta table-state Get EOF hit=" + hit));
      }
      if (chosen.equals("ConnectException")) {
        throw new org.apache.hbase.thirdparty.com.google.protobuf.ServiceException(
          new ConnectException("HBASE02 injected meta table-state Get connect fault hit=" + hit));
      }
    }
  }
}
