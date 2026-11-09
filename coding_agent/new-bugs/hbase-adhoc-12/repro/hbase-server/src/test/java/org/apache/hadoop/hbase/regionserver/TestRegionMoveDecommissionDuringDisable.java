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
package org.apache.hadoop.hbase.regionserver;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.util.Collections;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hbase.DoNotRetryIOException;
import org.apache.hadoop.hbase.HBaseTestingUtil;
import org.apache.hadoop.hbase.ServerName;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.Admin;
import org.apache.hadoop.hbase.client.ColumnFamilyDescriptorBuilder;
import org.apache.hadoop.hbase.client.RegionInfo;
import org.apache.hadoop.hbase.client.TableDescriptor;
import org.apache.hadoop.hbase.client.TableDescriptorBuilder;
import org.apache.hadoop.hbase.client.TableState;
import org.apache.hadoop.hbase.coprocessor.CoprocessorHost;
import org.apache.hadoop.hbase.coprocessor.MasterCoprocessor;
import org.apache.hadoop.hbase.coprocessor.MasterCoprocessorEnvironment;
import org.apache.hadoop.hbase.coprocessor.MasterObserver;
import org.apache.hadoop.hbase.coprocessor.ObserverContext;
import org.apache.hadoop.hbase.master.HMaster;
import org.apache.hadoop.hbase.master.RegionState;
import org.apache.hadoop.hbase.master.assignment.RegionStateNode;
import org.apache.hadoop.hbase.procedure2.ProcedureUtil;
import org.apache.hadoop.hbase.testclassification.MediumTests;
import org.apache.hadoop.hbase.util.Bytes;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * A region move that was accepted while the table was still ENABLED races with a disableTable.
 * The disable flips the table to DISABLING while some regions of the table are still OPEN and have
 * no procedure attached. A concurrent decommissionRegionServers(offload=true) then picks those
 * regions as regular regions to drain and AssignmentManager.preTransitCheck rejects the move with
 * DoNotRetryIOException("... is disabled for ..."), aborting the whole offload.
 */
@Tag(MediumTests.TAG)
public class TestRegionMoveDecommissionDuringDisable {

  private static final Logger LOG =
    LoggerFactory.getLogger(TestRegionMoveDecommissionDuringDisable.class);

  private static final HBaseTestingUtil TEST_UTIL = new HBaseTestingUtil();
  private static final TableName TABLE = TableName.valueOf("testDecommissionDuringDisable");
  private static final byte[] CF = Bytes.toBytes("f1");

  // master side: hold the DisableTableProcedure in its PRE_OPERATION step
  static volatile boolean blockDisable = false;
  static final CountDownLatch DISABLE_ENTERED = new CountDownLatch(1);
  static final CountDownLatch DISABLE_RELEASE = new CountDownLatch(1);

  public static class BlockingMasterObserver implements MasterCoprocessor, MasterObserver {
    @Override
    public Optional<MasterObserver> getMasterObserver() {
      return Optional.of(this);
    }

    @Override
    public void preDisableTableAction(ObserverContext<MasterCoprocessorEnvironment> ctx,
      TableName tableName) throws IOException {
      if (blockDisable && TABLE.equals(tableName)) {
        blockDisable = false;
        DISABLE_ENTERED.countDown();
        await(DISABLE_RELEASE);
      }
    }
  }

  private static void await(CountDownLatch latch) throws IOException {
    try {
      if (!latch.await(5, TimeUnit.MINUTES)) {
        throw new IOException("latch timeout");
      }
    } catch (InterruptedException e) {
      throw new IOException(e);
    }
  }

  @BeforeAll
  public static void startCluster() throws Exception {
    Configuration conf = TEST_UTIL.getConfiguration();
    conf.set(CoprocessorHost.MASTER_COPROCESSOR_CONF_KEY, BlockingMasterObserver.class.getName());
    // a longer (but ordinary) procedure retry back-off; CloseTableRegionsProcedure uses it when it
    // finds regions of the table in transition
    conf.setLong(ProcedureUtil.PROCEDURE_RETRY_SLEEP_INTERVAL_MS, 30000);
    TEST_UTIL.startMiniCluster(2);
  }

