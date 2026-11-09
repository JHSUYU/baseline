/*
 * Reproduction of Specula finding MC-3 (TargetSafe, AssignmentManager.java:769).
 * Variant of TestRegionMove#testDisableAndMove, same module, same setup, public APIs only.
 *
 * The test never writes a guard operand and never edits the target method. It READS RegionStateNode
 * to observe and time. The only timing aid is a master coprocessor on preTruncateRegionAction, the
 * public MasterObserver hook that truncate calls in PRE_OPERATION while it holds the scheduler region
 * lock (TruncateRegionProcedure.java:83,254). It delays truncate and changes no data.
 *
 * Each method runs in its own JVM (see test_bugMC-3_truncate_detach.sh).
 */
package org.apache.hadoop.hbase.regionserver;

import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hbase.HBaseTestingUtil;
import org.apache.hadoop.hbase.HConstants;
import org.apache.hadoop.hbase.MetaTableAccessor;
import org.apache.hadoop.hbase.ServerName;
import org.apache.hadoop.hbase.SingleProcessHBaseCluster;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.Admin;
import org.apache.hadoop.hbase.client.BalanceRequest;
import org.apache.hadoop.hbase.client.BalanceResponse;
import org.apache.hadoop.hbase.client.Connection;
import org.apache.hadoop.hbase.client.ConnectionFactory;
import org.apache.hadoop.hbase.client.DoNotRetryRegionException;
import org.apache.hadoop.hbase.client.Get;
import org.apache.hadoop.hbase.client.Put;
import org.apache.hadoop.hbase.client.RegionInfo;
import org.apache.hadoop.hbase.client.Table;
import org.apache.hadoop.hbase.coprocessor.MasterCoprocessor;
import org.apache.hadoop.hbase.coprocessor.MasterCoprocessorEnvironment;
import org.apache.hadoop.hbase.coprocessor.MasterObserver;
import org.apache.hadoop.hbase.coprocessor.ObserverContext;
import org.apache.hadoop.hbase.master.HMaster;
import org.apache.hadoop.hbase.master.RegionState;
import org.apache.hadoop.hbase.master.assignment.RegionStateNode;
import org.apache.hadoop.hbase.master.assignment.RegionStateStore;
import org.apache.hadoop.hbase.master.assignment.TransitRegionStateProcedure;
import org.apache.hadoop.hbase.master.procedure.MasterProcedureConstants;
import org.apache.hadoop.hbase.master.procedure.ServerCrashProcedure;
import org.apache.hadoop.hbase.procedure2.Procedure;
import org.apache.hadoop.hbase.testclassification.LargeTests;
import org.apache.hadoop.hbase.util.Bytes;
import org.apache.hadoop.hbase.util.JVMClusterUtil;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;

@Tag(LargeTests.TAG)
public class SpeculaMC3TruncateDetachTest {
  private static final String TARGET_FRAME = "AssignmentManager.preTransitCheck(AssignmentManager.java:769)";
  private static final byte[] F1 = Bytes.toBytes("f1");
  private static final long PERMANENCE_MS = 180_000;

  private HBaseTestingUtil util;
  private Admin admin;
  private TableName tableName;

  /** Public MasterObserver hook; delays truncate inside PRE_OPERATION, with its region lock held. */
  public static class HoldTruncate implements MasterCoprocessor, MasterObserver {
    static volatile boolean armed = false;
    static volatile CountDownLatch entered = new CountDownLatch(0);
    static volatile CountDownLatch release = new CountDownLatch(0);

    @Override
    public Optional<MasterObserver> getMasterObserver() {
      return Optional.of(this);
    }

    @Override
    public void preTruncateRegionAction(ObserverContext<MasterCoprocessorEnvironment> c,
      RegionInfo regionInfo) throws IOException {
      if (armed) {
        entered.countDown();
        try {
          release.await();
        } catch (InterruptedException e) {
          throw new IOException(e);
        }
      }
    }
  }

