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

/** Runtime probes at replay RPC ingress and the selected OperationStatus check. */
public final class HBase30Agent {
  private static final Map<String, Integer> hits = new HashMap<>();
  public static final AtomicLong callIds = new AtomicLong();
  public static final ThreadLocal<Long> activeReplay = new ThreadLocal<>();
  public static final ThreadLocal<Boolean> selectedReplay = new ThreadLocal<>();
  public static final ThreadLocal<Boolean> badBatchStatus = new ThreadLocal<>();
  private static long ioSequence;
  private static int nextFault;
  private static final String[] faults = System.getProperty("hbase30.fault.plan", "").split(";");

  public static void premain(String args, Instrumentation inst) {
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.regionserver.RSRpcServices"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(Replay.class).on(named("replay").and(takesArguments(2))))
        .visit(Advice.to(BatchResult.class).on(named("doReplayBatchOp").and(takesArguments(3)))))
      .installOn(inst);
  }

  public static synchronized void io(String table, int replica, int entries)
      throws org.apache.hbase.thirdparty.com.google.protobuf.ServiceException {
    if (table == null || !table.equals("testRegionReplicaReplicationWithReplicas_2")
        || replica != 1) return;
    String key = "RPC_REPLAY~" + table + "#" + replica + "~RSRpcServices.replay:2235";
    int hit = hits.containsKey(key) ? hits.get(key) + 1 : 1;
    hits.put(key, hit);
    String selector = key + "~" + hit;
    long seq = ++ioSequence;
    System.err.println("HBASE30 IO seq=" + seq + " selector=" + selector + " entries=" + entries);
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
    System.err.println("HBASE30 FAULT_APPLIED seq=" + seq + " step=" + nextFault
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
      badBatchStatus.set(false);
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
      System.err.println("HBASE30 REPLAY_ENTER call=" + id + " table=" + table
          + " replica=" + replica + " entries=" + count + " distinct_regions=" + regions.size());
      selectedReplay.set("testRegionReplicaReplicationWithReplicas_2".equals(table)
          && replica == 1);
      io(table, replica, count);
    }

    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Thrown Throwable thrown) {
      Throwable cause = thrown == null ? null : thrown.getCause();
      boolean targetError = Boolean.TRUE.equals(selectedReplay.get())
          && Boolean.TRUE.equals(badBatchStatus.get())
          && cause instanceof IOException;
      System.err.println("HBASE30 REPLAY_EXIT call=" + activeReplay.get()
          + " thrown=" + (thrown == null ? "none" : thrown.getClass().getName())
          + " cause=" + (cause == null ? "none" : cause.getClass().getName())
          + " status_error=" + targetError);
      activeReplay.remove();
      selectedReplay.remove();
      badBatchStatus.remove();
    }
  }

  public static final class BatchResult {
    @Advice.OnMethodExit
    public static void exit(@Advice.Return
        org.apache.hadoop.hbase.regionserver.OperationStatus[] statuses,
        @Advice.Argument(0) org.apache.hadoop.hbase.regionserver.HRegion region) {
      Long call = activeReplay.get();
      if (call == null || !Boolean.TRUE.equals(selectedReplay.get())) return;
      int bad = 0;
      String firstBadMessage = "none";
      if (statuses != null) {
        for (org.apache.hadoop.hbase.regionserver.OperationStatus status : statuses) {
          if (status != org.apache.hadoop.hbase.regionserver.OperationStatus.SUCCESS) {
            bad++;
            if (firstBadMessage.equals("none"))
              firstBadMessage = String.valueOf(status == null ? null : status.getExceptionMsg());
          }
        }
      }
      if (bad > 0) badBatchStatus.set(true);
      if (firstBadMessage.isEmpty()) firstBadMessage = "<empty>";
      System.err.println("HBASE30 BATCH_RETURN call=" + call
          + " region=" + region.getRegionInfo().getEncodedName()
          + " replica=" + region.getRegionInfo().getReplicaId()
          + " statuses=" + (statuses == null ? -1 : statuses.length)
          + " non_success=" + bad + " first_message="
          + firstBadMessage.replaceAll("\\s+", "_"));
    }
  }
}