  @AfterAll
  public static void stopCluster() throws Exception {
    DISABLE_RELEASE.countDown();
    TEST_UTIL.shutdownMiniCluster();
  }

  private static RegionStateNode node(HMaster master, RegionInfo ri) {
    return master.getAssignmentManager().getRegionStates().getRegionStateNode(ri);
  }

  @Test
  public void testDecommissionDuringDisableAndMove() throws Exception {
    Admin admin = TEST_UTIL.getAdmin();
    HMaster master = TEST_UTIL.getHBaseCluster().getMaster();
    TableDescriptor td = TableDescriptorBuilder.newBuilder(TABLE)
      .setColumnFamily(ColumnFamilyDescriptorBuilder.of(CF)).build();
    admin.createTable(td);
    TEST_UTIL.waitUntilAllRegionsAssigned(TABLE);

    ServerName rs1 = TEST_UTIL.getHBaseCluster().getRegionServer(0).getServerName();
    ServerName rs2 = TEST_UTIL.getHBaseCluster().getRegionServer(1).getServerName();
    List<RegionInfo> regions = admin.getRegions(TABLE);
    assertEquals(1, regions.size());
    RegionInfo region = regions.get(0);
    admin.move(region.getEncodedNameAsBytes(), rs1);
    TEST_UTIL.waitUntilNoRegionsInTransition(60000);
    assertEquals(rs1, node(master, region).getRegionLocation());

    // 1. Operator A disables the table; the DisableTableProcedure is in PRE_OPERATION.
    blockDisable = true;
    Future<Void> disableFuture = admin.disableTableAsync(TABLE);
    assertTrue(DISABLE_ENTERED.await(60, TimeUnit.SECONDS));
    assertTrue(master.getTableStateManager().isTableState(TABLE, TableState.State.ENABLED));

    // 2. At the same moment a move of the region (operator B or the balancer) is accepted: the
    // table is still ENABLED so preTransitCheck passes and a MOVE TRSP is attached to the region.
    Thread mover = new Thread(() -> {
      try {
        admin.move(region.getEncodedNameAsBytes(), rs2);
      } catch (IOException e) {
        LOG.info("move finished with", e);
      }
    }, "mover");
    mover.setDaemon(true);
    mover.start();
    TEST_UTIL.waitFor(60000, () -> node(master, region).getProcedure() != null);

    // 3. The disable continues: table -> DISABLING, CloseTableRegionsProcedure finds the region in
    // transition (the move), schedules nothing and backs off. The move then completes: the region
    // is OPEN on rs2 with no procedure attached while the table is DISABLING.
    DISABLE_RELEASE.countDown();
    TEST_UTIL.waitFor(60000, () -> {
      RegionStateNode n = node(master, region);
      return master.getTableStateManager().isTableState(TABLE, TableState.State.DISABLING)
        && n.isInState(RegionState.State.OPEN) && n.getProcedure() == null
        && rs2.equals(n.getRegionLocation());
    });
    LOG.info("Region {} is OPEN on {} with no procedure while {} is DISABLING",
      node(master, region), rs2, TABLE);

    // 4. Operator C drains rs2 (decommission with offload) concurrently.
    DoNotRetryIOException caught = null;
    try {
      admin.decommissionRegionServers(Collections.singletonList(rs2), true);
    } catch (DoNotRetryIOException e) {
      caught = e;
      LOG.error("decommissionRegionServers(" + rs2 + ", offload=true) failed", e);
    }
    List<RegionInfo> leftOnRs2 = admin.getRegions(rs2);
    LOG.info("Regions still on decommissioned {}: {}", rs2, leftOnRs2);

    // cleanup
    disableFuture.get(5, TimeUnit.MINUTES);
    admin.recommissionRegionServer(rs2, Collections.emptyList());

    if (caught != null) {
      // The bug: draining a server is rejected because a region of a DISABLING table that is
      // still OPEN (with no procedure) is handed to the move path.
      throw new AssertionError("decommissionRegionServers(offload=true) of " + rs2
        + " was aborted by AssignmentManager.preTransitCheck", caught);
    }
  }
}