  private static void log(String msg) {
    String line = "[MC3] " + System.currentTimeMillis() + " " + msg + "\n";
    System.out.print(line);
    String out = System.getenv("MC3_OUT");
    if (out != null) {
      try {
        Files.write(Paths.get(out), line.getBytes(StandardCharsets.UTF_8),
          StandardOpenOption.CREATE, StandardOpenOption.APPEND);
      } catch (IOException e) {
        // the same line already went to stdout
      }
    }
  }

  @BeforeEach
  public void setUp() throws Exception {
    util = new HBaseTestingUtil();
    Configuration conf = util.getConfiguration();
    conf.set("hbase.coprocessor.master.classes", HoldTruncate.class.getName());
    // src/test/resources/hbase-site.xml lowers this to 5; use the production minimum, as several
    // truncates wait in PE workers at the same time.
    conf.setInt(MasterProcedureConstants.MASTER_PROCEDURE_THREADS, 16);
    // Otherwise a balancer run spreads its plans across the 5 minute balancer period.
    conf.setInt(HConstants.HBASE_BALANCER_MAX_BALANCING, 5_000);
    util.startMiniCluster(2);
    admin = util.getAdmin();
    tableName = TableName.valueOf("mc3");
  }

  @AfterEach
  public void tearDown() throws Exception {
    HoldTruncate.armed = false;
    HoldTruncate.release.countDown();
    Thread t = new Thread(() -> {
      try {
        util.shutdownMiniCluster();
      } catch (Exception e) {
        log("shutdown: " + e);
      }
    });
    t.setDaemon(true);
    t.start();
    t.join(90_000);
    if (t.isAlive()) {
      log("shutdownMiniCluster still running after 90s; leaving it to the forked JVM exit");
    }
  }

  private HMaster master() {
    return util.getHBaseCluster().getMaster();
  }

  private RegionStateNode node(RegionInfo ri) {
    return master().getAssignmentManager().getRegionStates().getRegionStateNode(ri);
  }

  private boolean rsHasRegion(RegionInfo ri) {
    for (JVMClusterUtil.RegionServerThread t : util.getHBaseCluster().getRegionServerThreads()) {
      if (t.getRegionServer().isOnline() && t.getRegionServer().getRegion(ri.getEncodedName()) != null) {
        return true;
      }
    }
    return false;
  }

  private String metaState(RegionInfo ri) {
    try {
      return String.valueOf(
        RegionStateStore.getRegionState(MetaTableAccessor.getRegionResult(util.getConnection(), ri), ri));
    } catch (IOException e) {
      return "meta-read-failed:" + e.getClass().getSimpleName();
    }
  }

  private List<String> liveTrsps(RegionInfo ri) {
    return master().getMasterProcedureExecutor().getProcedures().stream()
      .filter(p -> p instanceof TransitRegionStateProcedure && !p.isFinished()
        && ((TransitRegionStateProcedure) p).getRegion().equals(ri))
      .map(Procedure::toString).collect(Collectors.toList());
  }

  private String snapshot(RegionInfo ri) {
    RegionStateNode n = node(ri);
    return ri.getEncodedName() + " rsnState=" + (n == null ? "?" : n.getState()) + " rsnProc="
      + (n == null || n.getProcedure() == null ? "null" : "pid=" + n.getProcedure().getProcId())
      + " metaState=" + metaState(ri) + " onAnyRS=" + rsHasRegion(ri) + " liveTRSPs=" + liveTrsps(ri);
  }

  private boolean stranded(RegionInfo ri) {
    RegionStateNode n = node(ri);
    return n != null && n.getProcedure() == null && n.isInState(RegionState.State.CLOSING);
  }

