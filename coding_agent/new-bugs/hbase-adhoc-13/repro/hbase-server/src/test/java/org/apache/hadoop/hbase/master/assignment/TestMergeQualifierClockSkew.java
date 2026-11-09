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

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import java.util.List;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hbase.HBaseTestingUtil;
import org.apache.hadoop.hbase.HConstants;
import org.apache.hadoop.hbase.MetaTableAccessor;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.Admin;
import org.apache.hadoop.hbase.client.RegionInfo;
import org.apache.hadoop.hbase.client.Result;
import org.apache.hadoop.hbase.client.TableDescriptor;
import org.apache.hadoop.hbase.master.procedure.MasterProcedureConstants;
import org.apache.hadoop.hbase.master.procedure.MasterProcedureEnv;
import org.apache.hadoop.hbase.procedure2.Procedure;
import org.apache.hadoop.hbase.procedure2.ProcedureExecutor;
import org.apache.hadoop.hbase.procedure2.ProcedureTestingUtility;
import org.apache.hadoop.hbase.testclassification.LargeTests;
import org.apache.hadoop.hbase.testclassification.MasterTests;
import org.apache.hadoop.hbase.util.EnvironmentEdge;
import org.apache.hadoop.hbase.util.EnvironmentEdgeManager;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Same set-up as {@link TestAdhocWorkload13}, but the master host's clock runs a few seconds ahead
 * of the clock of the RegionServer hosting hbase:meta (a skew well below the 10 s warning / 30 s
 * rejection thresholds of ServerManager). The skew is simulated in the single mini-cluster JVM by an
 * EnvironmentEdge that subtracts the skew for the RegionServer's RPC handler threads, i.e. for the
 * code that assigns server-side timestamps to mutations of hbase:meta.
 * <p>
 * The merge writes the merged region's info:merge* qualifiers with the master timestamp. The
 * catalog janitor finds no references in the merged region and runs
 * GCMultipleMergedRegionsProcedure, which archives the parents and "deletes" the merge qualifiers
 * with a Delete whose timestamp is assigned by the meta RegionServer's (earlier) clock. The delete
 * marker therefore does not cover the qualifiers, the GC procedure finishes successfully, the
 * parents are gone, yet the merged region still has merge qualifiers and the next merge of it is
 * rejected by the check in prepareMergeRegion.
 */
@Tag(MasterTests.TAG)
@Tag(LargeTests.TAG)
public class TestMergeQualifierClockSkew {

  private static final Logger LOG = LoggerFactory.getLogger(TestMergeQualifierClockSkew.class);

  private static final HBaseTestingUtil UTIL = new HBaseTestingUtil();

  /** Master clock ahead of the meta RegionServer clock by this many ms. */
  private static final long SKEW_MS = 5000;

  private static Admin admin;

  /**
   * Simulates the clock of the RegionServer host (which hosts hbase:meta) running SKEW_MS behind the
   * clock of the master host: the RegionServer's RPC handler threads, which assign the server-side
   * timestamps of the mutations they apply, see the earlier time.
   */
  private static final class RegionServerBehindEdge implements EnvironmentEdge {
    private final String rsPortTag;

    RegionServerBehindEdge(int rsPort) {
      this.rsPortTag = "port=" + rsPort;
    }

    @Override
    public long currentTime() {
      long now = System.currentTimeMillis();
      String name = Thread.currentThread().getName();
      if (name.startsWith("RpcServer.") && name.endsWith(rsPortTag)) {
        return now - SKEW_MS;
      }
      return now;
    }
  }

  private static void setupConf(Configuration conf) {
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
    admin.balancerSwitch(false, true);
    // The janitor is run explicitly below (as an operator / the periodic chore would).
    UTIL.getHBaseCluster().getMaster().setCatalogJanitorEnabled(false);
  }

  @AfterEach
  public void tearDown() throws Exception {
    EnvironmentEdgeManager.reset();
    for (TableDescriptor htd : admin.listTableDescriptors()) {
      UTIL.deleteTable(htd.getTableName());
    }
  }

