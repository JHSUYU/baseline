/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.apache.hadoop.hbase.quotas;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import java.io.IOException;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Proxy;
import java.util.Collections;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hbase.HBaseTestingUtil;
import org.apache.hadoop.hbase.HConstants;
import org.apache.hadoop.hbase.ServerName;
import org.apache.hadoop.hbase.SingleProcessHBaseCluster;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.TableNotEnabledException;
import org.apache.hadoop.hbase.client.Admin;
import org.apache.hadoop.hbase.client.ColumnFamilyDescriptorBuilder;
import org.apache.hadoop.hbase.client.Connection;
import org.apache.hadoop.hbase.client.ConnectionFactory;
import org.apache.hadoop.hbase.client.TableDescriptorBuilder;
import org.apache.hadoop.hbase.coprocessor.CoprocessorHost;
import org.apache.hadoop.hbase.coprocessor.MasterCoprocessor;
import org.apache.hadoop.hbase.coprocessor.MasterCoprocessorEnvironment;
import org.apache.hadoop.hbase.coprocessor.MasterObserver;
import org.apache.hadoop.hbase.coprocessor.ObserverContext;
import org.apache.hadoop.hbase.master.HMaster;
import org.apache.hadoop.hbase.master.procedure.FlushTableProcedure;
import org.apache.hadoop.hbase.master.procedure.MasterProcedureEnv;
import org.apache.hadoop.hbase.procedure2.Procedure;
import org.apache.hadoop.hbase.quotas.SpaceQuotaSnapshot.SpaceQuotaStatus;
import org.apache.hadoop.hbase.testclassification.MediumTests;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInfo;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * MC-3 reproduction, a variant of TestAdhocWorkload04: same cluster, same table, same observer in
 * the test JVM, same two runs and same flush. The only fault is one active-master kill through
 * SingleProcessHBaseCluster.killMaster. Nothing here writes the table state or edits the check.
 */
@Tag(MediumTests.TAG)
public class SpeculaAdhoc04MC3Test {
  private static final Logger LOG = LoggerFactory.getLogger(SpeculaAdhoc04MC3Test.class);
  private static final TableName TABLE = TableName.valueOf("adhoc_workload_04");
  private static final String TARGET_FILE = "AbstractStateMachineTableProcedure.java";
  private static final int TARGET_LINE = 163;

  private HBaseTestingUtil util;
  private volatile int masterPort;

  /** Holds the enable where a test asks: after submission, or in its first locked step. */
  public static class EnableHoldHook implements MasterCoprocessor, MasterObserver {
    static volatile CountDownLatch reached = new CountDownLatch(0);
    static volatile CountDownLatch release = new CountDownLatch(0);
    static volatile boolean atSubmit = false;

    @Override
    public Optional<MasterObserver> getMasterObserver() {
      return Optional.of(this);
    }

    @Override
    public void preEnableTableAction(ObserverContext<MasterCoprocessorEnvironment> ctx,
      TableName tableName) {
      if (!atSubmit) {
        hold(tableName);
      }
    }

    @Override
    public void postEnableTable(ObserverContext<MasterCoprocessorEnvironment> ctx,
      TableName tableName) throws IOException {
      if (atSubmit && hold(tableName)) {
        // The response of this call is lost, as it would be on a real crash.
        throw new IOException("master killed before answering the enable");
      }
    }

    private static boolean hold(TableName tableName) {
      CountDownLatch r = reached;
      if (!TABLE.equals(tableName) || r.getCount() == 0) {
        return false;
      }
      r.countDown();
      try {
        release.await(120, TimeUnit.SECONDS);
      } catch (InterruptedException e) {
        Thread.currentThread().interrupt();
      }
      return true;
    }
  }

  @BeforeEach
  public void setUp(TestInfo info) throws Exception {
    util = new HBaseTestingUtil();
    Configuration conf = util.getConfiguration();
    conf.setBoolean(QuotaUtil.QUOTA_CONF_KEY, true);
    if (info.getDisplayName().startsWith("prodShape")) {
      // The master's own observer does the work, on the period the codebase's quota tests use.
      SpaceQuotaHelperForTests.updateConfigForQuotas(conf);
    } else {
      conf.setInt(QuotaObserverChore.QUOTA_OBSERVER_CHORE_DELAY_KEY, 3_600_000);
      conf.setInt(QuotaObserverChore.QUOTA_OBSERVER_CHORE_PERIOD_KEY, 3_600_000);
    }
    conf.set(CoprocessorHost.MASTER_COPROCESSOR_CONF_KEY, EnableHoldHook.class.getName());
    util.startMiniCluster(1);
    util.waitFor(30000,
      () -> util.getMiniHBaseCluster().getMaster().getMasterQuotaManager().isQuotaInitialized());
  }

