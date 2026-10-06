import static net.bytebuddy.matcher.ElementMatchers.named;
import static net.bytebuddy.matcher.ElementMatchers.takesArguments;

import java.io.IOException;
import java.lang.instrument.Instrumentation;
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
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.TableState;

/** Independent TableState I/O recorder for the original HBASE-12 JUnit. */
public class HBase12MetaAgent {
  public static final String TEST_TABLE = "testDisableAndMove";
  static final ConcurrentHashMap<String, AtomicInteger> HITS = new ConcurrentHashMap<>();
  static final List<Fault> PLAN = new ArrayList<>();
  static int nextFault;
  static int applied;

  static final class Fault {
    final String id;
    final String kind;
    Fault(String id, String kind) { this.id = id; this.kind = kind; }
  }

  public static void premain(String args, Instrumentation inst) {
    String planFile = System.getProperty("hbase12meta.fault.plan", "");
    if (!planFile.isEmpty()) {
      try {
        for (String line : Files.readAllLines(Paths.get(planFile))) {
          String[] fields = line.trim().split("\\s+", 2);
          if (fields.length == 2 && !fields[0].startsWith("#"))
            PLAN.add(new Fault(fields[0], fields[1]));
        }
      } catch (IOException error) { throw new IllegalStateException(error); }
    }
    Runtime.getRuntime().addShutdownHook(new Thread(() ->
      System.err.println("HBASE12META PLAN requested=" + PLAN.size()
        + " matched=" + nextFault + " applied=" + applied)));
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.MetaTableAccessor"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(MetaRead.class).on(named("getTableState").and(takesArguments(2))))
        .visit(Advice.to(MetaWrite.class).on(named("updateTableState").and(takesArguments(2)))))
      .installOn(inst);
  }

  public static int hit(String family) {
    return HITS.computeIfAbsent(family, ignored -> new AtomicInteger()).incrementAndGet();
  }

  public static String id(String family, int ordinal) {
    try {
      byte[] digest = MessageDigest.getInstance("SHA-256")
        .digest((family + "|" + ordinal).getBytes("UTF-8"));
      StringBuilder result = new StringBuilder();
      for (int i = 0; i < 10; i++) result.append(String.format("%02x", digest[i] & 255));
      return result.toString();
    } catch (Exception error) { throw new IllegalStateException(error); }
  }

  public static synchronized String take(String pointId, boolean possible) {
    if (!possible || nextFault >= PLAN.size() || !PLAN.get(nextFault).id.equals(pointId))
      return "";
    return PLAN.get(nextFault++).kind;
  }

  public static synchronized void applied() { applied++; }

  public static class MetaRead {
    @Advice.OnMethodEnter
    public static int enter(@Advice.Argument(1) TableName table) throws IOException {
      if (!TEST_TABLE.equals(table.getNameAsString())) return -1;
      String family = "META_READ_REQUEST|" + TEST_TABLE + "|MetaTableAccessor.getTableState";
      int ordinal = hit(family);
      String pointId = id(family, ordinal);
      String kind = take(pointId, true);
      boolean inject = "IOException".equals(kind);
      System.err.println("HBASE12META IO marker=META_READ_REQUEST id=" + pointId
        + " family=" + family + " ordinal=" + ordinal + " table=" + TEST_TABLE
        + " fault=" + kind + " applied=" + inject);
      if (inject) {
        applied();
        throw new IOException("HBASE12META injected TableState read request IOException");
      }
      return ordinal;
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter int ordinal,
                            @Advice.Thrown(readOnly = false) Throwable error) {
      if (ordinal < 0) return;
      String family = "META_READ_RESPONSE|" + TEST_TABLE + "|MetaTableAccessor.getTableState";
      String pointId = id(family, ordinal);
      String kind = take(pointId, error == null);
      boolean inject = "IOException".equals(kind) || "SocketTimeoutException".equals(kind);
      System.err.println("HBASE12META IO marker=META_READ_RESPONSE id=" + pointId
        + " family=" + family + " ordinal=" + ordinal + " table=" + TEST_TABLE
        + " fault=" + kind + " applied=" + inject
        + " originalException=" + (error == null ? "none" : error.getClass().getName()));
      if (inject) {
        applied();
        error = "IOException".equals(kind)
          ? new IOException("HBASE12META injected TableState read response IOException")
          : new SocketTimeoutException("HBASE12META injected TableState read response timeout");
      }
    }
  }

  public static class MetaWrite {
    @Advice.OnMethodEnter
    public static int enter(@Advice.Argument(1) TableState state) throws IOException {
      if (!TEST_TABLE.equals(state.getTableName().getNameAsString())) return -1;
      String suffix = TEST_TABLE + "|" + state.getState()
        + "|MetaTableAccessor.updateTableState";
      String family = "META_WRITE_REQUEST|" + suffix;
      int ordinal = hit(family);
      String pointId = id(family, ordinal);
      String kind = take(pointId, true);
      boolean inject = "IOException".equals(kind);
      System.err.println("HBASE12META IO marker=META_WRITE_REQUEST id=" + pointId
        + " family=" + family + " ordinal=" + ordinal + " table=" + TEST_TABLE
        + " state=" + state.getState() + " fault=" + kind + " applied=" + inject);
      if (inject) {
        applied();
        throw new IOException("HBASE12META injected TableState write request IOException");
      }
      return ordinal;
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Argument(1) TableState state, @Advice.Enter int ordinal,
                            @Advice.Thrown(readOnly = false) Throwable error) {
      if (ordinal < 0) return;
      String family = "META_WRITE_RESPONSE|" + TEST_TABLE + "|" + state.getState()
        + "|MetaTableAccessor.updateTableState";
      String pointId = id(family, ordinal);
      String kind = take(pointId, error == null);
      boolean inject = "IOException".equals(kind) || "SocketTimeoutException".equals(kind);
      System.err.println("HBASE12META IO marker=META_WRITE_RESPONSE id=" + pointId
        + " family=" + family + " ordinal=" + ordinal + " table=" + TEST_TABLE
        + " state=" + state.getState() + " fault=" + kind + " applied=" + inject
        + " originalException=" + (error == null ? "none" : error.getClass().getName()));
      if (inject) {
        applied();
        error = "IOException".equals(kind)
          ? new IOException("HBASE12META injected TableState write response IOException")
          : new SocketTimeoutException("HBASE12META injected TableState write response timeout");
      }
    }
  }
}
