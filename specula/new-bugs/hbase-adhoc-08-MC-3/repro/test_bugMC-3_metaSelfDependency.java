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
package org.apache.hadoop.hbase.namespace;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hbase.HBaseTestingUtil;
import org.apache.hadoop.hbase.HConstants;
import org.apache.hadoop.hbase.NamespaceDescriptor;
import org.apache.hadoop.hbase.ServerName;
import org.apache.hadoop.hbase.SingleProcessHBaseCluster;
import org.apache.hadoop.hbase.SpeculaTrace;
import org.apache.hadoop.hbase.StartTestingClusterOption;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.Admin;
import org.apache.hadoop.hbase.client.ColumnFamilyDescriptor;
import org.apache.hadoop.hbase.client.ColumnFamilyDescriptorBuilder;
import org.apache.hadoop.hbase.client.RegionInfoBuilder;
import org.apache.hadoop.hbase.client.TableDescriptor;
import org.apache.hadoop.hbase.client.TableDescriptorBuilder;
import org.apache.hadoop.hbase.coprocessor.CoprocessorHost;
import org.apache.hadoop.hbase.coprocessor.RegionServerObserver;
import org.apache.hadoop.hbase.master.HMaster;
import org.apache.hadoop.hbase.master.ServerManager;
import org.apache.hadoop.hbase.master.TableNamespaceManager;
import org.apache.hadoop.hbase.master.assignment.AssignmentManager;
import org.apache.hadoop.hbase.master.assignment.RegionStateNode;
import org.apache.hadoop.hbase.quotas.QuotaUtil;
import org.apache.hadoop.hbase.regionserver.HRegionServer;
import org.apache.hadoop.hbase.rsgroup.RSGroupUtil;
import org.apache.hadoop.hbase.testclassification.LargeTests;
import org.apache.hadoop.hbase.util.Bytes;
import org.apache.hadoop.hbase.util.JVMClusterUtil.MasterThread;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * MC-3 reproduction: a variant of TestNamespaceAuditor#testTableOperations. It realizes the steps
 * of spec/output/MC_hunt_S2_meta_bfs.out: a master becomes active with meta open (BecomeActive,
 * WaitForMetaOnline), the RegionServer hosting meta crashes (RSCrash), meta's TRSP queues its
 * assignment (TrspQueueAssign), the schema service is published (InitClusterSchemaService), and the
 * assign thread plans meta (TargetCheck_Assign).
 * <p/>
 * The only timing control is the initClusterSchemaService override that TestShutdownBackupMaster
 * already uses, and it also aborts the RegionServer the same way that test does. Nothing here
 * writes the namespace cache or meta's ns rows, and ClusterSchemaServiceImpl#getNamespace is not
 * edited.
 */
@Tag(LargeTests.TAG)
public class SpeculaAdhocMC3Test {

  private static final Logger LOG = LoggerFactory.getLogger(SpeculaAdhocMC3Test.class);

  private enum Hook {
    /** Runs initClusterSchemaService untouched. */
    NONE,
    /** Aborts meta's host, and publishes the service after meta's TRSP has queued (CE order). */
    CRASH_THEN_TRSP_THEN_PUBLISH,
    /** Aborts meta's host, and publishes the service as soon as the master sees it gone. */
    CRASH_THEN_PUBLISH
  }

  private static volatile Hook hook = Hook.NONE;
  private static volatile HMaster hooked;
  private static volatile boolean probing;
  private static final List<HRegionServer> REGION_SERVERS = new CopyOnWriteArrayList<>();

  private final HBaseTestingUtil util = new HBaseTestingUtil();
  private Admin admin;
  private final String prefix = "TestNamespaceAuditor";

  public static final class RecordingRegionServer
    extends SingleProcessHBaseCluster.MiniHBaseClusterRegionServer {
    public RecordingRegionServer(Configuration conf) throws IOException, InterruptedException {
      super(conf);
      REGION_SERVERS.add(this);
    }
  }

  public static final class HookedMaster extends HMaster {
    public HookedMaster(Configuration conf) throws IOException {
      super(conf);
    }

