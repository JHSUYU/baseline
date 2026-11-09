/*
 * MC-3 reproduction: a variant of TestRetainAssignmentOnRestart#testForceRetainAssignment (same parent
 * class, same cluster setup and configuration, except rsClass and no HMasterForTest, whose
 * "exactly NUM_OF_RS destinations" gate cannot hold once the predecessor stays online).
 * Copied by test_bugMC-3_late_register.sh to
 * hbase-server/src/test/java/org/apache/hadoop/hbase/master/TestSpeculaMC3LateRegister.java
 *
 * Counterexample: spec/output/MC_hunt_s3_late_register.out. SCP and master timing are NOT controlled
 * beyond aborting the master as soon as it has recorded the predecessor as dead.
 */
package org.apache.hadoop.hbase.master;

import static org.apache.hadoop.hbase.master.assignment.AssignmentManager.FORCE_REGION_RETAINMENT;
import static org.apache.hadoop.hbase.master.assignment.AssignmentManager.FORCE_REGION_RETAINMENT_WAIT_INTERVAL;
import static org.apache.hadoop.hbase.master.procedure.ServerCrashProcedure.MASTER_SCP_RETAIN_ASSIGNMENT;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.Collection;
import java.util.List;
import java.util.concurrent.TimeUnit;
import org.apache.hadoop.hbase.HConstants;
import org.apache.hadoop.hbase.ServerName;
import org.apache.hadoop.hbase.SingleProcessHBaseCluster;
import org.apache.hadoop.hbase.StartTestingClusterOption;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.RegionInfo;
import org.apache.hadoop.hbase.master.procedure.ServerCrashProcedure;
import org.apache.hadoop.hbase.regionserver.HRegionServer;
import org.apache.hadoop.hbase.regionserver.SpeculaMC3RegionServer;
import org.apache.hadoop.hbase.testclassification.MasterTests;
import org.apache.hadoop.hbase.testclassification.LargeTests;
import org.apache.hadoop.hbase.zookeeper.ZKUtil;
import org.apache.hadoop.hbase.zookeeper.ZKWatcher;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

@Tag(MasterTests.TAG)
@Tag(LargeTests.TAG)
public class TestSpeculaMC3LateRegister extends AbstractTestRestartCluster {

  private static final Logger LOG = LoggerFactory.getLogger(TestSpeculaMC3LateRegister.class);

  private static final int NUM_OF_RS = 3;
  private static final String FAIL_FAST = "hbase.master.rs.remote.proc.fail.fast.limit";

  private ServerName p;
  private ServerName s;
  private RegionInfo r1;
  private RegionInfo r2;
  private long t0;
  private long crashAt;

  @Override
  protected boolean splitWALCoordinatedByZk() {
    String v = System.getenv("MC3_SPLIT_BY_ZK");
    return v == null || Boolean.parseBoolean(v);
  }

  /** Never leave the predecessor's exit parked: the mini cluster could not shut down. */
  @AfterEach
  public void releasePredecessor() {
    SpeculaMC3RegionServer.release.countDown();
  }

  private void mark(String fmt, Object... args) {
    LOG.info("MC3|t+" + (System.currentTimeMillis() - t0) + "ms " + fmt, args);
  }

  private void setupCluster() throws Exception {
    // same setup as TestRetainAssignmentOnRestart#testForceRetainAssignment
    UTIL.getConfiguration().setBoolean(FORCE_REGION_RETAINMENT, true);
    UTIL.getConfiguration().setLong(FORCE_REGION_RETAINMENT_WAIT_INTERVAL, 50);
    UTIL.getConfiguration().set(HConstants.CLIENT_CONNECTION_REGISTRY_IMPL_CONF_KEY,
      HConstants.ZK_CONNECTION_REGISTRY_CLASS);
    UTIL.getConfiguration().setBoolean(MASTER_SCP_RETAIN_ASSIGNMENT, true);
    // unset: the real default of 10. The counterexample's config scales it to 2.
    String limit = System.getenv("MC3_FAIL_FAST_LIMIT");
    if (limit != null) {
      UTIL.getConfiguration().setInt(FAIL_FAST, Integer.parseInt(limit));
    }
    UTIL.startMiniCluster(StartTestingClusterOption.builder()
      .rsClass(SpeculaMC3RegionServer.class).numRegionServers(NUM_OF_RS).build());
    UTIL.getMiniHBaseCluster().getMaster().getMasterRpcServices().synchronousBalanceSwitch(false);
    for (TableName table : TABLES) {
      UTIL.createTable(table, FAMILY);
    }
    for (TableName table : TABLES) {
      UTIL.waitTableEnabled(table);
    }
    UTIL.waitUntilNoRegionsInTransition(60000);
  }

