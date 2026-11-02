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

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hbase.HBaseTestingUtil;
import org.apache.hadoop.hbase.HConstants;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.Admin;
import org.apache.hadoop.hbase.client.Put;
import org.apache.hadoop.hbase.client.SnapshotType;
import org.apache.hadoop.hbase.client.Table;
import org.apache.hadoop.hbase.master.snapshot.SnapshotManager;
import org.apache.hadoop.hbase.regionserver.snapshot.RegionServerSnapshotManager;
import org.apache.hadoop.hbase.testclassification.MediumTests;
import org.apache.hadoop.hbase.testclassification.RegionServerTests;
import org.apache.hadoop.hbase.util.Bytes;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;

/**
 * The first restore of {@link TestRestoreFlushSnapshotFromClient#testRestoreSnapshot} on its own,
 * under the same configuration: one region server, a one-region table of 10 rows, one FLUSH
 * snapshot, then disable, restore, enable and the row count.
 */
@Tag(RegionServerTests.TAG)
@Tag(MediumTests.TAG)
public class TestAdhocWorkload07 {
  private static final HBaseTestingUtil UTIL = new HBaseTestingUtil();
  private static final byte[] FAMILY = Bytes.toBytes("cf");
  private static final int ROWS = 10;

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
    UTIL.startMiniCluster(1);
  }

  @AfterAll
  public static void tearDown() throws Exception {
    UTIL.shutdownMiniCluster();
  }

  @Test
  public void run() throws Exception {
    TableName tableName = TableName.valueOf("adhoc_workload_07");
    String snapshot = "adhoc_workload_07_snapshot";
    Admin admin = UTIL.getAdmin();
    try (Table table = UTIL.createTable(tableName, FAMILY)) {
      for (int row = 0; row < ROWS; row++) {
        table.put(new Put(Bytes.toBytes("row" + row)).addColumn(FAMILY, Bytes.toBytes("q"),
          Bytes.toBytes(row)));
      }
    }
    admin.snapshot(snapshot, tableName, SnapshotType.FLUSH);
    admin.disableTable(tableName);
    admin.restoreSnapshot(snapshot);
    admin.enableTable(tableName);
    SnapshotTestingUtils.verifyRowCount(UTIL, tableName, ROWS);
  }
}