  /** Same setup as TestRegionMove#testDisableAndMove; every table region placed on one server. */
  private List<RegionInfo> workload(int regions) throws Exception {
    Table t = util.createMultiRegionTable(tableName, F1, regions);
    util.waitUntilAllRegionsAssigned(tableName);
    for (RegionInfo ri : admin.getRegions(tableName)) {
      Put p = new Put(org.apache.hbase.thirdparty.com.google.common.primitives.Bytes
        .concat(ri.getStartKey(), Bytes.toBytes("1")));
      p.addColumn(F1, Bytes.toBytes("q1"), Bytes.toBytes("value"));
      t.put(p);
    }
    t.close();
    ServerName rs1 = util.getRSForFirstRegionInTable(tableName).getServerName();
    for (RegionInfo ri : admin.getRegions(tableName)) {
      if (!rs1.equals(node(ri).getRegionLocation())) {
        admin.move(ri.getEncodedNameAsBytes(), rs1);
      }
    }
    util.waitUntilAllRegionsAssigned(tableName);
    return admin.getRegions(tableName);
  }

  /** Counterexample states 2-25, with the balancer as the source of the move TRSP. */
  private List<RegionInfo> strandViaBalancer() throws Exception {
    List<RegionInfo> regions = workload(6);
    log("workload ready: " + regions.size() + " regions on one server");
    HoldTruncate.entered = new CountDownLatch(regions.size());
    HoldTruncate.release = new CountDownLatch(1);
    HoldTruncate.armed = true;
    List<Future<Void>> truncates = new ArrayList<>();
    for (RegionInfo ri : regions) {
      truncates.add(admin.truncateRegionAsync(ri.getRegionName()));
    }
    assertTrue(HoldTruncate.entered.await(90, TimeUnit.SECONDS), "truncates did not reach PRE_OPERATION");
    log("CE state 3: all truncates are in PRE_OPERATION holding the region lock");
    for (RegionInfo ri : regions) {
      log("  before balance: " + snapshot(ri));
    }

    admin.balancerSwitch(true, true);
    ExecutorService pool = Executors.newSingleThreadExecutor(r -> {
      Thread t = new Thread(r, "mc3-balance");
      t.setDaemon(true);
      return t;
    });
    Future<BalanceResponse> balance = pool.submit(() -> admin.balance(BalanceRequest.defaultInstance()));
    List<RegionInfo> attached = new ArrayList<>();
    long deadline = System.currentTimeMillis() + 120_000;
    while (System.currentTimeMillis() < deadline) {
      attached = regions.stream().filter(r -> node(r).getProcedure() != null).collect(Collectors.toList());
      if (balance.isDone()) {
        break;
      }
      Thread.sleep(100);
    }
    log("balance done=" + balance.isDone()
      + (balance.isDone() ? " response=" + balance.get() : ""));
    if (attached.isEmpty()) {
      throw new AssertionError("NOT_TRIGGERED: the balancer attached no TRSP to a held region");
    }
    log("CE state 5: preTransitCheck passed while truncate holds the lock; attached MOVE TRSP on "
      + attached.size() + " regions");
    List<Long> movePids = new ArrayList<>();
    for (RegionInfo ri : attached) {
      movePids.add(node(ri).getProcedure().getProcId());
      log("  attached: " + snapshot(ri));
    }

    HoldTruncate.armed = false;
    HoldTruncate.release.countDown();
    log("released truncates");
    for (Future<Void> f : truncates) {
      f.get(240, TimeUnit.SECONDS);
    }
    log("CE state 23: every truncate reported SUCCESS to the client and released its lock");

    List<RegionInfo> strandedRegions = new ArrayList<>();
    deadline = System.currentTimeMillis() + 120_000;
    while (System.currentTimeMillis() < deadline) {
      strandedRegions = attached.stream().filter(this::stranded).collect(Collectors.toList());
      if (strandedRegions.size() == attached.size()) {
        break;
      }
      Thread.sleep(200);
    }
    if (strandedRegions.isEmpty()) {
      for (RegionInfo ri : attached) {
        log("  not stranded: " + snapshot(ri));
      }
      throw new AssertionError("NOT_TRIGGERED: no attached region reached CLOSING without an owner");
    }
    log("CE state 24: " + strandedRegions.size() + "/" + attached.size()
      + " regions are CLOSING with no attached procedure. Detached move pids=" + movePids);
    return strandedRegions;
  }