  /** Predecessor: holds a user region, no hbase:meta, so SCP's carryingMeta path stays out. */
  private void pick() throws Exception {
    SingleProcessHBaseCluster cluster = UTIL.getHBaseCluster();
    int metaIdx = cluster.getServerWithMeta();
    for (int i = 0; i < NUM_OF_RS && p == null; i++) {
      HRegionServer rs = cluster.getRegionServer(i);
      if (i == metaIdx) {
        continue;
      }
      List<RegionInfo> regions = UTIL.getAdmin().getRegions(rs.getServerName());
      regions.removeIf(RegionInfo::isMetaRegion);
      if (!regions.isEmpty()) {
        p = rs.getServerName();
        r1 = regions.get(0);
      }
    }
    if (p == null) {
      // setup only, before any fault: placement can put every user region on the meta server
      RegionInfo ri = UTIL.getAdmin().getRegions(TABLES[0]).get(0);
      HRegionServer rs = cluster.getRegionServer((metaIdx + 1) % NUM_OF_RS);
      UTIL.getAdmin().move(ri.getEncodedNameAsBytes(), rs.getServerName());
      UTIL.waitUntilNoRegionsInTransition(60000);
      p = rs.getServerName();
      r1 = ri;
    }
    for (TableName table : TABLES) {
      for (RegionInfo ri : UTIL.getAdmin().getRegions(table)) {
        if (!ri.equals(r1) && !p.equals(location(ri))) {
          r2 = ri;
        }
      }
    }
    mark("PICK predecessor={} r1={} r2={}", p, r1.getEncodedName(),
      r2 == null ? null : r2.getEncodedName());
  }

  private ServerName location(RegionInfo ri) {
    return UTIL.getHBaseCluster().getMaster().getAssignmentManager().getRegionStates()
      .getRegionServerOfRegion(ri);
  }

  private ServerName destination() {
    SingleProcessHBaseCluster cluster = UTIL.getHBaseCluster();
    for (int i = 0; i < NUM_OF_RS; i++) {
      ServerName sn = cluster.getRegionServer(i).getServerName();
      if (!sn.equals(p)) {
        return sn;
      }
    }
    throw new IllegalStateException();
  }

  private boolean znodeExists(ServerName sn) throws Exception {
    ZKWatcher zkw = UTIL.getZooKeeperWatcher();
    return ZKUtil.checkExists(zkw, zkw.getZNodePaths().getRsPath(sn)) != -1;
  }

  private void state(String label, HMaster m) throws Exception {
    ServerManager sm = m.getServerManager();
    mark("STATE[{}] initialized={} P.online={} P.dead={} P.znode={} S={} S.online={} online={}",
      label, m.isInitialized(), sm.isServerOnline(p), sm.getDeadServers().isDeadServer(p),
      znodeExists(p), s, s == null ? null : sm.isServerOnline(s), sm.getOnlineServersList());
  }