  @AfterEach
  public void tearDown() throws Exception {
    EnableHoldHook.release.countDown();
    util.shutdownMiniCluster();
  }

  private void evidence(String fmt, Object... args) {
    LOG.info("MC3-EVIDENCE " + fmt, args);
  }

  private void killActiveMaster() throws IOException {
    SingleProcessHBaseCluster cluster = util.getMiniHBaseCluster();
    ServerName sn = cluster.getMaster().getServerName();
    masterPort = sn.getPort();
    evidence("killing active master {}", sn);
    cluster.killMaster(sn);
    cluster.waitForMasterToStop(sn, 120_000);
    evidence("master {} is down", sn);
  }

  private void startNewMaster() throws Exception {
    // Same port as the dead master, as a real restart: the clients' registry lists that address.
    SingleProcessHBaseCluster cluster = util.getMiniHBaseCluster();
    cluster.getConfiguration().setInt(HConstants.MASTER_PORT, masterPort);
    cluster.startMaster();
    assertTrue(cluster.waitForActiveAndReadyMaster(120_000));
    evidence("new active master {} initialized", cluster.getMaster().getServerName());
  }

  /** A Connection whose getAdmin() first runs crash; updateTableQuota calls it just to enable. */
  private static Connection crashOnEnable(Connection real, Runnable crash, AtomicInteger calls) {
    return (Connection) Proxy.newProxyInstance(Connection.class.getClassLoader(),
      new Class<?>[] { Connection.class }, (p, method, args) -> {
        if ("getAdmin".equals(method.getName()) && calls.getAndIncrement() == 0) {
          crash.run();
        }
        try {
          return method.invoke(real, args);
        } catch (InvocationTargetException e) {
          throw e.getCause();
        }
      });
  }

  private static SpaceQuotaSnapshot observance() {
    return new SpaceQuotaSnapshot(SpaceQuotaStatus.notInViolation(), 2048L, 4096L);
  }

  private static QuotaObserverChore newObserver(Connection conn, Connection notifierConn,
    Configuration conf, HMaster master) throws IOException {
    TableSpaceQuotaSnapshotNotifier notifier = new TableSpaceQuotaSnapshotNotifier();
    notifier.initialize(notifierConn);
    QuotaObserverChore observer =
      new QuotaObserverChore(conn, conf, notifier, master.getMasterQuotaManager(), master, null);
    observer.initializeSnapshotStores(Collections.emptyMap());
    observer.setTableQuotaSnapshot(TABLE,
      new SpaceQuotaSnapshot(new SpaceQuotaStatus(SpaceViolationPolicy.DISABLE), 2048L, 1024L));
    return observer;
  }

  private void createAndDisable(Admin admin) throws IOException {
    admin.createTable(TableDescriptorBuilder.newBuilder(TABLE)
      .setColumnFamily(ColumnFamilyDescriptorBuilder.of("f")).build());
    admin.disableTable(TABLE);
  }

  /** The two observer runs of the workload; returns how many of them threw. */
  private int observerRuns(QuotaObserverChore observer) {
    int failed = 0;
    for (int run = 0; run < 2; run++) {
      SpaceQuotaSnapshot before = observer.getTableQuotaSnapshot(TABLE);
      try {
        observer.updateTableQuota(TABLE, before, observance());
        evidence("observer run {}: returned normally; current={} equalsTarget={}", run, before,
          before.equals(observance()));
      } catch (IOException e) {
        failed++;
        evidence("observer run {}: FAILED with {}: {} (next run retries, per the workload)", run,
          e.getClass().getName(), e.getMessage());
      }
    }
    return failed;
  }

