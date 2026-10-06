import java.io.IOException;
import java.lang.instrument.Instrumentation;
import java.util.HashMap;
import java.util.Map;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import static net.bytebuddy.matcher.ElementMatchers.named;
import static net.bytebuddy.matcher.ElementMatchers.takesArguments;

/** Observes and can fault the real HDFS open used by SnapshotManifest. */
public final class HBase21ManifestAgent {
  private static final Map<String, Integer> hits = new HashMap<>();
  private static long eventSequence;
  private static final String plan = System.getProperty("hbase21.manifest.fault.plan", "");

  public static void premain(String args, Instrumentation inst) {
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hdfs.DistributedFileSystem"))
      .transform((builder, type, loader, module, domain) -> builder.visit(
        Advice.to(DfsOpen.class).on(named("open").and(takesArguments(2)))))
      .installOn(inst);
  }

  private static String snapshotSite() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (frame.getClassName().equals("org.apache.hadoop.hbase.snapshot.SnapshotManifest")
          && frame.getMethodName().equals("readDataManifest")) {
        return "SnapshotManifest.readDataManifest:" + frame.getLineNumber();
      }
    }
    return null;
  }

  private static String snapshotResource(Object path) {
    String full = String.valueOf(path);
    String marker = "/.hbase-snapshot/";
    int at = full.indexOf(marker);
    return at < 0 ? full : full.substring(at + marker.length());
  }

  public static synchronized void onOpen(Object path) throws IOException {
    String site = snapshotSite();
    if (site == null) return;
    String resource = snapshotResource(path);
    String key = "DFS_OPEN~" + resource + "~" + site;
    int ordinal = hits.containsKey(key) ? hits.get(key) + 1 : 1;
    hits.put(key, ordinal);
    long seq = ++eventSequence;
    String selector = key + "~" + ordinal;
    System.err.println("HBASE21 MANIFEST_IO seq=" + seq + " selector=" + selector);
    if (!plan.equals(selector + "~IOEXCEPTION")) return;
    System.err.println("HBASE21 MANIFEST_FAULT_MATCHED seq=" + seq
      + " selector=" + selector + " kind=IOEXCEPTION");
    System.err.println("HBASE21 MANIFEST_FAULT_APPLIED seq=" + seq
      + " selector=" + selector + " kind=IOEXCEPTION");
    throw new IOException("HBASE21 injected DFS.open IOException for " + selector);
  }

  public static final class DfsOpen {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(0) Object path) throws IOException {
      onOpen(path);
    }
  }
}