  /** CE state 25. Operator requests through the public Admin API against a stranded region. */
  private void operatorRequests(RegionInfo ri) throws Exception {
    ServerName other = null;
    for (ServerName sn : admin.getRegionServers()) {
      if (!sn.equals(node(ri).getRegionLocation())) {
        other = sn;
      }
    }
    int hits = 0;
    Exception e = null;
    try {
      admin.move(ri.getEncodedNameAsBytes(), other);
    } catch (Exception ex) {
      e = ex;
    }
    hits += reportTarget("Admin.move", e);
    e = null;
    try {
      admin.assign(ri.getRegionName());
    } catch (Exception ex) {
      e = ex;
    }
    hits += reportTarget("Admin.assign", e);
    e = null;
    try {
      admin.unassign(ri.getRegionName());
    } catch (Exception ex) {
      e = ex;
    }
    hits += reportTarget("Admin.unassign", e);
    assertTrue(hits > 0, "TARGET_NOT_FIRED: no operator request threw from " + TARGET_FRAME);
  }

  private int reportTarget(String op, Exception e) {
    if (e == null) {
      log("  " + op + " returned normally");
      return 0;
    }
    boolean frame = String.valueOf(e.getMessage()).contains(TARGET_FRAME);
    boolean type = e instanceof DoNotRetryRegionException;
    log("  " + op + " threw " + e.getClass().getName() + " typeIsTarget=" + type + " frame769=" + frame);
    String msg = String.valueOf(e.getMessage());
    int cut = 0;
    for (int i = 0; i < 5 && cut >= 0; i++) {
      cut = msg.indexOf('\n', cut + 1);
    }
    log("  message: " + (cut > 0 ? msg.substring(0, cut) : msg));
    return type && frame ? 1 : 0;
  }

  private void clientIo(RegionInfo ri) throws IOException {
    Configuration c = new Configuration(util.getConfiguration());
    c.setInt(HConstants.HBASE_CLIENT_RETRIES_NUMBER, 3);
    c.setInt(HConstants.HBASE_CLIENT_OPERATION_TIMEOUT, 15_000);
    c.setInt(HConstants.HBASE_RPC_TIMEOUT_KEY, 5_000);
    try (Connection conn = ConnectionFactory.createConnection(c);
      Table t = conn.getTable(tableName)) {
      // 0x01 suffix: the row must sort inside ri even when ri has the empty start key.
      byte[] row = org.apache.hbase.thirdparty.com.google.common.primitives.Bytes
        .concat(ri.getStartKey(), new byte[] { 0x01 });
      assertTrue(ri.containsRow(row), "probe row is outside " + ri.getEncodedName());
      try {
        t.put(new Put(row).addColumn(F1, Bytes.toBytes("q1"), Bytes.toBytes("v")));
        log("  client Put on " + ri.getEncodedName() + " SUCCEEDED");
      } catch (IOException e) {
        String m = String.valueOf(e.getMessage());
        log("  client Put on " + ri.getEncodedName() + " FAILED: " + e.getClass().getSimpleName() + ": "
          + m.substring(0, Math.min(220, m.length())).replace('\n', ' '));
      }
      try {
        t.get(new Get(row));
        log("  client Get on " + ri.getEncodedName() + " SUCCEEDED");
      } catch (IOException e) {
        log("  client Get on " + ri.getEncodedName() + " FAILED: " + e.getClass().getSimpleName());
      }
    }
  }

  private void watch(List<RegionInfo> regions, long ms, String label) throws Exception {
    long start = System.currentTimeMillis();
    while (System.currentTimeMillis() - start < ms) {
      Thread.sleep(30_000);
      for (RegionInfo ri : regions) {
        log("  " + label + " t+" + (System.currentTimeMillis() - start) / 1000 + "s " + snapshot(ri));
      }
    }
  }