    @Override
    protected void initClusterSchemaService() throws IOException, InterruptedException {
      Hook mode = hook;
      if (mode != Hook.NONE) {
        hook = Hook.NONE;
        hooked = this;
        // The CE has a second RegionServer (r2) that meta can move to.
        while (getServerManager().getOnlineServersList().size() < 2) {
          Thread.sleep(50);
        }
        AssignmentManager am = getAssignmentManager();
        ServerName metaHost = am.getRegionStates()
          .getRegionServerOfRegion(RegionInfoBuilder.FIRST_META_REGIONINFO);
        LOG.info("MC3-STEP WaitForMetaOnline passed on {}, meta on {}", getServerName(), metaHost);
        startProbe(this);
        for (HRegionServer rs : REGION_SERVERS) {
          if (rs.getServerName().equals(metaHost)) {
            LOG.info("MC3-STEP RSCrash {}", metaHost);
            SpeculaTrace.emit("RSCrash", SpeculaTrace.rsName(metaHost), "{}", "{}");
            rs.abort("MC-3: crash the RegionServer hosting meta");
          }
        }
        RegionStateNode node =
          am.getRegionStates().getRegionStateNode(RegionInfoBuilder.FIRST_META_REGIONINFO);
        long deadline = System.currentTimeMillis() + 120000;
        while (System.currentTimeMillis() < deadline) {
          // TRSP#queueAssign moves the procedure to the OPEN state right after it queues the region.
          boolean ready = mode == Hook.CRASH_THEN_TRSP_THEN_PUBLISH
            ? String.valueOf(node.getProcedure()).contains("REGION_STATE_TRANSITION_OPEN")
            : !getServerManager().isServerOnline(metaHost);
          if (ready) {
            break;
          }
          Thread.sleep(5);
        }
        LOG.info("MC3-STEP publishing the schema service; meta TRSP={}, state={}",
          node.getProcedure(), node.getState());
      }
      super.initClusterSchemaService();
    }
  }

  /** Reads only: logs what a client of this master would see while the cache load runs. */
  private static void startProbe(HMaster master) {
    Thread probe = new Thread(() -> {
      long start = System.currentTimeMillis();
      while (probing && !master.isInitialized()) {
        RegionStateNode node = master.getAssignmentManager().getRegionStates()
          .getRegionStateNode(RegionInfoBuilder.FIRST_META_REGIONINFO);
        boolean published = master.getClusterSchema() != null;
        boolean cached = false;
        try {
          cached =
            published && master.getClusterSchema().getTableNamespaceManager().doesNamespaceExist(
              NamespaceDescriptor.SYSTEM_NAMESPACE_NAME_STR);
        } catch (IOException | RuntimeException e) {
          LOG.info("MC3-PROBE read failed", e);
        }
        LOG.info(
          "MC3-PROBE t={}ms published={} hbaseNsCached={} metaState={} metaLocation={} "
            + "onlineServers={} initialized={} aborted={} stopped={}",
          System.currentTimeMillis() - start, published, cached, node.getState(),
          node.getRegionLocation(), master.getServerManager().getOnlineServersList().size(),
          master.isInitialized(), master.isAborted(), master.isStopped());
        if (master.isStopped() || master.isAborted()) {
          return;
        }
        try {
          Thread.sleep(2000);
        } catch (InterruptedException e) {
          return;
        }
      }
    }, "MC3-Probe");
    probe.setDaemon(true);
    probe.start();
  }

  @BeforeEach
  public void reset() {
    hook = Hook.NONE;
    hooked = null;
    probing = true;
    REGION_SERVERS.clear();
  }

  @AfterEach
  public void tearDown() throws Exception {
    probing = false;
    SpeculaTrace.close();
    util.shutdownMiniCluster();
  }

  /** TNA:107-121, with two RegionServers (the CE has r1 and r2) and the hook classes. */
  private StartTestingClusterOption configure(int masters, boolean rsgroup) {
    Configuration conf = util.getConfiguration();
    conf.set(CoprocessorHost.REGION_COPROCESSOR_CONF_KEY,
      TestNamespaceAuditor.CustomObserver.class.getName());
    conf.setStrings(CoprocessorHost.MASTER_COPROCESSOR_CONF_KEY,
      TestNamespaceAuditor.MasterSyncObserver.class.getName(),
      TestNamespaceAuditor.CPMasterObserver.class.getName());
    conf.setBoolean(QuotaUtil.QUOTA_CONF_KEY, true);
    conf.setClass("hbase.coprocessor.regionserver.classes",
      TestNamespaceAuditor.CPRegionServerObserver.class, RegionServerObserver.class);
    // HBaseTestingUtil would otherwise wait for every RegionServer, so no later master could start
    // with one crashed. One is what ServerManager uses by default.
    conf.setInt(ServerManager.WAIT_ON_REGIONSERVERS_MINTOSTART, 1);
    if (rsgroup) {
      RSGroupUtil.enableRSGroup(conf);
    }
    LOG.info("MC3-CONFIG masters={} rsgroup={} clientRetries={} dispatchWaitMs={}", masters,
      rsgroup, conf.getInt(HConstants.HBASE_CLIENT_RETRIES_NUMBER, -1),
      conf.getInt(AssignmentManager.ASSIGN_DISPATCH_WAIT_MSEC_CONF_KEY, 150));
    return StartTestingClusterOption.builder().numMasters(masters).numRegionServers(2)
      .masterClass(HookedMaster.class).rsClass(RecordingRegionServer.class).build();
  }