  /** States 2-19 of the counterexample. Returns the new active master. */
  private HMaster crashAndFailOver(boolean holdZnode) throws Exception {
    t0 = System.currentTimeMillis();
    setupCluster();
    pick();
    SingleProcessHBaseCluster cluster = UTIL.getHBaseCluster();
    HMaster oldMaster = cluster.getMaster();
    SpeculaMC3RegionServer.reset(p, holdZnode);

    // states 2-6: admin.move, TRSP close, close RRP dispatched, call on the wire
    ServerName dest = destination();
    mark("CLIENT_MOVE {} -> {}", r1.getEncodedName(), dest);
    Thread mover = new Thread(() -> {
      try {
        UTIL.getAdmin().move(r1.getEncodedNameAsBytes(), dest);
        mark("CLIENT_MOVE returned");
      } catch (Exception e) {
        mark("CLIENT_MOVE failed: {}", e.toString());
      }
    }, "MC3-move");
    mover.setDaemon(true);
    mover.start();

    // state 7: the predecessor crashes with the close on the wire
    assertTrue(SpeculaMC3RegionServer.crashed.await(60, TimeUnit.SECONDS), "close never reached P");
    assertTrue(SpeculaMC3RegionServer.portClosed.await(60, TimeUnit.SECONDS), "P port never closed");
    crashAt = System.currentTimeMillis();
    mark("P crashed, port closed; P.znode={}", znodeExists(p));

    // states 8-13: the dispatcher retries, then fail-fast expires the predecessor and submits SCP
    long deadline = System.currentTimeMillis() + 180_000;
    while (
      !oldMaster.getServerManager().getDeadServers().isDeadServer(p)
        && System.currentTimeMillis() < deadline
    ) {
      Thread.sleep(5);
    }
    assertTrue(oldMaster.getServerManager().getDeadServers().isDeadServer(p), "P never expired");
    // The dead list is written before the SCP is stored. The counterexample's master crash comes
    // after SCP is pending (state 13), so wait until the executor has it: submitProcedure stores a
    // procedure before it publishes it in getProcedures().
    deadline = System.currentTimeMillis() + 60_000;
    boolean scpStored = false;
    while (!scpStored && System.currentTimeMillis() < deadline) {
      scpStored = oldMaster.getMasterProcedureExecutor().getProcedures().stream()
        .anyMatch(pr -> pr instanceof ServerCrashProcedure
          && p.equals(((ServerCrashProcedure) pr).getServerName()));
      if (!scpStored) {
        Thread.sleep(1);
      }
    }
    assertTrue(scpStored, "SCP for P never stored");
    mark("P_EXPIRED by old master, SCP stored, {}ms after the crash; P.online={} P.znode={}",
      System.currentTimeMillis() - crashAt, oldMaster.getServerManager().isServerOnline(p),
      znodeExists(p));

    // state 15: master failover, with the predecessor's SCP pending
    cluster.abortMaster(0);
    cluster.waitOnMaster(0);
    mark("OLD_MASTER_DOWN {}ms after the crash", System.currentTimeMillis() - crashAt);

    // states 14, 16: same-port successor. It can only register with the new master.
    cluster.getConf().setInt(HConstants.REGIONSERVER_PORT, p.getPort());
    Thread successor = new Thread(() -> {
      try {
        s = cluster.startRegionServer().getRegionServer().getServerName();
        mark("SUCCESSOR_ONLINE {}", s);
      } catch (Exception e) {
        mark("SUCCESSOR failed: {}", e.toString());
      }
    }, "MC3-successor");
    successor.setDaemon(true);
    successor.start();

    // states 17-18: new master. upgrade() records P online from ZK and dead from the SCP.
    // HBaseTestingUtil pins min and max to-start to the RS count, so a master that reads three
    // servers from ZK would not wait at all. Use HBase's real defaults (ServerManager.java:871-891):
    // min 1, max unlimited, timeout 4500ms, which is the window for registering before `initialized`.
    cluster.getConf().setInt(ServerManager.WAIT_ON_REGIONSERVERS_MINTOSTART, 1);
    cluster.getConf().setInt(ServerManager.WAIT_ON_REGIONSERVERS_MAXTOSTART, Integer.MAX_VALUE);
    Thread newMaster = new Thread(() -> {
      try {
        cluster.startMaster();
      } catch (Exception e) {
        mark("NEW_MASTER failed: {}", e.toString());
      }
    }, "MC3-new-master");
    newMaster.setDaemon(true);
    newMaster.start();

    HMaster m = null;
    deadline = System.currentTimeMillis() + 120_000;
    while (System.currentTimeMillis() < deadline) {
      m = cluster.getMaster();
      if (m != null && m != oldMaster && m.isActiveMaster() && m.getServerManager() != null) {
        break;
      }
      m = null;
      Thread.sleep(20);
    }
    assertTrue(m != null, "no new active master");
    mark("NEW_MASTER_ACTIVE {} , {}ms after the crash", m.getServerName(),
      System.currentTimeMillis() - crashAt);
    return m;
  }

  /**
   * The finding's state: after the successor registered, before `initialized`, the predecessor is
   * online and dead (expireServer returned early, ServerManager.java:675-678). Once the master is
   * initialized, the successor's next report clears the dead entry (cleanPreviousInstance), so this
   * state must be sampled here and not at the fire.
   */
  private void awaitOnlineAndDeadBeforeInitialized(HMaster m) throws Exception {
    ServerManager sm = m.getServerManager();
    long deadline = System.currentTimeMillis() + 60_000;
    ServerName successor = null;
    while (successor == null && System.currentTimeMillis() < deadline && !m.isInitialized()) {
      for (ServerName sn : sm.getOnlineServersList()) {
        if (ServerName.isSameAddress(sn, p) && sn.getStartcode() != p.getStartcode()) {
          successor = sn;
        }
      }
      if (successor == null) {
        Thread.sleep(1);
      }
    }
    boolean online = sm.isServerOnline(p);
    boolean dead = sm.getDeadServers().isDeadServer(p);
    boolean initialized = m.isInitialized();
    mark("STATE[REGISTERED] successor={} initialized={} P.online={} P.dead={} P.znode={}", successor,
      initialized, online, dead, znodeExists(p));
    assertTrue(successor != null, "successor did not register before initialized");
    assertTrue(online && dead && !initialized, "P is not online and dead before initialized");
  }

