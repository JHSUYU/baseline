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
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import java.io.IOException;
import java.util.Collections;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hbase.HBaseTestingUtil;
import org.apache.hadoop.hbase.HConstants;
import org.apache.hadoop.hbase.NamespaceDescriptor;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.Waiter;
import org.apache.hadoop.hbase.client.Admin;
import org.apache.hadoop.hbase.client.ColumnFamilyDescriptorBuilder;
import org.apache.hadoop.hbase.client.Mutation;
import org.apache.hadoop.hbase.client.RegionInfo;
import org.apache.hadoop.hbase.client.TableDescriptor;
import org.apache.hadoop.hbase.client.TableDescriptorBuilder;
import org.apache.hadoop.hbase.coprocessor.CoprocessorHost;
import org.apache.hadoop.hbase.coprocessor.MasterCoprocessor;
import org.apache.hadoop.hbase.coprocessor.MasterCoprocessorEnvironment;
import org.apache.hadoop.hbase.coprocessor.MasterObserver;
import org.apache.hadoop.hbase.coprocessor.ObserverContext;
import org.apache.hadoop.hbase.master.HMaster;
import org.apache.hadoop.hbase.master.TableNamespaceManager;
import org.apache.hadoop.hbase.quotas.MasterQuotaManager;
import org.apache.hadoop.hbase.quotas.QuotaExceededException;
import org.apache.hadoop.hbase.quotas.QuotaUtil;
import org.apache.hadoop.hbase.snapshot.RestoreSnapshotException;
import org.apache.hadoop.hbase.testclassification.LargeTests;
import org.apache.hadoop.hbase.util.Bytes;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * A split that is rolled back after SPLIT_TABLE_REGION_PRE_OPERATION leaves the "+1 region" it
 * reserved in the namespace quota cache (onRegionSplitReverted is never invoked). A later, perfectly
 * valid restore-snapshot of another table in the namespace is then rejected by
 * NamespaceStateManager.checkAndUpdateNamespaceRegionCount(TableName, int).
 */
@Tag(LargeTests.TAG)
public class TestNamespaceAuditorSplitRollbackLeak {

  private static final Logger LOG =
    LoggerFactory.getLogger(TestNamespaceAuditorSplitRollbackLeak.class);
  private static final HBaseTestingUtil UTIL = new HBaseTestingUtil();
  private static Admin ADMIN;

  /** Master observer that aborts a split in the pre-META step (after the quota was reserved). */
  public static class FailSplitObserver implements MasterCoprocessor, MasterObserver {
    static volatile boolean failSplit = false;

    @Override
    public Optional<MasterObserver> getMasterObserver() {
      return Optional.of(this);
    }

    @Override
    public void preSplitRegionBeforeMETAAction(ObserverContext<MasterCoprocessorEnvironment> ctx,
      byte[] splitKey, List<Mutation> metaEntries) throws IOException {
      if (failSplit) {
        throw new IOException("Injected failure of split before META update");
      }
    }
  }

  @BeforeAll
  public static void before() throws Exception {
    Configuration conf = UTIL.getConfiguration();
    conf.setStrings(CoprocessorHost.MASTER_COPROCESSOR_CONF_KEY, FailSplitObserver.class.getName());
    conf.setInt(HConstants.HBASE_CLIENT_RETRIES_NUMBER, 5);
    conf.setBoolean(QuotaUtil.QUOTA_CONF_KEY, true);
    UTIL.startMiniCluster(1);
    UTIL.waitFor(60000, (Waiter.Predicate<Exception>) () -> {
      HMaster master = UTIL.getHBaseCluster().getMaster();
      if (master == null) {
        return false;
      }
      MasterQuotaManager qm = master.getMasterQuotaManager();
      return qm != null && qm.isQuotaInitialized();
    });
    ADMIN = UTIL.getAdmin();
  }

  @AfterAll
  public static void tearDown() throws Exception {
    UTIL.shutdownMiniCluster();
  }

  private static NamespaceTableAndRegionInfo state(String ns) {
    return UTIL.getHBaseCluster().getMaster().getMasterQuotaManager().getNamespaceQuotaManager()
      .getState(ns);
  }

  @Test
  public void testRestoreSnapshotAfterRolledBackSplit() throws Exception {
    String nsp = "TestNamespaceAuditorSplitRollbackLeak_ns";
    NamespaceDescriptor nspDesc = NamespaceDescriptor.create(nsp)
      .addConfiguration(TableNamespaceManager.KEY_MAX_REGIONS, "6").build();
    ADMIN.createNamespace(nspDesc);

    TableName table1 = TableName.valueOf(nsp + TableName.NAMESPACE_DELIM + "table1");
    TableName table2 = TableName.valueOf(nsp + TableName.NAMESPACE_DELIM + "table2");
    TableDescriptor td1 = TableDescriptorBuilder.newBuilder(table1)
      .setColumnFamily(ColumnFamilyDescriptorBuilder.of("fam1")).build();
    TableDescriptor td2 = TableDescriptorBuilder.newBuilder(table2)
      .setColumnFamily(ColumnFamilyDescriptorBuilder.of("fam1")).build();

    // table1: 2 regions
    ADMIN.createTable(td1, new byte[][] { Bytes.toBytes("MMM") });
    // table2: 4 regions, snapshot it, then recreate with 1 region (as in
    // testRestoreSnapshotQuotaExceed)
    ADMIN.createTable(td2, Bytes.toBytes("AAA"), Bytes.toBytes("ZZZ"), 4);
    String snapshot = "snapshot_splitRollbackLeak";
    ADMIN.snapshot(snapshot, table2);
    ADMIN.disableTable(table2);
    ADMIN.deleteTable(table2);
    ADMIN.createTable(td2);
    assertEquals(3, state(nsp).getRegionCount(), "2 (table1) + 1 (table2)");

    // A split of table1 fails after the quota manager already accounted the extra region.
    List<RegionInfo> regions = ADMIN.getRegions(table1);
    Collections.sort(regions, RegionInfo.COMPARATOR);
    FailSplitObserver.failSplit = true;
    try {
      ADMIN.splitRegionAsync(regions.get(0).getRegionName(), Bytes.toBytes("FFF")).get(60,
        TimeUnit.SECONDS);
      fail("split should have failed");
    } catch (ExecutionException e) {
      LOG.info("Split failed and was rolled back as expected", e);
    } finally {
      FailSplitObserver.failSplit = false;
    }
    UTIL.waitUntilNoRegionsInTransition(60000);
    assertEquals(2, ADMIN.getRegions(table1).size(), "split rolled back; table1 still 2 regions");
    LOG.info("Namespace cache after rolled-back split: total={}, table1={}",
      state(nsp).getRegionCount(), state(nsp).getRegionCountOfTable(table1));

    // Real usage: 2 (table1) + 4 (restored table2) = 6 <= 6 => restore must be allowed.
    ADMIN.disableTable(table2);
    try {
      ADMIN.restoreSnapshot(snapshot);
    } catch (RestoreSnapshotException e) {
      LOG.error("Restore of snapshot rejected although it fits the namespace quota", e);
      Throwable c = e;
      while (c != null && !(c instanceof QuotaExceededException)) {
        c = c.getCause();
      }
      assertTrue(c != null, "expected QuotaExceededException cause");
      fail("Valid restore rejected by namespace quota check due to leaked split reservation: "
        + c.getMessage(), c);
    }
  }
}