  /** Asserts the flush failed at the target line, from the procedure's own recorded exception. */
  private void assertFlushFailedAtTarget(Exception thrown) throws IOException {
    assertNotNull(thrown, "admin.flush succeeded; the target did not fire");
    Throwable t = thrown;
    while (t != null && !(t instanceof TableNotEnabledException)) {
      t = t.getCause();
    }
    assertNotNull(t, "flush failed with something else: " + thrown);
    evidence("client admin.flush threw {}: {}", thrown.getClass().getName(), thrown.getMessage());

    HMaster master = util.getMiniHBaseCluster().getMaster();
    Procedure<MasterProcedureEnv> flush = null;
    for (Procedure<MasterProcedureEnv> p : master.getMasterProcedureExecutor().getProcedures()) {
      if (p instanceof FlushTableProcedure && p.isFailed()) {
        flush = p;
      }
    }
    assertNotNull(flush, "no failed FlushTableProcedure on the active master");
    Throwable root = flush.getException().getCause();
    assertTrue(root instanceof TableNotEnabledException, "root=" + root);
    evidence("server procedure {} failed with {}", flush, root.toString());
    boolean atTarget = false;
    for (StackTraceElement e : root.getStackTrace()) {
      evidence("  server frame: {}", e);
      if (
        TARGET_FILE.equals(e.getFileName()) && e.getLineNumber() == TARGET_LINE
          && "preflightChecks".equals(e.getMethodName())
      ) {
        atTarget = true;
      }
    }
    assertTrue(atTarget, "exception was not thrown from " + TARGET_FILE + ":" + TARGET_LINE);
    evidence("TARGET FIRED: TableNotEnabledException thrown at {}:{}", TARGET_FILE, TARGET_LINE);
  }

  /** No fault: the original workload order must reach ENABLED and flush successfully. */
  @Test
  public void control_noCrash() throws Exception {
    Admin admin = util.getAdmin();
    createAndDisable(admin);
    Configuration observerConf = new Configuration(util.getConfiguration());
    observerConf.setInt(HConstants.HBASE_CLIENT_RETRIES_NUMBER, 0);
    HMaster master = util.getMiniHBaseCluster().getMaster();
    try (Connection conn = ConnectionFactory.createConnection(observerConf)) {
      assertEquals(0, observerRuns(newObserver(conn, conn, observerConf, master)));
    }
    assertTrue(admin.isTableEnabled(TABLE));
    admin.flush(TABLE);
    evidence("control: table enabled and flush succeeded");
  }

  /**
   * Level 0, cold connection: a kill before the observer's run 0, no hook of any kind. The observer
   * has no hbase:quota location yet, so both puts fail and its map keeps the violation: a later run
   * would retry. It reaches L163, but it is not the counterexample's mechanism.
   */
  @Test
  public void level0_coldConnection_killBeforeObserverRun() throws Exception {
    Admin admin = util.getAdmin();
    createAndDisable(admin);
    Configuration observerConf = new Configuration(util.getConfiguration());
    observerConf.setInt(HConstants.HBASE_CLIENT_RETRIES_NUMBER, 0);
    HMaster master = util.getMiniHBaseCluster().getMaster();
    Exception flushFailure = null;
    try (Connection conn = ConnectionFactory.createConnection(observerConf)) {
      QuotaObserverChore observer = newObserver(conn, conn, observerConf, master);
      killActiveMaster();
      int failed = observerRuns(observer);
      evidence("level0: observer runs that failed = {}", failed);
    }
    startNewMaster();
    try {
      admin.flush(TABLE);
    } catch (IOException e) {
      flushFailure = e;
    }
    evidence("level0: table disabled = {}", admin.isTableDisabled(TABLE));
    assertFlushFailedAtTarget(flushFailure);
  }

  /**
   * Level 0, warm connection: as above, except the observer's connection already knows where
   * hbase:quota is, as any connection that has used it does. The put reaches the region server,
   * the map moves to observance, and the enable has no master to go to. No hook of any kind.
   */
  @Test
  public void level0_warmConnection_killBeforeObserverRun() throws Exception {
    Admin admin = util.getAdmin();
    createAndDisable(admin);
    Configuration observerConf = new Configuration(util.getConfiguration());
    observerConf.setInt(HConstants.HBASE_CLIENT_RETRIES_NUMBER, 0);
    HMaster master = util.getMiniHBaseCluster().getMaster();
    Exception flushFailure = null;
    try (Connection conn = ConnectionFactory.createConnection(observerConf)) {
      conn.getRegionLocator(QuotaTableUtil.QUOTA_TABLE_NAME).getAllRegionLocations();
      QuotaObserverChore observer = newObserver(conn, conn, observerConf, master);
      killActiveMaster();
      assertEquals(1, observerRuns(observer), "run 0 fails at the enable, run 1 is a no-op");
      assertEquals(observance(), observer.getTableQuotaSnapshot(TABLE));
    }
    startNewMaster();
    try {
      admin.flush(TABLE);
    } catch (IOException e) {
      flushFailure = e;
    }
    assertFlushFailedAtTarget(flushFailure);
    assertTrue(admin.isTableDisabled(TABLE));
    evidence("level0-warm: table still DISABLED after the flush failed");
  }