  /** Level 1. The counterexample: truncate + balancer move + operator request. */
  @Test
  public void testLevel1BalancerCounterexample() throws Exception {
    List<RegionInfo> stranded = strandViaBalancer();
    RegionInfo ri = stranded.get(0);
    log("state right after stranding: " + snapshot(ri));
    operatorRequests(ri);
    clientIo(ri);
    log("control: client I/O on regions the balancer did not touch");
    for (RegionInfo healthy : admin.getRegions(tableName)) {
      if (stranded.stream().noneMatch(r -> r.getEncodedName().equals(healthy.getEncodedName()))) {
        log("  healthy: " + snapshot(healthy));
        clientIo(healthy);
      }
    }
    log("watching for a mechanism that clears the state for " + PERMANENCE_MS / 1000 + "s");
    watch(stranded, PERMANENCE_MS, "stranded");
    log("after watch: " + snapshot(ri));
    assertTrue(stranded(ri), "the state resolved on its own: " + snapshot(ri));
    operatorRequests(ri);
    clientIo(ri);
    log("RESULT level1: target fired and the region stayed stranded");
  }

  /** Level 0. No hook: Admin.move and Admin.truncateRegionAsync race from two client threads. */
  @Test
  public void testLevel0PureRace() throws Exception {
    List<RegionInfo> regions = workload(12);
    ExecutorService pool = Executors.newCachedThreadPool(r -> {
      Thread t = new Thread(r, "mc3-move");
      t.setDaemon(true);
      return t;
    });
    int attempts = 0;
    int truncateErrors = 0;
    int moveErrors = 0;
    for (int round = 0; round < 4; round++) {
      for (RegionInfo ri : regions) {
        if (stranded(ri) || node(ri).getProcedure() != null || !node(ri).isInState(RegionState.State.OPEN)) {
          continue;
        }
        attempts++;
        ServerName loc = node(ri).getRegionLocation();
        ServerName dest = admin.getRegionServers().stream().filter(s -> !s.equals(loc)).findFirst().get();
        long jitterMs = attempts % 8;
        Future<?> move = pool.submit(() -> {
          admin.move(ri.getEncodedNameAsBytes(), dest);
          return null;
        });
        Thread.sleep(jitterMs);
        try {
          admin.truncateRegionAsync(ri.getRegionName()).get(180, TimeUnit.SECONDS);
        } catch (Exception e) {
          truncateErrors++;
        }
        long end = System.currentTimeMillis() + 15_000;
        while (!move.isDone() && !stranded(ri) && System.currentTimeMillis() < end) {
          Thread.sleep(100);
        }
        if (move.isDone()) {
          try {
            move.get();
          } catch (Exception e) {
            moveErrors++;
          }
        }
        if (stranded(ri)) {
          log("LEVEL0 HIT at attempt " + attempts + " jitterMs=" + jitterMs + " : " + snapshot(ri));
          operatorRequests(ri);
          clientIo(ri);
          Thread.sleep(60_000);
          log("after 60s: " + snapshot(ri));
          assertTrue(stranded(ri), "resolved on its own");
          log("RESULT level0: target fired with no timing aid");
          return;
        }
      }
    }
    log("RESULT level0: NOT triggered attempts=" + attempts + " truncateErrors=" + truncateErrors
      + " moveErrors=" + moveErrors);
  }