  /** The session of a real kill -9 expires hbase's default 90s after the crash. */
  private void expireSession() {
    long elapsed = System.currentTimeMillis() - crashAt;
    mark("SESSION_EXPIRY {}ms after the crash (zookeeper.session.timeout default: 90000ms)", elapsed);
    assertTrue(elapsed < 90_000, "the scenario must fit inside the ZK session, took " + elapsed);
    SpeculaMC3RegionServer.release.countDown();
  }

  /** The public way to stop a cluster: stop-hbase.sh and Admin#shutdown. Returns if it completed. */
  private boolean adminShutdownCompletes(HMaster m, long waitMs) throws Exception {
    mark("ADMIN_SHUTDOWN requested; onlineServers={}", m.getServerManager().getOnlineServersList());
    try {
      UTIL.getAdmin().shutdown();
    } catch (Exception e) {
      mark("ADMIN_SHUTDOWN call: {}", e.toString());
    }
    long start = System.currentTimeMillis();
    while (!m.isStopped() && System.currentTimeMillis() - start < waitMs) {
      Thread.sleep(100);
    }
    SingleProcessHBaseCluster cluster = UTIL.getHBaseCluster();
    mark("ADMIN_SHUTDOWN after {}ms: master.isStopped={} onlineServers={} liveRSThreads={}",
      System.currentTimeMillis() - start, m.isStopped(), m.getServerManager().getOnlineServersList(),
      cluster.getLiveRegionServerThreads().size());
    return m.isStopped();
  }

  private void assertFiredAtTarget() {
    String fire = SpeculaMC3RegionServer.FIRES.get(0);
    LOG.info("MC3|FIRST_FIRE_STACK {}", fire);
    assertTrue(fire.contains("org.apache.hbase.thirdparty.com.google.protobuf.ServiceException"),
      fire);
    // The target statement is the multi-line throw at RSRpcServices.java:1878-1881. javac attributes
    // ServiceException.<init> (bytecode 48) to the line of its last argument: LineNumberTable has
    // 1878: 18, 1880: 34. So a throw from the target always shows frame 1880.
    assertTrue(fire.contains("RSRpcServices.throwOnWrongStartCode(RSRpcServices.java:1880)"), fire);
  }

  private void awaitNoRit(HMaster m, String label) throws Exception {
    long start = System.currentTimeMillis();
    try {
      UTIL.waitUntilNoRegionsInTransition(180000);
      mark("NO_RIT[{}] after {}ms; r1 on {}", label, System.currentTimeMillis() - start,
        m.getAssignmentManager().getRegionStates().getRegionServerOfRegion(r1));
    } catch (Throwable t) {
      mark("RIT_STUCK[{}] after {}ms: {}", label, System.currentTimeMillis() - start, t.toString());
    }
  }

  /**
   * Level 0: the codebase's plain simulated kill, whose exit path deletes the znode at once. The new
   * master does not read the predecessor from ZK, so the counterexample's precondition is absent.
   */
  @Test
  public void level0PlainKill() throws Exception {
    HMaster m = crashAndFailOver(false);
    boolean fired = SpeculaMC3RegionServer.fired.await(45, TimeUnit.SECONDS);
    state("L0_end", m);
    mark("RESULT_L0 fired={} fires={}", fired, SpeculaMC3RegionServer.FIRES.size());
    assertEquals(0, SpeculaMC3RegionServer.FIRES.size(), "L0 is not expected to fire");
  }

