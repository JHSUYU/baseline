import java.lang.instrument.Instrumentation;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.ConcurrentHashMap;
import net.bytebuddy.agent.builder.AgentBuilder;
import net.bytebuddy.asm.Advice;
import static net.bytebuddy.matcher.ElementMatchers.*;

/** Direct visitor probe scoped to the unchanged original replication JUnit. */
public class HBase35Agent {
  public static final AtomicBoolean TEST_ACTIVE = new AtomicBoolean();
  public static final AtomicInteger VISIT_IDS = new AtomicInteger();
  public static final AtomicInteger SCAN_HITS = new AtomicInteger();
  public static final AtomicInteger FULL_SCAN_IDS = new AtomicInteger();
  public static final AtomicInteger ACTIVE_FULL_SCAN_ID = new AtomicInteger();
  public static final ConcurrentHashMap<Integer, AtomicInteger> SCAN_HITS_BY_FULL_SCAN =
    new ConcurrentHashMap<Integer, AtomicInteger>();
  public static final ThreadLocal<Integer> ACTIVE_VISIT = new ThreadLocal<Integer>();

  public static String planned(int scanId, int ordinal) {
    for (String entry : System.getProperty("hbase35.fault.plan", "").split(",")) {
      String[] parts = entry.split(":", 4);
      if (parts.length == 4 && parts[0].equals("META_SCAN")
          && parts[1].equals(Integer.toString(scanId))
          && parts[2].equals(Integer.toString(ordinal))) return parts[3];
    }
    return "";
  }

  public static java.io.IOException failure(int scanId, int ordinal, String kind) {
    String message = "HBASE35 injected META_SCAN scanId=" + scanId
      + " ordinal=" + ordinal;
    if (kind.equals("IOException")) return new java.io.IOException(message);
    if (kind.equals("EOFException")) return new java.io.EOFException(message);
    if (kind.equals("SocketTimeoutException")) return new java.net.SocketTimeoutException(message);
    if (kind.equals("ConnectException")) return new java.net.ConnectException(message);
    if (kind.equals("DoNotRetryIOException"))
      return new org.apache.hadoop.hbase.DoNotRetryIOException(message);
    throw new IllegalArgumentException("Unknown SCAN_OPEN fault kind " + kind);
  }

  public static void premain(String args, Instrumentation inst) {
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.util.TestHBaseFsckReplication"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(TestScope.class).on(named("test").and(takesArguments(0)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.util.HBaseFsck$3"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(MetaVisitor.class).on(named("visit").and(takesArguments(1)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.util.HbckRegionInfo"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(MetaEntryGuard.class).on(named("getMetaEntry").and(takesArguments(0)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.regionserver.RSRpcServices"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(ScanRpc.class).on(named("scan").and(takesArguments(2)))))
      .installOn(inst);
    new AgentBuilder.Default()
      .type(named("org.apache.hadoop.hbase.MetaTableAccessor"))
      .transform((builder, type, loader, module, domain) -> builder
        .visit(Advice.to(FullScan.class).on(named("fullScanRegions").and(takesArguments(2)))))
      .installOn(inst);
  }

  public static class TestScope {
    @Advice.OnMethodEnter
    public static void enter() {
      TEST_ACTIVE.set(true);
      System.err.println("HBASE35 TEST_ENTER method=test");
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Thrown Throwable error) {
      System.err.println("HBASE35 TEST_EXIT exception="
        + (error == null ? "none" : error.getClass().getName()));
      TEST_ACTIVE.set(false);
    }
  }

  public static class MetaVisitor {
    @Advice.OnMethodEnter
    public static boolean enter(@Advice.Argument(0)
        org.apache.hadoop.hbase.client.Result result) {
      if (!TEST_ACTIVE.get()) return false;
      int visit = VISIT_IDS.incrementAndGet();
      ACTIVE_VISIT.set(visit);
      System.err.println("HBASE35 TARGET_ENTER visit=" + visit
        + " scanId=" + ACTIVE_FULL_SCAN_ID.get() + " row="
        + org.apache.hadoop.hbase.util.Bytes.toStringBinary(result.getRow())
        + " cells=" + result.size());
      return true;
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter boolean active, @Advice.Thrown Throwable error) {
      if (active) {
        System.err.println("HBASE35 TARGET_EXIT visit=" + ACTIVE_VISIT.get()
          + " exception="
          + (error == null ? "none" : error.getClass().getName() + ":" + error.getMessage()));
        ACTIVE_VISIT.remove();
      }
    }
  }

  public static class MetaEntryGuard {
    @Advice.OnMethodExit
    public static void exit(@Advice.Return Object metaEntry) {
      if (ACTIVE_VISIT.get() != null) System.err.println("HBASE35 GUARD_META_ENTRY visit="
        + ACTIVE_VISIT.get() + " null=" + (metaEntry == null));
    }
  }

  public static class ScanRpc {
    @Advice.OnMethodEnter
    public static void enter(@Advice.Argument(1)
        org.apache.hadoop.hbase.shaded.protobuf.generated.ClientProtos.ScanRequest request)
        throws org.apache.hbase.thirdparty.com.google.protobuf.ServiceException {
      if (!TEST_ACTIVE.get() || !request.hasScan()) return;
      String region = request.hasRegion()
        ? request.getRegion().getValue().toStringUtf8() : "none";
      if (!region.equals("hbase:meta,,1")) return;
      int hit = SCAN_HITS.incrementAndGet();
      int scanId = ACTIVE_FULL_SCAN_ID.get();
      AtomicInteger counter = SCAN_HITS_BY_FULL_SCAN.get(scanId);
      int ordinal = counter == null ? 0 : counter.incrementAndGet();
      String kind = planned(scanId, ordinal);
      System.err.println("HBASE35 IO door=SCAN_OPEN hit=" + hit
        + " scanId=" + scanId + " ordinal=" + ordinal
        + " region=" + region + " regionType="
        + (request.hasRegion() ? request.getRegion().getType() : "none")
        + " matched=" + !kind.isEmpty() + " applied=" + !kind.isEmpty()
        + " fault=" + kind
        + " thread=" + Thread.currentThread().getName());
      if (!kind.isEmpty()) {
        java.io.IOException cause = failure(scanId, ordinal, kind);
        System.err.println("HBASE35 FAULT_THROW scanId=" + scanId
          + " ordinal=" + ordinal + " exception=" + cause.getClass().getName()
          + ":" + cause.getMessage());
        throw new org.apache.hbase.thirdparty.com.google.protobuf.ServiceException(cause);
      }
    }
  }

  public static class FullScan {
    @Advice.OnMethodEnter
    public static int enter() {
      if (!TEST_ACTIVE.get()) return 0;
      int id = FULL_SCAN_IDS.incrementAndGet();
      ACTIVE_FULL_SCAN_ID.set(id);
      SCAN_HITS_BY_FULL_SCAN.put(id, new AtomicInteger());
      System.err.println("HBASE35 FULL_SCAN_ENTER id=" + id);
      return id;
    }
    @Advice.OnMethodExit(onThrowable = Throwable.class)
    public static void exit(@Advice.Enter int id, @Advice.Thrown Throwable error) {
      if (id != 0) System.err.println("HBASE35 FULL_SCAN_EXIT id=" + id
        + " exception=" + (error == null ? "none" : error.getClass().getName()));
      if (id != 0) ACTIVE_FULL_SCAN_ID.compareAndSet(id, 0);
    }
  }
}