  @Test
  public void testMergeAfterGcWithMasterClockAhead() throws Exception {
    final TableName tableName = TableName.valueOf("testMergeAfterGcWithMasterClockAhead");
    UTIL.createTable(tableName, new byte[][] { HConstants.CATALOG_FAMILY }, new byte[][] {
      new byte[] { 'b' }, new byte[] { 'c' }, new byte[] { 'd' }, new byte[] { 'e' } });
    List<RegionInfo> ris = MetaTableAccessor.getTableRegions(UTIL.getConnection(), tableName);
    final ProcedureExecutor<MasterProcedureEnv> procExec =
      UTIL.getHBaseCluster().getMaster().getMasterProcedureExecutor();
    RegionStateStore rss = UTIL.getHBaseCluster().getMaster().getAssignmentManager()
      .getRegionStateStore();

    // Master host clock is SKEW_MS ahead of the meta RegionServer host clock.
    int rsPort =
      UTIL.getHBaseCluster().getRegionServer(0).getRpcServer().getListenerAddress().getPort();
    assertTrue(UTIL.getHBaseCluster().getRegionServer(0).getRegions(TableName.META_TABLE_NAME)
      .size() == 1, "meta expected on the single RegionServer");
    EnvironmentEdgeManager.injectEdge(new RegionServerBehindEdge(rsPort));

    // 1. merge regions 0 and 1
    MergeTableRegionsProcedure first = new MergeTableRegionsProcedure(procExec.getEnvironment(),
      new RegionInfo[] { ris.get(0), ris.get(1) }, true);
    long firstId = procExec.submitProcedure(first);
    ProcedureTestingUtility.waitProcedure(procExec, firstId);
    ProcedureTestingUtility.assertProcNotFailed(procExec, firstId);
    RegionInfo merged = first.getMergedRegion();
    assertTrue(rss.hasMergeRegions(merged));

    // 2. catalog janitor: merged region has no references -> GCMultipleMergedRegionsProcedure
    assertTrue(UTIL.getHBaseCluster().getMaster().getCatalogJanitor().scan() > 0);
    // wait for the GC to finish: parents archived and removed from hbase:meta
    UTIL.waitFor(30000, () -> procExec.getProcedures().stream()
      .anyMatch(p -> p instanceof GCMultipleMergedRegionsProcedure && p.isSuccess())
      && MetaTableAccessor.getRegionResult(UTIL.getConnection(), ris.get(0)).isEmpty()
      && MetaTableAccessor.getRegionResult(UTIL.getConnection(), ris.get(1)).isEmpty());
    for (Procedure<?> p : procExec.getProcedures()) {
      if (p instanceof GCMultipleMergedRegionsProcedure) {
        LOG.info("GC procedure {} finished, success={}", p, p.isSuccess());
        assertTrue(p.isSuccess());
      }
    }
    assertTrue(MetaTableAccessor.getRegionResult(UTIL.getConnection(), ris.get(0)).isEmpty());
    Result mergedRow = MetaTableAccessor.getRegionResult(UTIL.getConnection(), merged);
    LOG.info("Merged region row after successful GC: {}", mergedRow);
    // The GC "deleted" the merge qualifiers, but they are still there.
    assertTrue(rss.hasMergeRegions(merged),
      "merge qualifiers expected to survive the GC delete because of the clock skew");

    // 3. merge the merged region with its neighbour -> rejected by the ad hoc check
    MergeTableRegionsProcedure second = new MergeTableRegionsProcedure(procExec.getEnvironment(),
      new RegionInfo[] { merged, ris.get(2) }, true);
    long secondId = procExec.submitProcedure(second);
    ProcedureTestingUtility.waitProcedure(procExec, secondId);
    Procedure<?> result = procExec.getResult(secondId);
    assertTrue(result.isFailed(), "second merge expected to fail");
    Throwable cause = result.getException().unwrapRemoteException();
    LOG.error("Second merge failed although the merged region's parents were already GC'd", cause);
    cause.printStackTrace(System.out);
    assertTrue(cause instanceof org.apache.hadoop.hbase.exceptions.MergeRegionException,
      "unexpected " + cause);
    assertFalse(MetaTableAccessor.getRegionResult(UTIL.getConnection(), merged).isEmpty());
    fail("Merge of " + merged.getShortNameToLog() + " rejected: " + cause);
  }
}
