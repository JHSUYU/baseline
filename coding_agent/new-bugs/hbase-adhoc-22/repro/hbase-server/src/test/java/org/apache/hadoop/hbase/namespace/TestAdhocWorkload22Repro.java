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

import java.util.List;
import org.apache.hadoop.hbase.HBaseTestingUtil;
import org.apache.hadoop.hbase.MetaTableAccessor;
import org.apache.hadoop.hbase.NamespaceDescriptor;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.Admin;
import org.apache.hadoop.hbase.client.ColumnFamilyDescriptorBuilder;
import org.apache.hadoop.hbase.client.RegionInfo;
import org.apache.hadoop.hbase.client.TableDescriptor;
import org.apache.hadoop.hbase.client.TableDescriptorBuilder;
import org.apache.hadoop.hbase.master.TableNamespaceManager;
import org.apache.hadoop.hbase.quotas.QuotaUtil;
import org.apache.hadoop.hbase.testclassification.MediumTests;
import org.apache.hadoop.hbase.util.Bytes;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;

/**
 * Reproduces a spurious namespace region-quota rejection. Truncating a two-region table without
 * preserving its splits leaves it with one region, but the master's namespace quota cache
 * (NamespaceStateManager) still accounts two regions for it, because TruncateTableProcedure never
 * updates the cache. A subsequent creation of a one-region table in a namespace that allows two
 * regions (1 real + 1 new = 2) is then rejected by the check in
 * NamespaceStateManager.checkAndUpdateNamespaceTableCount (2 cached + 1 = 3 &gt; 2).
 */
@Tag(MediumTests.TAG)
public class TestAdhocWorkload22Repro {
  private static final HBaseTestingUtil UTIL = new HBaseTestingUtil();
  private static final String NAMESPACE = "adhoc_workload_22";

  @BeforeAll
  public static void setUp() throws Exception {
    UTIL.getConfiguration().setBoolean(QuotaUtil.QUOTA_CONF_KEY, true);
    UTIL.startMiniCluster(1);
    UTIL.waitFor(30000,
      () -> UTIL.getMiniHBaseCluster().getMaster().getMasterQuotaManager().isQuotaInitialized());
  }

  @AfterAll
  public static void tearDown() throws Exception {
    UTIL.shutdownMiniCluster();
  }

  @Test
  public void run() throws Exception {
    Admin admin = UTIL.getAdmin();
    admin.createNamespace(NamespaceDescriptor.create(NAMESPACE)
      .addConfiguration(TableNamespaceManager.KEY_MAX_REGIONS, "2").build());
    TableName truncated = TableName.valueOf(NAMESPACE, "truncated");
    admin.createTable(table(truncated), new byte[][] { Bytes.toBytes("m") });
    admin.disableTable(truncated);
    admin.truncateTable(truncated, false);
    UTIL.waitTableAvailable(truncated);

    // The truncated table really has a single region now.
    List<RegionInfo> regions =
      MetaTableAccessor.getTableRegions(UTIL.getConnection(), truncated, true);
    assertEquals(1, regions.size(), "regions of truncated table in meta: " + regions);
    NamespaceTableAndRegionInfo state = UTIL.getMiniHBaseCluster().getMaster()
      .getMasterQuotaManager().getNamespaceQuotaManager().getState(NAMESPACE);
    System.out.println("REPRO: real region count of " + truncated + " = " + regions.size()
      + ", namespace quota cache = " + state);

    // 1 real region + 1 new region = 2 <= max 2, so this must succeed. It fails with
    // QuotaExceededException thrown at NamespaceStateManager.java:168.
    try {
      admin.createTable(table(TableName.valueOf(NAMESPACE, "created")));
    } catch (Exception e) {
      System.out.println("REPRO: createTable failed:");
      e.printStackTrace(System.out);
      throw e;
    }
  }

  private static TableDescriptor table(TableName name) {
    return TableDescriptorBuilder.newBuilder(name)
      .setColumnFamily(ColumnFamilyDescriptorBuilder.of("f")).build();
  }
}
