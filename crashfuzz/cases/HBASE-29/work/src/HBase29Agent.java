import java.io.IOException;
import java.lang.instrument.Instrumentation;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.atomic.AtomicLong;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import static net.bytebuddy.matcher.ElementMatchers.*;

/** Runtime probes at replay RPC ingress and the selected per-entry check. */
public final class HBase29Agent {
  private static final Map<String, Integer> hits = new HashMap<>();
  public static final AtomicLong callIds = new AtomicLong();
  public static final ThreadLocal<Long> activeReplay = new ThreadLocal<>();
  private static long ioSequence;
  private static int nextFault;
  private static final String[] faults = System.getProperty("hbase29.fault.plan", "").split(";");

  public static void premain(String args, Instrumentation inst) {
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.regionserver.RSRpcServices"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Replay.class).on(named("replay").and(takesArguments(2)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.wal.WALSplitUtil"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(EntryGuard.class).on(named("getMutationsFromWALEntry").and(takesArguments(4)))))
      .installOn(inst);
  }

  public static synchronized void io(String table, int replica, int entries)
      throws org.apache.hbase.thirdparty.com.google.protobuf.ServiceException {
    if (table == null || !table.startsWith("testRegionReplicaReplicationWithReplicas_2")) return;
    String key = "RPC_REPLAY~" + table + "#" + replica + "~RSRpcServices.replay:2235";
    int hit = hits.containsKey(key) ? hits.get(key) + 1 : 1;
    hits.put(key, hit);
    String selector = key + "~" + hit;
    long seq = ++ioSequence;
    System.err.println("HBASE29 IO seq=" + seq + " selector=" + selector + " entries=" + entries);
    if (nextFault >= faults.length || faults[nextFault].isEmpty()) return;
    String[] step = faults[nextFault].split("~", 5);
    if (step.length != 5 || !selector.equals(step[0] + "~" + step[1] + "~" + step[2] + "~" + step[3]))
      return;
    String kind = step[4];
    IOException cause;
    if (kind.equals("IOEXCEPTION")) cause = new IOException("injected replay RPC " + selector);
    else if (kind.equals("EOF")) cause = new java.io.EOFException("injected replay RPC " + selector);
    else if (kind.equals("NOTFOUND")) cause = new java.io.FileNotFoundException("injected replay RPC " + selector);
    else throw new IllegalArgumentException("Unsupported fault kind " + kind);
    ++nextFault;
    System.err.println("HBASE29 FAULT_APPLIED seq=" + seq + " step=" + nextFault
        + " selector=" + selector + " kind=" + kind);
    throw new org.apache.hbase.thirdparty.com.google.protobuf.ServiceException(cause);
  }

  public static final class Replay {
    @Advice.OnMethodEnter
    public static void enter(
        @Advice.Argument(1) org.apache.hadoop.hbase.shaded.protobuf.generated.AdminProtos.ReplicateWALEntryRequest request,
        @Advice.FieldValue("regionServer") org.apache.hadoop.hbase.regionserver.HRegionServer server)
        throws org.apache.hbase.thirdparty.com.google.protobuf.ServiceException {
      long id = callIds.incrementAndGet();
      activeReplay.set(id);
      int count = request.getEntryCount();
      Set<String> regions = new HashSet<>();
      for (org.apache.hadoop.hbase.shaded.protobuf.generated.AdminProtos.WALEntry entry : request.getEntryList())
        regions.add(entry.getKey().getEncodedRegionName().toStringUtf8());
      String table = null;
      int replica = -1;
      if (count > 0) {
        String encoded = request.getEntry(0).getKey().getEncodedRegionName().toStringUtf8();
        try {
          org.apache.hadoop.hbase.regionserver.HRegion region = server.getRegionByEncodedName(encoded);
          table = region.getRegionInfo().getTable().getNameAsString();
          replica = region.getRegionInfo().getReplicaId();
        } catch (Exception ignored) {
          // A failed lookup has no stable logical region identity for fault matching.
        }
      }
      System.err.println("HBASE29 REPLAY_ENTER call=" + id + " table=" + table
          + " replica=" + replica + " entries=" + count + " distinct_regions=" + regions.size());
      io(table, replica, count);
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Thrown Throwable thrown) {
      Throwable cause = thrown == null ? null : thrown.getCause();
      boolean mixed = cause instanceof org.apache.hadoop.hbase.NotServingRegionException
          && String.valueOf(cause.getMessage()).contains("Replay request contains entries from multiple");
      System.err.println("HBASE29 REPLAY_EXIT call=" + activeReplay.get()
          + " thrown=" + (thrown == null ? "none" : thrown.getClass().getName())
          + " cause=" + (cause == null ? "none" : cause.getClass().getName())
          + " mixed_region=" + mixed);
      activeReplay.remove();
    }
  }

  public static final class EntryGuard {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(0)
        org.apache.hadoop.hbase.shaded.protobuf.generated.AdminProtos.WALEntry entry) {
      Long call = activeReplay.get();
      if (call != null)
        System.err.println("HBASE29 ENTRY_AFTER_GUARD call=" + call
            + " region=" + entry.getKey().getEncodedRegionName().toStringUtf8());
    }
  }
}