  /**
   * Level 1, the counterexample's order. Steps 15-16 (put, map update) happen first; step 17 is the
   * kill, taken at the observer's call for an Admin, just before step 18's enable; step 19 is the
   * failed attempt; steps 20-21 the no-op run; step 23 the flush sent while the master is down;
   * steps 24-25 the next master; steps 26-29 the flush procedure.
   */
  @Test
  public void level1_counterexampleOrder() throws Exception {
    Admin admin = util.getAdmin();
    createAndDisable(admin);
    Configuration observerConf = new Configuration(util.getConfiguration());
    observerConf.setInt(HConstants.HBASE_CLIENT_RETRIES_NUMBER, 0);
    HMaster master = util.getMiniHBaseCluster().getMaster();
    AtomicInteger adminCalls = new AtomicInteger();
    try (Connection real = ConnectionFactory.createConnection(observerConf)) {
      Connection conn = crashOnEnable(real, () -> {
        try {
          killActiveMaster();
        } catch (IOException e) {
          throw new IllegalStateException(e);
        }
      }, adminCalls);
      QuotaObserverChore observer = newObserver(conn, real, observerConf, master);
      int failed = observerRuns(observer);
      assertEquals(1, failed, "run 0 must fail on the dead master, run 1 must be a no-op");
      assertEquals(1, adminCalls.get(), "run 1 must not attempt the enable again");
      assertEquals(observance(), observer.getTableQuotaSnapshot(TABLE));
      evidence("after both runs: observer map={} enableAttempts={}",
        observer.getTableQuotaSnapshot(TABLE), adminCalls.get());
    }

    CompletableFuture<Void> flush = new CompletableFuture<>();
    Thread flusher = new Thread(() -> {
      try {
        admin.flush(TABLE);
        flush.complete(null);
      } catch (Throwable e) {
        flush.completeExceptionally(e);
      }
    }, "mc3-flush");
    flusher.start();
    Thread.sleep(2000);
    assertFalse(flush.isDone(), "the flush must still be retrying while the master is down");
    evidence("flush outstanding while the master is down");
    startNewMaster();

    Exception flushFailure = null;
    try {
      flush.get(300, TimeUnit.SECONDS);
    } catch (ExecutionException e) {
      flushFailure = (Exception) e.getCause();
    }
    assertFlushFailedAtTarget(flushFailure);

    // Permanence: nothing has re-issued the enable, and the observer will not.
    assertTrue(admin.isTableDisabled(TABLE));
    evidence("table DISABLED on the new master: {}", admin.isTableDisabled(TABLE));
    Thread.sleep(30_000);
    assertTrue(admin.isTableDisabled(TABLE));
    try {
      admin.flush(TABLE);
      fail("second flush must fail too");
    } catch (TableNotEnabledException e) {
      evidence("30s later: table still DISABLED, second flush throws {}", e.getClass().getName());
    }
    // Control: the failure is only the lost enable; an operator's enable heals it.
    admin.enableTable(TABLE);
    admin.flush(TABLE);
    evidence("manual admin.enableTable, then flush succeeded");
  }

  private Thread killAtHook(CountDownLatch reached, CountDownLatch release, String where) {
    Thread killer = new Thread(() -> {
      try {
        reached.await();
        evidence("E reached the hold point: {}", where);
        SingleProcessHBaseCluster cluster = util.getMiniHBaseCluster();
        ServerName sn = cluster.getMaster().getServerName();
        masterPort = sn.getPort();
        cluster.killMaster(sn);
        Thread.sleep(1000);
        release.countDown();
        cluster.waitForMasterToStop(sn, 120_000);
        evidence("master {} is down", sn);
        startNewMaster();
      } catch (Exception e) {
        LOG.error("kill failed", e);
        release.countDown();
      }
    }, "mc3-killer");
    killer.start();
    return killer;
  }

