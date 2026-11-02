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

import java.io.IOException;
import java.util.Collections;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hbase.HBaseTestingUtil;
import org.apache.hadoop.hbase.HConstants;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.Admin;
import org.apache.hadoop.hbase.client.ColumnFamilyDescriptorBuilder;
import org.apache.hadoop.hbase.client.Connection;
import org.apache.hadoop.hbase.client.ConnectionFactory;
import org.apache.hadoop.hbase.client.TableDescriptorBuilder;
import org.apache.hadoop.hbase.master.HMaster;
import org.apache.hadoop.hbase.quotas.SpaceQuotaSnapshot.SpaceQuotaStatus;
import org.apache.hadoop.hbase.testclassification.MediumTests;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Space quotas on a one-region-server cluster. A table is created and disabled. A quota observer
 * on the master (the master's own observer runs are delayed past the test) starts with the table's
 * snapshot in DISABLE violation and is run twice, each run moving the table to a snapshot that is
 * not in violation; its client makes one attempt per call. Then the table is flushed.
 */
@Tag(MediumTests.TAG)
public class TestAdhocWorkload04 {
  private static final Logger LOG = LoggerFactory.getLogger(TestAdhocWorkload04.class);
  private static final HBaseTestingUtil UTIL = new HBaseTestingUtil();

  @BeforeAll
  public static void setUp() throws Exception {
    Configuration conf = UTIL.getConfiguration();
    conf.setBoolean(QuotaUtil.QUOTA_CONF_KEY, true);
    conf.setInt(QuotaObserverChore.QUOTA_OBSERVER_CHORE_DELAY_KEY, 3_600_000);
    conf.setInt(QuotaObserverChore.QUOTA_OBSERVER_CHORE_PERIOD_KEY, 3_600_000);
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
    TableName table = TableName.valueOf("adhoc_workload_04");
    Admin admin = UTIL.getAdmin();
    admin.createTable(TableDescriptorBuilder.newBuilder(table)
      .setColumnFamily(ColumnFamilyDescriptorBuilder.of("f")).build());
    admin.disableTable(table);

    Configuration observerConf = new Configuration(UTIL.getConfiguration());
    observerConf.setInt(HConstants.HBASE_CLIENT_RETRIES_NUMBER, 0);
    HMaster master = UTIL.getMiniHBaseCluster().getMaster();
    try (Connection conn = ConnectionFactory.createConnection(observerConf)) {
      TableSpaceQuotaSnapshotNotifier notifier = new TableSpaceQuotaSnapshotNotifier();
      notifier.initialize(conn);
      QuotaObserverChore observer = new QuotaObserverChore(conn, observerConf, notifier,
        master.getMasterQuotaManager(), master, null);
      observer.initializeSnapshotStores(Collections.emptyMap());
      observer.setTableQuotaSnapshot(table,
        new SpaceQuotaSnapshot(new SpaceQuotaStatus(SpaceViolationPolicy.DISABLE), 2048L, 1024L));
      SpaceQuotaSnapshot observance =
        new SpaceQuotaSnapshot(SpaceQuotaStatus.notInViolation(), 2048L, 4096L);
      for (int run = 0; run < 2; run++) {
        try {
          observer.updateTableQuota(table, observer.getTableQuotaSnapshot(table), observance);
        } catch (IOException failed) {
          LOG.warn("Observer run {} failed; the next run retries", run, failed);
        }
      }
    }
    admin.flush(table);
  }
}