  /**
   * Level 1, session outlives the master's initialization: the znode lingers past the fire, then the
   * ZK session expires after the successor has reported to an initialized master.
   */
  @Test
  public void level1SessionExpiresLate() throws Exception {
    HMaster m = crashAndFailOver(true);
    awaitOnlineAndDeadBeforeInitialized(m);
    assertTrue(SpeculaMC3RegionServer.fired.await(180, TimeUnit.SECONDS), "target did not fire");
    state("AT_FIRE", m);
    assertFiredAtTarget();
    assertTrue(m.getServerManager().isServerOnline(p), "P should be online at the fire");

    awaitNoRit(m, "late");
    long deadline = System.currentTimeMillis() + 120_000;
    while (!m.isInitialized() && System.currentTimeMillis() < deadline) {
      Thread.sleep(100);
    }
    Thread.sleep(10_000); // a few successor heartbeats to the initialized master
    state("BEFORE_SESSION_EXPIRY", m);
    expireSession();
    deadline = System.currentTimeMillis() + 60_000;
    while (m.getServerManager().isServerOnline(p) && System.currentTimeMillis() < deadline) {
      Thread.sleep(100);
    }
    state("AFTER_SESSION_EXPIRY", m);
    boolean retired = !m.getServerManager().isServerOnline(p);
    mark("RESULT_LATE fires={} P_retired={} r1_on={}", SpeculaMC3RegionServer.FIRES.size(), retired,
      m.getAssignmentManager().getRegionStates().getRegionServerOfRegion(r1));
    // negative control for the hang in level1SessionExpiresEarly: P retired, shutdown completes
    boolean completes = adminShutdownCompletes(m, 90_000);
    mark("RESULT_LATE_SHUTDOWN completes={}", completes);
    assertTrue(retired, "P should retire when its session expires after the dead entry is cleared");
    assertTrue(completes, "Admin#shutdown should complete");
  }

  /**
   * Level 1, session expires while the predecessor is still in the dead list, before `initialized`:
   * expireServer returns early once more and nothing is left to retire it. Then look at the
   * predecessor through the public Admin API, and move a region to it through the public Admin API.
   */
  @Test
  public void level1SessionExpiresEarly() throws Exception {
    HMaster m = crashAndFailOver(true);
    awaitOnlineAndDeadBeforeInitialized(m);
    expireSession();
    long deadline = System.currentTimeMillis() + 30_000;
    while (znodeExists(p) && System.currentTimeMillis() < deadline) {
      Thread.sleep(5);
    }
    state("SESSION_EXPIRED", m);
    assertTrue(SpeculaMC3RegionServer.fired.await(180, TimeUnit.SECONDS), "target did not fire");
    state("AT_FIRE", m);
    assertFiredAtTarget();

    awaitNoRit(m, "early");
    deadline = System.currentTimeMillis() + 120_000;
    while (!m.isInitialized() && System.currentTimeMillis() < deadline) {
      Thread.sleep(100);
    }
    Thread.sleep(30_000); // SCP done, several successor heartbeats, nothing else to wait for
    state("SETTLED", m);
    Collection<ServerName> live = UTIL.getAdmin().getRegionServers();
    boolean ghost = live.contains(p);
    mark("ADMIN_getRegionServers {} containsPredecessor={}", live, ghost);

    int before = SpeculaMC3RegionServer.FIRES.size();
    if (ghost && r2 != null) {
      mark("CLIENT_MOVE_TO_PREDECESSOR {} -> {}", r2.getEncodedName(), p);
      long start = System.currentTimeMillis();
      try {
        UTIL.getAdmin().move(r2.getEncodedNameAsBytes(), p);
        mark("CLIENT_MOVE_TO_PREDECESSOR returned after {}ms", System.currentTimeMillis() - start);
      } catch (Exception e) {
        mark("CLIENT_MOVE_TO_PREDECESSOR failed after {}ms: {}", System.currentTimeMillis() - start,
          e.toString());
      }
      awaitNoRit(m, "moveToP");
      mark("r2 now on {}", m.getAssignmentManager().getRegionStates().getRegionServerOfRegion(r2));
    }
    state("END", m);
    boolean retired = !m.getServerManager().isServerOnline(p);
    mark("RESULT_EARLY fires={} firesFromMoveToP={} P_retired={}",
      SpeculaMC3RegionServer.FIRES.size(), SpeculaMC3RegionServer.FIRES.size() - before, retired);
    boolean completes = adminShutdownCompletes(m, 180_000);
    List<ServerName> left = m.getServerManager().getOnlineServersList();
    mark("RESULT_EARLY_SHUTDOWN completes={} onlineServersLeft={} predecessorIsTheOnlyOneLeft={}",
      completes, left, left.size() == 1 && left.contains(p));
    if (!completes) {
      // nothing else will ever stop this master, and tearDown would wait on it forever
      m.stop("MC-3 test cleanup: Admin#shutdown did not complete");
    }
    assertTrue(ghost, "Admin#getRegionServers should still list the crashed predecessor");
    assertTrue(!retired, "P should never retire");
    assertTrue(!completes, "Admin#shutdown should hang on the predecessor");
  }
}
