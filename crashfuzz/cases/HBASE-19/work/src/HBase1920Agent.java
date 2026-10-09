import java.io.EOFException;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.lang.instrument.Instrumentation;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import static net.bytebuddy.matcher.ElementMatchers.*;

/** Runtime-only probes for the two checks in the original modify-table JUnit. */
public final class HBase1920Agent {
  private static final Map<String, Integer> hits = new HashMap<>();
  public static final AtomicLong targetIds = new AtomicLong();
  public static final ThreadLocal<Long> activeTarget = new ThreadLocal<>();
  public static final ThreadLocal<Integer> cfReads = new ThreadLocal<>();
  public static final ThreadLocal<Boolean> noReopen = new ThreadLocal<>();
  private static long ioSequence;
  private static int nextFault;
  private static final String[] faults = System.getProperty("hbase1920.fault.plan", "").split(";");

  public static void premain(String args, Instrumentation inst) {
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.master.procedure.ModifyTableProcedure"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Target.class).on(named("preflightChecks").and(takesArguments(2))))
        .visit(Advice.to(CoprocGuard.class).on(named("isCoprocModified").and(takesArguments(0)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.client.TableDescriptorBuilder$ModifyableTableDescriptor"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(CfCount.class).on(named("getColumnFamilyCount").and(takesArguments(0)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.util.FSTableDescriptors"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(FsRead.class).on(named("getTableDescriptorFromFs").and(takesArguments(3))))
        .visit(Advice.to(FsWrite.class).on(named("updateTableDescriptor").and(takesArguments(1)))))
      .installOn(inst);
  }

  public static String logicalTable(org.apache.hadoop.fs.Path path) {
    String raw = path.toUri().getPath();
    int data = raw.lastIndexOf("/data/");
    if (data < 0) return null;
    String tail = raw.substring(data + 6);
    String[] fields = tail.split("/");
    return fields.length >= 2 ? fields[0] + ":" + fields[1] : null;
  }

  public static String site() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (frame.getClassName().equals("org.apache.hadoop.hbase.util.FSTableDescriptors")
          && !frame.getMethodName().equals("getTableDescriptorFromFs")
          && !frame.getMethodName().equals("updateTableDescriptor")) {
        return frame.getMethodName() + ":" + frame.getLineNumber();
      }
    }
    return "FSTableDescriptors:unknown";
  }

  public static synchronized void io(String family, String table) throws IOException {
    if (table == null || !table.endsWith(":testModifyWillNotReopenRegions")) return;
    String key = family + "~" + table + "~" + site();
    int hit = hits.containsKey(key) ? hits.get(key) + 1 : 1;
    hits.put(key, hit);
    String selector = key + "~" + hit;
    long seq = ++ioSequence;
    System.err.println("HBASE1920 IO seq=" + seq + " selector=" + selector);
    if (nextFault >= faults.length || faults[nextFault].isEmpty()) return;
    String[] step = faults[nextFault].split("~", 5);
    if (step.length != 5 || !selector.equals(step[0] + "~" + step[1]
        + "~" + step[2] + "~" + step[3])) return;
    ++nextFault;
    String kind = step[4];
    System.err.println("HBASE1920 FAULT_APPLIED seq=" + seq + " step=" + nextFault
        + " selector=" + selector + " kind=" + kind);
    if (kind.equals("IOEXCEPTION")) throw new IOException("injected FS I/O " + selector);
    if (kind.equals("EOF")) throw new EOFException("injected FS I/O " + selector);
    if (kind.equals("NOTFOUND")) throw new FileNotFoundException("injected FS I/O " + selector);
    throw new IllegalArgumentException("unsupported fault kind " + kind);
  }

  public static final class Target {
    @Advice.OnMethodEnter
    public static void enter(@Advice.FieldValue("unmodifiedTableDescriptor")
        org.apache.hadoop.hbase.client.TableDescriptor oldDescriptor,
        @Advice.FieldValue("modifiedTableDescriptor")
        org.apache.hadoop.hbase.client.TableDescriptor newDescriptor,
        @Advice.FieldValue("reopenRegions") boolean reopen) {
      long id = targetIds.incrementAndGet();
      activeTarget.set(id);
      cfReads.set(0);
      noReopen.set(!reopen);
      System.err.println("HBASE1920 TARGET_ENTER call=" + id + " no_reopen=" + !reopen
        + " table=" + (newDescriptor == null ? "none" : newDescriptor.getTableName()));
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Thrown Throwable thrown) {
      String message = thrown == null ? "" : String.valueOf(thrown.getMessage());
      String outcome = message.contains("Cannot add or remove column families") ? "cf_reject"
          : message.contains("Can not modify Coprocessor") ? "coproc_reject"
          : thrown == null ? "normal" : "other_exception";
      System.err.println("HBASE1920 TARGET_EXIT call=" + activeTarget.get()
          + " no_reopen=" + noReopen.get() + " cf_reads=" + cfReads.get()
          + " exception=" + (thrown == null ? "none" : thrown.getClass().getName())
          + " outcome=" + outcome);
      activeTarget.remove();
      cfReads.remove();
      noReopen.remove();
    }
  }

  public static final class CfCount {
    @Advice.OnMethodExit
    public static void exit(@Advice.Return int count) {
      Long call = activeTarget.get();
      if (call != null && Boolean.TRUE.equals(noReopen.get())) {
        int ordinal = cfReads.get() + 1;
        cfReads.set(ordinal);
        System.err.println("HBASE1920 CF_GUARD call=" + call
            + " ordinal=" + ordinal + " count=" + count);
      }
    }
  }

  public static final class CoprocGuard {
    @Advice.OnMethodExit
    public static void exit(@Advice.Return boolean modified) {
      Long call = activeTarget.get();
      if (call != null && Boolean.TRUE.equals(noReopen.get()))
        System.err.println("HBASE1920 COPROC_GUARD call=" + call + " modified=" + modified);
    }
  }

  public static final class FsRead {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(1) org.apache.hadoop.fs.Path tableDir)
        throws IOException {
      io("FS_READ", logicalTable(tableDir));
    }
  }

  public static final class FsWrite {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(0)
        org.apache.hadoop.hbase.client.TableDescriptor descriptor) throws IOException {
      io("FS_WRITE", descriptor.getTableName().getNameWithNamespaceInclAsString());
    }
  }
}
