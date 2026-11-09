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

import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.util.Collections;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;
import org.apache.hadoop.hbase.HBaseTestingUtil;
import org.apache.hadoop.hbase.ServerName;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.Admin;
import org.apache.hadoop.hbase.client.Put;
import org.apache.hadoop.hbase.client.RegionInfo;
import org.apache.hadoop.hbase.client.Table;
import org.apache.hadoop.hbase.coprocessor.CoprocessorHost;
import org.apache.hadoop.hbase.coprocessor.MasterCoprocessor;
import org.apache.hadoop.hbase.coprocessor.MasterCoprocessorEnvironment;
import org.apache.hadoop.hbase.coprocessor.MasterObserver;
import org.apache.hadoop.hbase.coprocessor.ObserverContext;
import org.apache.hadoop.hbase.master.RegionState;
import org.apache.hadoop.hbase.testclassification.MediumTests;
import org.apache.hadoop.hbase.util.Bytes;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Decommissioning (with offload) a region server while one of its regions is being split. The
 * SplitTableRegionProcedure puts the parent region into SPLITTING state (in memory, without
 * attaching a procedure to the RegionStateNode) in SPLIT_TABLE_REGION_PREPARE and only attaches the
 * unassign TRSP in SPLIT_TABLE_REGION_CLOSE_PARENT_REGION. In between, the move issued by the
 * offload hits AssignmentManager.preTransitCheck, which throws DoNotRetryRegionException
 * ("Unexpected state") instead of the retryable "in transition" HBaseIOException; the offload loop
 * aborts and the remaining regions are never moved off the decommissioned server.
 */
@Tag(MediumTests.TAG)
public class TestRegionMoveDuringSplit {

  private static final Logger LOG = LoggerFactory.getLogger(TestRegionMoveDuringSplit.class);

  private static final HBaseTestingUtil TEST_UTIL = new HBaseTestingUtil();
  private static final byte[] F1 = Bytes.toBytes("f1");

  static volatile boolean block = false;
  static final CountDownLatch ENTERED = new CountDownLatch(1);
  static final CountDownLatch RELEASE = new CountDownLatch(1);

  public static class BlockingSplitObserver implements MasterCoprocessor, MasterObserver {
    @Override
    public Optional<MasterObserver> getMasterObserver() {
      return Optional.of(this);
    }

    @Override
    public void preSplitRegionAction(ObserverContext<MasterCoprocessorEnvironment> c,
      TableName tableName, byte[] splitRow) throws IOException {
      if (block) {
        ENTERED.countDown();
        try {
          RELEASE.await(120, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
          Thread.currentThread().interrupt();
        }
      }
    }
  }

  @BeforeAll
  public static void startCluster() throws Exception {
    TEST_UTIL.getConfiguration().set(CoprocessorHost.MASTER_COPROCESSOR_CONF_KEY,
      BlockingSplitObserver.class.getName());
    TEST_UTIL.startMiniCluster(2);
  }

  @AfterAll
  public static void stopCluster() throws Exception {
    RELEASE.countDown();
    TEST_UTIL.shutdownMiniCluster();
  }

  @Test
  public void testDecommissionWhileSplitting() throws Exception {
    TableName tableName = TableName.valueOf("testDecommissionWhileSplitting");
    Admin admin = TEST_UTIL.getAdmin();
    byte[][] splitKeys = new byte[][] { Bytes.toBytes("1"), Bytes.toBytes("3"),
      Bytes.toBytes("5"), Bytes.toBytes("7") };
    Table t = TEST_UTIL.createTable(tableName, new byte[][] { F1 }, splitKeys);
    TEST_UTIL.waitUntilAllRegionsAssigned(tableName);
    for (int i = 0; i < 10; i++) {
      Put p = new Put(Bytes.toBytes(Integer.toString(i) + "-row"));
      p.addColumn(F1, Bytes.toBytes("q"), Bytes.toBytes("v"));
      t.put(p);
    }
    admin.flush(tableName);

    HRegionServer rs1 = TEST_UTIL.getRSForFirstRegionInTable(tableName);
    ServerName rs1Name = rs1.getServerName();
    List<RegionInfo> onRs1 = admin.getRegions(rs1Name).stream()
      .filter(r -> r.getTable().equals(tableName)).collect(Collectors.toList());
    assertTrue(!onRs1.isEmpty());
    RegionInfo parent = onRs1.get(0);
    byte[] splitRow = Bytes.add(parent.getStartKey(), Bytes.toBytes("0"));
    LOG.info("Splitting {} at {} on {}", parent.getEncodedName(), Bytes.toString(splitRow),
      rs1Name);

    // A split of a region on rs1 is in progress (it could equally have been requested by the
    // region server itself because the region grew too big).
    block = true;
    Future<Void> splitFuture = admin.splitRegionAsync(parent.getRegionName(), splitRow);
    assertTrue(ENTERED.await(60, TimeUnit.SECONDS), "split did not reach pre-operation");
    RegionState state = TEST_UTIL.getHBaseCluster().getMaster().getAssignmentManager()
      .getRegionStates().getRegionState(parent);
    LOG.info("Parent region state while split is in progress: {}", state);

    try {
      // Operator decommissions rs1 and asks to offload its regions.
      admin.decommissionRegionServers(Collections.singletonList(rs1Name), true);
    } finally {
      block = false;
      RELEASE.countDown();
      try {
        splitFuture.get(120, TimeUnit.SECONDS);
      } catch (Exception e) {
        LOG.warn("split failed", e);
      }
    }
  }
}