  private void enableCrash(boolean atSubmit, String where) throws Exception {
    Admin admin = util.getAdmin();
    createAndDisable(admin);
    Configuration observerConf = new Configuration(util.getConfiguration());
    observerConf.setInt(HConstants.HBASE_CLIENT_RETRIES_NUMBER, 0);
    HMaster master = util.getMiniHBaseCluster().getMaster();
    EnableHoldHook.atSubmit = atSubmit;
    EnableHoldHook.release = new CountDownLatch(1);
    EnableHoldHook.reached = new CountDownLatch(1);
    Thread killer = killAtHook(EnableHoldHook.reached, EnableHoldHook.release, where);
    try (Connection conn = ConnectionFactory.createConnection(observerConf)) {
      int failed = observerRuns(newObserver(conn, conn, observerConf, master));
      evidence("{}: observer runs that failed = {}", where, failed);
    }
    admin.flush(TABLE);
    evidence("{}: flush succeeded; table enabled = {}", where, admin.isTableEnabled(TABLE));
    killer.join();
    assertTrue(admin.isTableEnabled(TABLE));
  }

  /** Branch 3: E's lock is persisted when the master dies; it is restored and blocks F. */
  @Test
  public void branch3_enableLockPersisted() throws Exception {
    enableCrash(false, "E in its first action step, lock persisted");
  }

  /** E is stored and its answer is lost, so the observer gives up while E survives. */
  @Test
  public void branch2_enableStoredResponseLost() throws Exception {
    enableCrash(true, "E submitted, response not sent");
  }

  private TableName prodShapeDisabledByQuota(SpaceQuotaHelperForTests helper, Admin admin)
    throws Exception {
    TableName tn = helper.writeUntilViolation(SpaceViolationPolicy.DISABLE);
    util.waitFor(120_000, 1000, () -> admin.isTableDisabled(tn));
    evidence("prodShape: the master's observer disabled {} for its quota violation", tn);
    return tn;
  }

  private static void raiseLimit(Admin admin, TableName tn) throws IOException {
    admin.setQuota(QuotaSettingsFactory.limitTableSpace(tn,
      100L * SpaceQuotaHelperForTests.ONE_MEGABYTE, SpaceViolationPolicy.DISABLE));
  }

  /** Control: without a crash, the master's own observer re-enables after the limit is raised. */
  @Test
  public void prodShape_control_noCrash() throws Exception {
    Admin admin = util.getAdmin();
    SpaceQuotaHelperForTests helper =
      new SpaceQuotaHelperForTests(util, () -> "mc3ctl", new AtomicLong());
    TableName tn = prodShapeDisabledByQuota(helper, admin);
    raiseLimit(admin, tn);
    util.waitFor(120_000, 1000, () -> admin.isTableEnabled(tn));
    evidence("prodShape control: limit raised, the observer enabled {}", tn);
    admin.flush(tn);
    evidence("prodShape control: flush succeeded");
  }

  /** The observer lives in the master here: does a next master ever re-issue the enable? */
  @Test
  public void prodShape_masterRestart() throws Exception {
    Admin admin = util.getAdmin();
    SpaceQuotaHelperForTests helper =
      new SpaceQuotaHelperForTests(util, () -> "mc3prod", new AtomicLong());
    TableName tn = prodShapeDisabledByQuota(helper, admin);
    killActiveMaster();
    startNewMaster();
    raiseLimit(admin, tn);
    Thread.sleep(45_000);
    evidence("prodShape: 45s after raising the limit on the new master: disabled={} row={}",
      admin.isTableDisabled(tn),
      QuotaTableUtil.getCurrentSnapshotFromQuotaTable(util.getConnection(), tn));
    assertTrue(admin.isTableDisabled(tn), "the new master's observer re-enabled the table");
    Exception flushFailure = null;
    try {
      admin.flush(tn);
    } catch (IOException e) {
      flushFailure = e;
    }
    assertFlushFailedAtTarget(flushFailure);
    try {
      admin.enableTable(tn);
      evidence("prodShape: manual admin.enableTable succeeded");
    } catch (IOException e) {
      evidence("prodShape: manual admin.enableTable threw {}: {}", e.getClass().getName(),
        e.getMessage());
    }
    evidence("prodShape: finally disabled={}", admin.isTableDisabled(tn));
  }
}