  /** TNA:145-184 as written. */
  private void readAndCreateTables(String nsp) throws IOException {
    NamespaceDescriptor nspDesc =
      NamespaceDescriptor.create(nsp).addConfiguration(TableNamespaceManager.KEY_MAX_REGIONS, "5")
        .addConfiguration(TableNamespaceManager.KEY_MAX_TABLES, "2").build();
    admin.createNamespace(nspDesc);
    assertNotNull(admin.getNamespaceDescriptor(nsp), "Namespace descriptor found null.");
    assertEquals(3, admin.listNamespaceDescriptors().length);
    ColumnFamilyDescriptor fam =
      ColumnFamilyDescriptorBuilder.newBuilder(Bytes.toBytes("fam1")).build();
    TableDescriptor one = TableDescriptorBuilder
      .newBuilder(TableName.valueOf(nsp + TableName.NAMESPACE_DELIM + "table1"))
      .setColumnFamily(fam).build();
    TableDescriptor two = TableDescriptorBuilder
      .newBuilder(TableName.valueOf(nsp + TableName.NAMESPACE_DELIM + "table2"))
      .setColumnFamily(fam).build();
    admin.createTable(one);
    admin.createTable(two, Bytes.toBytes("AAA"), Bytes.toBytes("ZZZ"), 4);
  }

  private HMaster otherMaster(SingleProcessHBaseCluster cluster, HMaster active) {
    for (MasterThread t : cluster.getMasterThreads()) {
      if (t.getMaster() != active) {
        return t.getMaster();
      }
    }
    throw new AssertionError("no backup master");
  }

  /**
   * Runs the workload, hands the active role to the backup through a clean stop (not a fault, and
   * the CE counts no master crash), and returns the backup, which is now the CE's m1.
   */
  private HMaster workloadThenHandover(Hook mode) throws Exception {
    util.startMiniCluster(configure(2, RSGroupUtil.isRSGroupEnabled(util.getConfiguration())));
    TestNamespaceAuditor.waitForQuotaInitialize(util);
    util.waitTableAvailable(QuotaUtil.QUOTA_TABLE_NAME, 120000);
    admin = util.getAdmin();
    readAndCreateTables(prefix + "_np2");
    util.waitUntilNoRegionsInTransition(120000);
    SingleProcessHBaseCluster cluster = util.getHBaseCluster();
    HMaster first = cluster.getMaster();
    HMaster backup = otherMaster(cluster, first);
    hook = mode;
    LOG.info("MC3-STEP stopping the active master {} cleanly; backup is {}", first.getServerName(),
      backup.getServerName());
    first.stop("MC-3: hand the active role to the backup");
    return backup;
  }

  private void waitUntilDoneOrDead(HMaster master, long millis) throws Exception {
    util.waitFor(millis, 500, () -> master.isInitialized() || master.isAborted()
      || master.isStopped());
    LOG.info("MC3-RESULT master={} initialized={} aborted={} stopped={}", master.getServerName(),
      master.isInitialized(), master.isAborted(), master.isStopped());
  }

  /**
   * Level 1, CE order. Expected on a correct system: the backup finishes initializing. Actual: the
   * assign thread throws from CSSI:111, meta is not assigned, and the master aborts.
   */
  @Test
  public void testLevel1CeOrderTakeover() throws Exception {
    // Keeps meta's plan after the publish, whatever the WAL split takes. Timing only.
    util.getConfiguration().setInt(AssignmentManager.ASSIGN_DISPATCH_WAIT_MSEC_CONF_KEY, 3000);
    RSGroupUtil.enableRSGroup(util.getConfiguration());
    HMaster master = workloadThenHandover(Hook.CRASH_THEN_TRSP_THEN_PUBLISH);
    waitUntilDoneOrDead(master, 400000);
    assertTrue(hooked == master, "the hook did not run on the backup");
    assertFalse(master.isInitialized(), "the master survived the crash");
    assertTrue(master.isAborted(), "the master was not aborted");
    recoverWithFreshMaster();
  }

