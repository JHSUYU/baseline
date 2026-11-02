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
package org.apache.hadoop.hbase.master.assignment;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hbase.HBaseTestingUtil;
import org.apache.hadoop.hbase.HConstants;
import org.apache.hadoop.hbase.MetaTableAccessor;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.Admin;
import org.apache.hadoop.hbase.client.RegionInfo;
import org.apache.hadoop.hbase.client.TableDescriptor;
import org.apache.hadoop.hbase.master.procedure.MasterProcedureConstants;
import org.apache.hadoop.hbase.master.procedure.MasterProcedureEnv;
import org.apache.hadoop.hbase.master.procedure.MasterProcedureTestingUtility;
import org.apache.hadoop.hbase.procedure2.ProcedureExecutor;
import org.apache.hadoop.hbase.procedure2.ProcedureTestingUtility;
import org.apache.hadoop.hbase.testclassification.LargeTests;
import org.apache.hadoop.hbase.testclassification.MasterTests;
import org.apache.hadoop.hbase.util.Threads;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInfo;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Region merges under the cluster set-up of {@link TestMergeTableRegionsProcedure}. Two regions of
 * a five-region table are merged; the table is disabled and enabled; the catalog janitor's scan is
 * run once on the test thread; after 3 s the merged region is merged with its neighbour.
 */
@Tag(MasterTests.TAG)
@Tag(LargeTests.TAG)
public class TestAdhocWorkload13 {

  private static final Logger LOG = LoggerFactory.getLogger(TestAdhocWorkload13.class);
  private String testMethodName;

  private static final HBaseTestingUtil UTIL = new HBaseTestingUtil();

  private static Admin admin;

  private static void setupConf(Configuration conf) {
    // Reduce the maximum attempts to speed up the test
    conf.setInt("hbase.assignment.maximum.attempts", 3);
    conf.setInt("hbase.master.maximum.ping.server.attempts", 3);
    conf.setInt("hbase.master.ping.server.retry.sleep.interval", 1);
    conf.setInt(MasterProcedureConstants.MASTER_PROCEDURE_THREADS, 1);
    conf.set("hbase.coprocessor.region.classes",
      RegionServerHostingReplicaSlowOpenCoprocessor.class.getName());
  }

  @BeforeAll
  public static void setupCluster() throws Exception {
    setupConf(UTIL.getConfiguration());
    UTIL.startMiniCluster(1);
    admin = UTIL.getAdmin();
  }

  @AfterAll
  public static void cleanupTest() throws Exception {
    UTIL.shutdownMiniCluster();
  }

  @BeforeEach
  public void setup() throws Exception {
    resetProcExecutorTestingKillFlag();
    MasterProcedureTestingUtility.generateNonceGroup(UTIL.getHBaseCluster().getMaster());
    MasterProcedureTestingUtility.generateNonce(UTIL.getHBaseCluster().getMaster());
    // Turn off balancer so it doesn't cut in and mess up our placements.
    admin.balancerSwitch(false, true);
    // Turn off the meta scanner so it don't remove parent on us.
    UTIL.getHBaseCluster().getMaster().setCatalogJanitorEnabled(false);
    resetProcExecutorTestingKillFlag();
  }

  @BeforeEach
  public void setTestMethod(TestInfo testInfo) {
    testMethodName = testInfo.getTestMethod().get().getName();
  }

  @AfterEach
  public void tearDown() throws Exception {
    resetProcExecutorTestingKillFlag();
    for (TableDescriptor htd : admin.listTableDescriptors()) {
      LOG.info("Tear down, remove table=" + htd.getTableName());
      UTIL.deleteTable(htd.getTableName());
    }
  }

  private void resetProcExecutorTestingKillFlag() {
    final ProcedureExecutor<MasterProcedureEnv> procExec = getMasterProcedureExecutor();
    ProcedureTestingUtility.setKillAndToggleBeforeStoreUpdate(procExec, false);
    assertTrue(procExec.isRunning(), "expected executor to be running");
  }

  @Test
  public void run() throws Exception {
    final TableName tableName = TableName.valueOf(testMethodName);
    UTIL.createTable(tableName, new byte[][] { HConstants.CATALOG_FAMILY }, new byte[][] {
      new byte[] { 'b' }, new byte[] { 'c' }, new byte[] { 'd' }, new byte[] { 'e' } });
    List<RegionInfo> ris = MetaTableAccessor.getTableRegions(UTIL.getConnection(), tableName);
    final ProcedureExecutor<MasterProcedureEnv> procExec = getMasterProcedureExecutor();
    MergeTableRegionsProcedure first = new MergeTableRegionsProcedure(procExec.getEnvironment(),
      new RegionInfo[] { ris.get(0), ris.get(1) }, true);
    long firstId = procExec.submitProcedure(first);
    ProcedureTestingUtility.waitProcedure(procExec, firstId);
    ProcedureTestingUtility.assertProcNotFailed(procExec, firstId);
    admin.disableTable(tableName);
    admin.enableTable(tableName);
    RegionInfo merged = first.getMergedRegion();
    UTIL.getHBaseCluster().getMaster().getCatalogJanitor().scan();
    Threads.sleep(3000);
    MergeTableRegionsProcedure second = new MergeTableRegionsProcedure(procExec.getEnvironment(),
      new RegionInfo[] { merged, ris.get(2) }, true);
    long secondId = procExec.submitProcedure(second);
    ProcedureTestingUtility.waitProcedure(procExec, secondId);
    ProcedureTestingUtility.assertProcNotFailed(procExec, secondId);
    assertEquals(ris.size() - 2,
      MetaTableAccessor.getTableRegions(UTIL.getConnection(), tableName).size());
  }

  private ProcedureExecutor<MasterProcedureEnv> getMasterProcedureExecutor() {
    return UTIL.getHBaseCluster().getMaster().getMasterProcedureExecutor();
  }
}
