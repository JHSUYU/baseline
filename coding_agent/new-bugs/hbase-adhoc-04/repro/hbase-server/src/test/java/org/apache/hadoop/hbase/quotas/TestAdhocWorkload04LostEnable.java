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

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import java.io.IOException;
import java.util.Collections;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hbase.HBaseTestingUtil;
import org.apache.hadoop.hbase.HConstants;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.TableNotEnabledException;
import org.apache.hadoop.hbase.client.Admin;
import org.apache.hadoop.hbase.client.ColumnFamilyDescriptorBuilder;
import org.apache.hadoop.hbase.client.Connection;
import org.apache.hadoop.hbase.client.ConnectionFactory;
import org.apache.hadoop.hbase.client.TableDescriptorBuilder;
import org.apache.hadoop.hbase.coprocessor.CoprocessorHost;
import org.apache.hadoop.hbase.coprocessor.MasterCoprocessor;
import org.apache.hadoop.hbase.coprocessor.MasterCoprocessorEnvironment;
import org.apache.hadoop.hbase.coprocessor.MasterObserver;
import org.apache.hadoop.hbase.coprocessor.ObserverContext;
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
 * Same workload as {@link TestAdhocWorkload04}, but the first enableTable request issued by the
 * quota observer (when the table moves out of DISABLE violation) fails transiently at the master.
 * QuotaObserverChore.updateTableQuota records the new (observance) state in memory before the
 * enable succeeds, so the next observer run sees current == target and never retries the enable.
 * The table stays DISABLED although its quota is in observance; the following flush is rejected
 * by the TableNotEnabledException check in AbstractStateMachineTableProcedure.preflightChecks.
 */
@Tag(MediumTests.TAG)
public class TestAdhocWorkload04LostEnable {
  private static final Logger LOG = LoggerFactory.getLogger(TestAdhocWorkload04LostEnable.class);
  private static final HBaseTestingUtil UTIL = new HBaseTestingUtil();

  static final AtomicBoolean FAIL_NEXT_ENABLE = new AtomicBoolean(false);
  static final AtomicInteger ENABLE_ATTEMPTS = new AtomicInteger();

  /** Fault injection: the next enableTable request fails at the master (a lost/failed RPC). */
  public static class FailOnceEnableObserver implements MasterCoprocessor, MasterObserver {
    @Override
    public Optional<MasterObserver> getMasterObserver() {
      return Optional.of(this);
    }

    @Override
    public void preEnableTable(ObserverContext<MasterCoprocessorEnvironment> ctx,
      TableName tableName) throws IOException {
      ENABLE_ATTEMPTS.incrementAndGet();
      if (FAIL_NEXT_ENABLE.compareAndSet(true, false)) {
        throw new IOException("Injected transient failure of enableTable " + tableName);
      }
    }
  }

  @BeforeAll
  public static void setUp() throws Exception {
    Configuration conf = UTIL.getConfiguration();
    conf.setBoolean(QuotaUtil.QUOTA_CONF_KEY, true);
    conf.setInt(QuotaObserverChore.QUOTA_OBSERVER_CHORE_DELAY_KEY, 3_600_000);
    conf.setInt(QuotaObserverChore.QUOTA_OBSERVER_CHORE_PERIOD_KEY, 3_600_000);
    conf.set(CoprocessorHost.MASTER_COPROCESSOR_CONF_KEY, FailOnceEnableObserver.class.getName());
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
    // The observer's first enable request fails.
    FAIL_NEXT_ENABLE.set(true);
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
    LOG.info("enableTable attempts by the observer: {}; table enabled={}", ENABLE_ATTEMPTS.get(),
      admin.isTableEnabled(table));
    try {
      admin.flush(table);
      fail("flush should have failed: table left disabled after quota observance");
    } catch (TableNotEnabledException e) {
      LOG.error("Flush rejected: table left DISABLED although quota is in observance", e);
      boolean atCheck = false;
      for (Throwable t = e; t != null; t = t.getCause()) {
        for (StackTraceElement f : t.getStackTrace()) {
          if (f.getClassName().endsWith("AbstractStateMachineTableProcedure")
            && f.getMethodName().equals("preflightChecks")) {
            atCheck = true;
          }
        }
      }
      // Rethrow so that the server-side stack trace shows in the test failure.
      assertTrue(atCheck, "expected frame at AbstractStateMachineTableProcedure.preflightChecks");
      throw e;
    }
  }
}