  /** Same as above with the default dispatch wait, and without waiting for meta's TRSP. */
  @Test
  public void testLevel1DefaultDispatchTakeover() throws Exception {
    RSGroupUtil.enableRSGroup(util.getConfiguration());
    HMaster master = workloadThenHandover(Hook.CRASH_THEN_PUBLISH);
    waitUntilDoneOrDead(master, 400000);
    assertTrue(hooked == master, "the hook did not run on the backup");
    assertFalse(master.isInitialized(), "the master survived the crash");
    assertTrue(master.isAborted(), "the master was not aborted");
    recoverWithFreshMaster();
  }

  /** After the abort nothing is left to assign meta until an operator starts another master. */
  private void recoverWithFreshMaster() throws Exception {
    SingleProcessHBaseCluster cluster = util.getHBaseCluster();
    util.waitFor(120000, 500, () -> cluster.getLiveMasterThreads().isEmpty());
    LOG.info("MC3-RESULT no live master thread is left; live RegionServers={}",
      cluster.getLiveRegionServerThreads().size());
    hook = Hook.NONE;
    long start = System.currentTimeMillis();
    cluster.startMaster();
    assertTrue(cluster.waitForActiveAndReadyMaster(300000), "fresh master did not initialize");
    util.invalidateConnection();
    admin = util.getAdmin();
    NamespaceDescriptor[] namespaces = admin.listNamespaceDescriptors();
    LOG.info("MC3-RESULT fresh master initialized in {}ms, namespaces={}",
      System.currentTimeMillis() - start, namespaces.length);
    assertEquals(3, namespaces.length, "the namespace rows must be durable");
    assertNotNull(admin.getNamespaceDescriptor(NamespaceDescriptor.SYSTEM_NAMESPACE_NAME_STR));
  }

  /**
   * Level 1, one master and a first boot: no stop of any master, the only event is the RegionServer
   * crash. JVMClusterUtil#startup cannot return, so startMiniCluster fails when its wait expires.
   */
  @Test
  public void testLevel1FirstBootSingleMaster() throws Exception {
    util.getConfiguration().setInt("hbase.master.init.timeout.localHBaseCluster", 240000);
    hook = Hook.CRASH_THEN_TRSP_THEN_PUBLISH;
    util.getConfiguration().setInt(AssignmentManager.ASSIGN_DISPATCH_WAIT_MSEC_CONF_KEY, 3000);
    boolean started = true;
    try {
      util.startMiniCluster(configure(1, true));
    } catch (IOException | RuntimeException e) {
      started = false;
      LOG.info("MC3-RESULT startMiniCluster failed: {}", e.toString());
    }
    HMaster master = hooked;
    assertNotNull(master, "the hook did not run");
    LOG.info("MC3-RESULT first boot: started={} initialized={} aborted={}", started,
      master.isInitialized(), master.isAborted());
    assertFalse(started, "the cluster came up");
    assertTrue(master.isAborted(), "the master was not aborted");
  }

  /** Control: the same schedule with rsgroup off (DisabledRSGroupInfoManager returns early). */
  @Test
  public void testControlRsGroupOff() throws Exception {
    util.getConfiguration().setInt(AssignmentManager.ASSIGN_DISPATCH_WAIT_MSEC_CONF_KEY, 3000);
    HMaster master = workloadThenHandover(Hook.CRASH_THEN_TRSP_THEN_PUBLISH);
    waitUntilDoneOrDead(master, 400000);
    assertTrue(hooked == master, "the hook did not run on the backup");
    assertTrue(master.isInitialized(), "rsgroup off must initialize");
    assertFalse(master.isAborted(), "rsgroup off must not abort");
    assertEquals(3, util.getAdmin().listNamespaceDescriptors().length);
  }

  /** Level 0: no hook; the crash races the backup's startup from a plain test thread. */
  @Test
  public void testLevel0NoHookRace() throws Exception {
    RSGroupUtil.enableRSGroup(util.getConfiguration());
    HMaster master = workloadThenHandover(Hook.NONE);
    util.waitFor(120000, 1, () -> master.getClusterSchema() != null || master.isStopped());
    ServerName metaHost = master.getAssignmentManager().getRegionStates()
      .getRegionServerOfRegion(RegionInfoBuilder.FIRST_META_REGIONINFO);
    boolean cachedAtCrash = master.getClusterSchema().getTableNamespaceManager()
      .doesNamespaceExist(NamespaceDescriptor.SYSTEM_NAMESPACE_NAME_STR);
    LOG.info("MC3-STEP L0 crash of {} right after the publish was seen; hbaseNsCached={}", metaHost,
      cachedAtCrash);
    for (HRegionServer rs : REGION_SERVERS) {
      if (rs.getServerName().equals(metaHost)) {
        rs.abort("MC-3 L0");
      }
    }
    waitUntilDoneOrDead(master, 400000);
  }
}
