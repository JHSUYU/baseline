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
package org.apache.hadoop.hbase.snapshot;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import java.io.IOException;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hbase.HBaseTestingUtil;
import org.apache.hadoop.hbase.HConstants;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.Admin;
import org.apache.hadoop.hbase.client.Mutation;
import org.apache.hadoop.hbase.client.Put;
import org.apache.hadoop.hbase.client.SnapshotType;
import org.apache.hadoop.hbase.client.Table;
import org.apache.hadoop.hbase.coprocessor.CoprocessorHost;
import org.apache.hadoop.hbase.coprocessor.ObserverContext;
import org.apache.hadoop.hbase.coprocessor.RegionCoprocessor;
import org.apache.hadoop.hbase.coprocessor.RegionCoprocessorEnvironment;
import org.apache.hadoop.hbase.coprocessor.RegionObserver;
import org.apache.hadoop.hbase.master.snapshot.SnapshotManager;
import org.apache.hadoop.hbase.regionserver.MiniBatchOperationInProgress;
import org.apache.hadoop.hbase.regionserver.snapshot.RegionServerSnapshotManager;
import org.apache.hadoop.hbase.testclassification.MediumTests;
import org.apache.hadoop.hbase.testclassification.RegionServerTests;
import org.apache.hadoop.hbase.util.Bytes;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Two concurrent cloneSnapshot requests of the same snapshot to the same (new) table. The first
 * clone procedure writes the new table's descriptor to the file system (WRITE_FS_LAYOUT) before
 * the table-state row of the new table appears in hbase:meta (ASSIGN_REGIONS). A meta write that
 * is slow (held here by a latch on the hbase:meta region) widens that window. The second client's
 * tableExists() pre-check (table-state row in meta) says the target does not exist, but the master
 * sees the descriptor and routes the clone request into the restore path, whose "must be
 * disabled" check then looks at the SOURCE table of the snapshot (which is enabled) and throws
 * UnsupportedOperationException.
 */
@Tag(RegionServerTests.TAG)
@Tag(MediumTests.TAG)
public class TestAdhocConcurrentCloneSnapshot07 {
  private static final Logger LOG =
    LoggerFactory.getLogger(TestAdhocConcurrentCloneSnapshot07.class);
  private static final HBaseTestingUtil UTIL = new HBaseTestingUtil();
  private static final byte[] FAMILY = Bytes.toBytes("cf");
  private static final int ROWS = 10;

  static volatile byte[] blockRowPrefix = null;
  static final CountDownLatch reached = new CountDownLatch(1);
  static final CountDownLatch release = new CountDownLatch(1);

  /** Delays the hbase:meta write of the region rows of the clone target (a slow meta write). */
  public static class SlowMetaObserver implements RegionCoprocessor, RegionObserver {
    @Override
    public Optional<RegionObserver> getRegionObserver() {
      return Optional.of(this);
    }

    @Override
    public void preBatchMutate(ObserverContext<? extends RegionCoprocessorEnvironment> c,
      MiniBatchOperationInProgress<Mutation> miniBatchOp) throws IOException {
      byte[] prefix = blockRowPrefix;
      if (prefix == null || !c.getEnvironment().getRegionInfo().isMetaRegion()) {
        return;
      }
      for (int i = 0; i < miniBatchOp.size(); i++) {
        if (Bytes.startsWith(miniBatchOp.getOperation(i).getRow(), prefix)) {
          LOG.info("Holding meta write of {}", Bytes.toStringBinary(prefix));
          reached.countDown();
          try {
            release.await(120, TimeUnit.SECONDS);
          } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
          }
          return;
        }
      }
    }
  }

  @BeforeAll
  public static void setupCluster() throws Exception {
    Configuration conf = UTIL.getConfiguration();
    conf.setInt("hbase.regionserver.msginterval", 100);
    conf.setInt("hbase.client.pause", 250);
    conf.setInt(HConstants.HBASE_CLIENT_RETRIES_NUMBER, 6);
    conf.setBoolean("hbase.master.enabletable.roundrobin", true);
    conf.setBoolean(SnapshotManager.HBASE_SNAPSHOT_ENABLED, true);
    conf.setLong(RegionServerSnapshotManager.SNAPSHOT_TIMEOUT_MILLIS_KEY,
      RegionServerSnapshotManager.SNAPSHOT_TIMEOUT_MILLIS_DEFAULT * 2);
    conf.set(CoprocessorHost.REGION_COPROCESSOR_CONF_KEY, SlowMetaObserver.class.getName());
    UTIL.startMiniCluster(1);
  }

  @AfterAll
  public static void tearDown() throws Exception {
    release.countDown();
    UTIL.shutdownMiniCluster();
  }

  @Test
  public void run() throws Exception {
    TableName tableName = TableName.valueOf("adhoc_workload_07");
    TableName cloneName = TableName.valueOf("adhoc_workload_07_clone");
    String snapshot = "adhoc_workload_07_snapshot";
    Admin admin = UTIL.getAdmin();
    try (Table table = UTIL.createTable(tableName, FAMILY)) {
      for (int row = 0; row < ROWS; row++) {
        table.put(new Put(Bytes.toBytes("row" + row)).addColumn(FAMILY, Bytes.toBytes("q"),
          Bytes.toBytes(row)));
      }
    }
    admin.snapshot(snapshot, tableName, SnapshotType.FLUSH);

    // Client A: clone the snapshot into a new table. Its meta write is slow.
    blockRowPrefix = Bytes.toBytes(cloneName.getNameAsString() + ",");
    CompletableFuture<Void> cloneA =
      UTIL.getAsyncConnection().getAdmin().cloneSnapshot(snapshot, cloneName);
    assertTrue(reached.await(60, TimeUnit.SECONDS), "clone A did not reach ADD_TO_META");

    // Client B: the same clone request while A is in progress. The source table is untouched and
    // enabled; B never asked for a restore.
    Throwable err = null;
    try {
      admin.cloneSnapshot(snapshot, cloneName);
    } catch (Throwable t) {
      err = t;
    } finally {
      blockRowPrefix = null;
      release.countDown();
    }
    cloneA.get(120, TimeUnit.SECONDS);
    if (err == null) {
      fail("second clone unexpectedly succeeded");
    }
    StringWriter sw = new StringWriter();
    err.printStackTrace(new PrintWriter(sw));
    String trace = sw.toString();
    LOG.info("Second cloneSnapshot failed with:\n{}", trace);
    System.out.println("Second cloneSnapshot failed with:\n" + trace);
    if (trace.contains("UnsupportedOperationException")) {
      throw new AssertionError("cloneSnapshot to a new table hit restore check on source table",
        err);
    }
    fail("unexpected failure: " + trace);
  }
}