  /** Negative control: the hook alone, with no concurrent move, must not strand anything. */
  @Test
  public void testControlHookWithoutMove() throws Exception {
    List<RegionInfo> regions = workload(6);
    HoldTruncate.entered = new CountDownLatch(regions.size());
    HoldTruncate.release = new CountDownLatch(1);
    HoldTruncate.armed = true;
    List<Future<Void>> truncates = new ArrayList<>();
    for (RegionInfo ri : regions) {
      truncates.add(admin.truncateRegionAsync(ri.getRegionName()));
    }
    assertTrue(HoldTruncate.entered.await(90, TimeUnit.SECONDS));
    Thread.sleep(5_000);
    HoldTruncate.armed = false;
    HoldTruncate.release.countDown();
    for (Future<Void> f : truncates) {
      f.get(240, TimeUnit.SECONDS);
    }
    Thread.sleep(20_000);
    RegionInfo ri = regions.get(0);
    for (RegionInfo r : regions) {
      log("  control: " + snapshot(r));
      assertTrue(node(r).isInState(RegionState.State.OPEN) && node(r).getProcedure() == null);
    }
    ServerName loc = node(ri).getRegionLocation();
    ServerName dest = admin.getRegionServers().stream().filter(s -> !s.equals(loc)).findFirst().get();
    admin.move(ri.getEncodedNameAsBytes(), dest);
    log("  control: Admin.move after truncate succeeded: " + snapshot(ri));
    clientIo(ri);
    log("RESULT control: no stranding and no target exception without a concurrent move");
  }

  /** Does a master failover clear the state? */
  @Test
  public void testRecoveryMasterFailover() throws Exception {
    List<RegionInfo> stranded = strandViaBalancer();
    RegionInfo ri = stranded.get(0);
    Thread.sleep(10_000);
    log("before failover: " + snapshot(ri));
    SingleProcessHBaseCluster cluster = util.getHBaseCluster();
    ServerName old = master().getServerName();
    cluster.killMaster(old);
    cluster.waitForMasterToStop(old, 60_000);
    cluster.startMaster();
    assertTrue(cluster.waitForActiveAndReadyMaster(180_000));
    log("new active master " + master().getServerName());
    util.waitFor(120_000, () -> master().isInitialized());
    watch(stranded, 150_000, "post-failover");
    log("after failover: " + snapshot(ri));
    // The client registry still lists the dead master's port; point it at the new master.
    util.getConfiguration().set(HConstants.MASTER_ADDRS_KEY,
      master().getServerName().getAddress().toString());
    Exception e = null;
    try (Connection c = ConnectionFactory.createConnection(util.getConfiguration());
      Admin a = c.getAdmin()) {
      ServerName dest = a.getRegionServers().stream()
        .filter(s -> !s.equals(node(ri).getRegionLocation())).findFirst().get();
      a.move(ri.getEncodedNameAsBytes(), dest);
    } catch (Exception ex) {
      e = ex;
    }
    reportTarget("Admin.move after failover", e);
    clientIo(ri);
    log("after client calls: " + snapshot(ri));
    log("RESULT master failover: done");
  }

  /** Does a crash of the hosting server clear the state? */
  @Test
  public void testRecoveryRegionServerCrash() throws Exception {
    List<RegionInfo> stranded = strandViaBalancer();
    RegionInfo ri = stranded.get(0);
    Thread.sleep(10_000);
    ServerName host = node(ri).getRegionLocation();
    log("before RS kill: host=" + host + " " + snapshot(ri));
    util.getHBaseCluster().killRegionServer(host);
    util.getHBaseCluster().waitForRegionServerToStop(host, 60_000);
    long start = System.currentTimeMillis();
    while (System.currentTimeMillis() - start < 180_000) {
      Thread.sleep(30_000);
      log("  post-crash t+" + (System.currentTimeMillis() - start) / 1000 + "s " + snapshot(ri));
      for (Procedure<?> p : master().getMasterProcedureExecutor().getProcedures()) {
        if (p instanceof ServerCrashProcedure) {
          log("    SCP: " + p + " finished=" + p.isFinished());
        }
      }
    }
    log("after RS crash: " + snapshot(ri));
    clientIo(ri);
    for (RegionInfo r : stranded) {
      log("  stranded after crash: " + snapshot(r));
    }
    BalanceResponse br = admin.balance(BalanceRequest.defaultInstance());
    log("Admin.balance while SCP is unfinished: balancerRan=" + br.isBalancerRan()
      + " deadServersInProgress=" + master().getServerManager().areDeadServersInProgress());
    log("RESULT rs crash: done");
  }
}
