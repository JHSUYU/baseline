#!/usr/bin/env bash
# MC-1 reproduction: a DeleteNamespaceProcedure recovered after failover races quota init on the new
# master; NamespaceStateManager.initialize throws from ClusterSchemaServiceImpl:111 and the master aborts.
#
# Usage: test_bugMC-1_nsm_init_abort.sh <mode> [rounds] [earlierTables]
#   level0     Level 0: public API only. deleteNamespaceAsync races killMaster. No hooks.
#   natural    Level 1: crash placed by ProcedureTestingUtility.setKillBeforeStoreUpdate; no hold on m2.
#              earlierTables tables live in a namespace sorting before the deleted one.
#   hold       Level 1: same crash; m2's init thread waits at the existing MasterObserver.preGetTableNames
#              hook (top of NSM:227) until the DNP has removed the namespace. Workload namespace only.
#   control    Negative control: same crash, no hold, no earlier tables (natural window of microseconds).
#
# Needs hbase-server sources pristine at 1790942bb2 (see the guard below). No system source is edited.
# The worktree normally carries Phase 2.5 instrumentation. To run this script, reverse it first:
#   git apply -R ../instrumentation-backup/tracked.patch
#   rm hbase-server/src/main/java/org/apache/hadoop/hbase/SpeculaTrace.java \
#      hbase-server/src/test/java/org/apache/hadoop/hbase/namespace/SpeculaAdhocHbaseAdhoc08Test.java
set -uo pipefail
MODE=${1:?mode}; ROUNDS=${2:-1}; TABLES=${3:-0}
OUT=/users/ZhenyuLi/Specula/runs/20261102-195741-783a/hbase-adhoc-08/.specula-output
WT=$OUT/confirmation/MC-1/worktree
LOGS=$OUT/repro/MC-1-logs; mkdir -p "$LOGS"
source /bulk/specula-adhoc/hbase/cases/hbase-adhoc-08/env.sh
cd "$WT" || exit 2

TEST=hbase-server/src/test/java/org/apache/hadoop/hbase/namespace/SpeculaMC1ReproTest.java
# Guard: main sources must be exactly the pinned commit.
[ "$(git rev-parse --short=10 HEAD)" = "1790942bb2" ] || { echo "wrong HEAD"; exit 2; }
if [ -n "$(git status --short -- hbase-server/src/main hbase-procedure hbase-common | grep -v target)" ]; then
  echo "main sources are not pristine:"; git status --short -- hbase-server/src/main; exit 2
fi
if [ -n "$(git status --short -- hbase-server/src/test | grep -v SpeculaMC1ReproTest)" ]; then
  echo "test sources are not pristine:"; git status --short -- hbase-server/src/test; exit 2
fi

cat > "$TEST" <<'JAVA'
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
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import java.io.IOException;
import java.io.PrintStream;
import java.io.FileOutputStream;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hbase.HBaseTestingUtil;
import org.apache.hadoop.hbase.HConstants;
import org.apache.hadoop.hbase.NamespaceDescriptor;
import org.apache.hadoop.hbase.NamespaceNotFoundException;
import org.apache.hadoop.hbase.SingleProcessHBaseCluster;
import org.apache.hadoop.hbase.StartTestingClusterOption;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.Admin;
import org.apache.hadoop.hbase.client.ColumnFamilyDescriptor;
import org.apache.hadoop.hbase.client.ColumnFamilyDescriptorBuilder;
import org.apache.hadoop.hbase.client.TableDescriptor;
import org.apache.hadoop.hbase.client.TableDescriptorBuilder;
import org.apache.hadoop.hbase.coprocessor.CoprocessorHost;
import org.apache.hadoop.hbase.coprocessor.MasterCoprocessor;
import org.apache.hadoop.hbase.coprocessor.MasterCoprocessorEnvironment;
import org.apache.hadoop.hbase.coprocessor.MasterObserver;
import org.apache.hadoop.hbase.coprocessor.ObserverContext;
import org.apache.hadoop.hbase.coprocessor.RegionServerObserver;
import org.apache.hadoop.hbase.master.HMaster;
import org.apache.hadoop.hbase.master.MasterServices;
import org.apache.hadoop.hbase.master.TableNamespaceManager;
import org.apache.hadoop.hbase.master.procedure.MasterProcedureConstants;
import org.apache.hadoop.hbase.procedure2.ProcedureTestingUtility;
import org.apache.hadoop.hbase.quotas.MasterQuotaManager;
import org.apache.hadoop.hbase.quotas.QuotaUtil;
import org.apache.hadoop.hbase.testclassification.LargeTests;
import org.apache.hadoop.hbase.util.Bytes;
import org.apache.hadoop.hbase.util.JVMClusterUtil;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;

/**
 * Variant of TestNamespaceAuditor#testTableOperations for MC-1. Setup and body are copied from it.
 * It writes neither the namespace cache nor meta's ns rows, and edits no system source.
 */
@Tag(LargeTests.TAG)
public class SpeculaMC1ReproTest {
  private static final String PREFIX = "TestNamespaceAuditor";
  private static final String NSP = PREFIX + "_np2";
  private static final String EARLIER = PREFIX + "_np1";
  private static final PrintStream REPORT = report();

  private static PrintStream report() {
    try {
      return new PrintStream(new FileOutputStream(System.getenv("MC1_REPORT"), true), true);
    } catch (IOException e) {
      throw new IllegalStateException(e);
    }
  }

  private static void say(String s) {
    REPORT.println(s);
  }

  /** Waits at the top of NSM:227 until the DNP has removed the namespace. Read-only; never writes. */
  public static class HoldNsmLookup implements MasterCoprocessor, MasterObserver {
    static volatile boolean armed;
    static final AtomicInteger HELD = new AtomicInteger();
    static volatile long waitedMs;

    @Override
    public Optional<MasterObserver> getMasterObserver() {
      return Optional.of(this);
    }

    @Override
    public void preGetTableNames(ObserverContext<MasterCoprocessorEnvironment> ctx,
      List<TableDescriptor> descriptors, String regex) throws IOException {
      if (!armed) {
        return;
      }
      boolean fromNsmInit = false;
      for (StackTraceElement f : new Throwable().getStackTrace()) {
        fromNsmInit |= f.getClassName().endsWith("NamespaceStateManager");
      }
      if (!fromNsmInit) {
        return;
      }
      armed = false;
      HELD.incrementAndGet();
      MasterServices m = ctx.getEnvironment().getMasterServices();
      long start = System.currentTimeMillis();
      while (m.getClusterSchema().getTableNamespaceManager().doesNamespaceExist(NSP)
        && System.currentTimeMillis() - start < 120000) {
        try {
          Thread.sleep(5);
        } catch (InterruptedException e) {
          Thread.currentThread().interrupt();
          return;
        }
      }
      waitedMs = System.currentTimeMillis() - start;
    }
  }

  private static final class Trial {
    final HBaseTestingUtil util = new HBaseTestingUtil();
    Admin admin;
    SingleProcessHBaseCluster cluster;
  }

  private Trial start(String mode) throws Exception {
    Trial t = new Trial();
    Configuration conf = t.util.getConfiguration();
    conf.set(CoprocessorHost.REGION_COPROCESSOR_CONF_KEY,
      TestNamespaceAuditor.CustomObserver.class.getName());
    if (mode.equals("hold")) {
      conf.setStrings(CoprocessorHost.MASTER_COPROCESSOR_CONF_KEY,
        TestNamespaceAuditor.MasterSyncObserver.class.getName(),
        TestNamespaceAuditor.CPMasterObserver.class.getName(), HoldNsmLookup.class.getName());
    } else {
      conf.setStrings(CoprocessorHost.MASTER_COPROCESSOR_CONF_KEY,
        TestNamespaceAuditor.MasterSyncObserver.class.getName(),
        TestNamespaceAuditor.CPMasterObserver.class.getName());
    }
    conf.setInt(HConstants.HBASE_CLIENT_RETRIES_NUMBER, 5);
    conf.setBoolean(QuotaUtil.QUOTA_CONF_KEY, true);
    conf.setClass("hbase.coprocessor.regionserver.classes",
      TestNamespaceAuditor.CPRegionServerObserver.class, RegionServerObserver.class);
    if (!mode.equals("level0")) {
      // setKillBeforeStoreUpdate asserts one worker (ProcedureTestingUtility:270), as in
      // TestDeleteNamespaceProcedure.
      conf.setInt(MasterProcedureConstants.MASTER_PROCEDURE_THREADS, 1);
    }
    t.util.startMiniCluster(StartTestingClusterOption.builder().numMasters(2).build());
    TestNamespaceAuditor.waitForQuotaInitialize(t.util);
    t.util.waitTableAvailable(QuotaUtil.QUOTA_TABLE_NAME, 120000);
    t.admin = t.util.getAdmin();
    t.cluster = t.util.getHBaseCluster();
    return t;
  }

  /** TestNamespaceAuditor#testTableOperations, then the table half of its cleanup. */
  private void workload(Trial t, int earlierTables) throws Exception {
    Admin admin = t.admin;
    ColumnFamilyDescriptor fam =
      ColumnFamilyDescriptorBuilder.newBuilder(Bytes.toBytes("fam1")).build();
    if (earlierTables > 0) {
      admin.createNamespace(NamespaceDescriptor.create(EARLIER).build());
      for (int i = 0; i < earlierTables; i++) {
        admin.createTable(TableDescriptorBuilder
          .newBuilder(TableName.valueOf(EARLIER + TableName.NAMESPACE_DELIM + "t" + i))
          .setColumnFamily(fam).build());
      }
    }
    NamespaceDescriptor nspDesc =
      NamespaceDescriptor.create(NSP).addConfiguration(TableNamespaceManager.KEY_MAX_REGIONS, "5")
        .addConfiguration(TableNamespaceManager.KEY_MAX_TABLES, "2").build();
    admin.createNamespace(nspDesc);
    assertNotNull(admin.getNamespaceDescriptor(NSP), "Namespace descriptor found null.");
    assertEquals(earlierTables > 0 ? 4 : 3, admin.listNamespaceDescriptors().length);
    TableDescriptor one = TableDescriptorBuilder
      .newBuilder(TableName.valueOf(NSP + TableName.NAMESPACE_DELIM + "table1"))
      .setColumnFamily(fam).build();
    TableDescriptor two = TableDescriptorBuilder
      .newBuilder(TableName.valueOf(NSP + TableName.NAMESPACE_DELIM + "table2"))
      .setColumnFamily(fam).build();
    admin.createTable(one);
    boolean rejected = false;
    try {
      admin.createTable(two, Bytes.toBytes("AAA"), Bytes.toBytes("ZZZ"), 5);
    } catch (IOException e) {
      rejected = true;
    }
    assertTrue(rejected, "Constraint not violated for table2");
    admin.createTable(two, Bytes.toBytes("AAA"), Bytes.toBytes("ZZZ"), 4);
    for (TableName tn : new TableName[] { one.getTableName(), two.getTableName() }) {
      admin.disableTable(tn);
      TestNamespaceAuditor.MasterSyncObserver observer = t.cluster.getMaster()
        .getMasterCoprocessorHost().findCoprocessor(TestNamespaceAuditor.MasterSyncObserver.class);
      admin.deleteTable(tn);
      observer.tableDeletionLatch.await();
    }
  }

  private static HMaster other(SingleProcessHBaseCluster cluster, HMaster m1) {
    for (JVMClusterUtil.MasterThread mt : cluster.getMasterThreads()) {
      if (mt.getMaster() != m1) {
        return mt.getMaster();
      }
    }
    throw new IllegalStateException("no backup master");
  }

  private org.apache.logging.log4j.core.Appender captureStartupFailure(
    AtomicReference<Throwable> thrown) {
    org.apache.logging.log4j.core.Appender appender =
      mock(org.apache.logging.log4j.core.Appender.class);
    when(appender.getName()).thenReturn("mc1Appender");
    when(appender.isStarted()).thenReturn(true);
    doAnswer(inv -> {
      org.apache.logging.log4j.core.LogEvent e =
        inv.getArgument(0, org.apache.logging.log4j.core.LogEvent.class);
      if (e.getMessage().getFormattedMessage().contains("Failed to become active master")
        && e.getThrown() != null) {
        thrown.compareAndSet(null, e.getThrown());
      }
      return null;
    }).when(appender).append(any(org.apache.logging.log4j.core.LogEvent.class));
    ((org.apache.logging.log4j.core.Logger) org.apache.logging.log4j.LogManager
      .getLogger(HMaster.class)).addAppender(appender);
    return appender;
  }

  /** Returns the outcome label for one trial. */
  private String trial(String mode, int round, int earlierTables) throws Exception {
    HoldNsmLookup.armed = false;
    Trial t = start(mode);
    AtomicReference<Throwable> thrown = new AtomicReference<>();
    org.apache.logging.log4j.core.Appender appender = captureStartupFailure(thrown);
    try {
      workload(t, earlierTables);
      HMaster m1 = t.cluster.getMaster();
      HMaster m2 = other(t.cluster, m1);
      assertFalse(m2.isActiveMaster(), "m2 should be the backup");
      long tCrash = System.currentTimeMillis();
      if (mode.equals("level0")) {
        // Level 0: the client's delete and the crash race. Nothing holds the procedure.
        Thread killer = new Thread(() -> {
          try {
            Thread.sleep(ThreadLocalRandom.current().nextInt(0, 6));
            t.cluster.killMaster(m1.getServerName());
          } catch (Exception e) {
            say("killer: " + e);
          }
        }, "mc1-killer");
        killer.start();
        try {
          t.admin.deleteNamespaceAsync(NSP);
        } catch (IOException e) {
          say("deleteNamespaceAsync on the dying master: " + e.getClass().getSimpleName());
        }
        killer.join();
      } else {
        // CE states 43-44: the DNP is persisted at submit; the worker's first store update kills the
        // executor, so the store keeps it at PREPARE. Then the master dies.
        HoldNsmLookup.armed = mode.equals("hold");
        ProcedureTestingUtility.setKillBeforeStoreUpdate(m1.getMasterProcedureExecutor(), true);
        t.admin.deleteNamespaceAsync(NSP);
        t.util.waitFor(60000, () -> !m1.getMasterProcedureExecutor().isRunning());
        t.cluster.killMaster(m1.getServerName());
      }

      // Wait for m2's fate.
      t.util.waitFor(300000, 50, () -> {
        MasterQuotaManager q = m2.getMasterQuotaManager();
        return m2.isAborted() || m2.isStopped() || (q != null && q.isQuotaInitialized());
      });
      long elapsed = System.currentTimeMillis() - tCrash;
      if (m2.isAborted() || m2.isStopped()) {
        Throwable e = thrown.get();
        say(String.format("[%s #%d tables=%d] m2 %s after %d ms", mode, round, earlierTables,
          m2.isAborted() ? "ABORTED" : "STOPPED", elapsed));
        say("  HMaster logged: Failed to become active master; exception = " + e);
        if (e != null) {
          StackTraceElement[] st = e.getStackTrace();
          for (int i = 0; i < Math.min(st.length, 12); i++) {
            say("    at " + st[i]);
          }
        }
        boolean targetFrame = e instanceof NamespaceNotFoundException && e.getStackTrace().length > 0
          && e.getStackTrace()[0].getClassName().endsWith("ClusterSchemaServiceImpl")
          && e.getStackTrace()[0].getMethodName().equals("getNamespace")
          && e.getStackTrace()[0].getLineNumber() == 111;
        say("  thrown from ClusterSchemaServiceImpl.getNamespace:111 = " + targetFrame);
        // The consumer: with both masters gone, can a client still do master operations?
        say("  active master visible to the cluster: " + t.cluster.getMaster());
        try (Admin probe = t.util.getConnection().getAdmin()) {
          long s = System.currentTimeMillis();
          try {
            probe.listNamespaceDescriptors();
            say("  client listNamespaceDescriptors: OK (unexpected)");
          } catch (IOException ioe) {
            say("  client listNamespaceDescriptors FAILED after " + (System.currentTimeMillis() - s)
              + " ms: " + ioe.getClass().getSimpleName());
          }
        }
        // Does an operator-started third master recover?
        JVMClusterUtil.MasterThread m3 = t.cluster.startMaster();
        t.util.waitFor(300000, 100, () -> {
          MasterQuotaManager q = m3.getMaster().getMasterQuotaManager();
          return m3.getMaster().isAborted()
            || (q != null && q.isQuotaInitialized());
        });
        say("  third master: aborted=" + m3.getMaster().isAborted() + " quotaInitialized="
          + (m3.getMaster().getMasterQuotaManager() != null));
        if (!m3.getMaster().isAborted()) {
          // Read m3 directly: the test client's MasterRegistry only lists the original two ports.
          boolean gone = true;
          for (NamespaceDescriptor ns : m3.getMaster().getClusterSchema().getNamespaces()) {
            gone &= !ns.getName().equals(NSP);
          }
          say("  after third master: namespace " + NSP + " gone from its cache = " + gone);
          t.util.waitFor(120000, 100, () -> m3.getMaster().getMasterProcedureExecutor()
            .getProcedures().stream().allMatch(p -> p.isFinished()));
          m3.getMaster().getMasterProcedureExecutor().getProcedures().stream()
            .filter(p -> p instanceof org.apache.hadoop.hbase.master.procedure.DeleteNamespaceProcedure)
            .forEach(p -> say("  DNP final state on third master: " + p.getState()
              + (p.hasException() ? " exception=" + p.getException().getCause() : "")));
        }
        return targetFrame ? "TARGET_FIRED" : "ABORTED_OTHER:" + e;
      }
      say(String.format("[%s #%d tables=%d] m2 up, quota initialized after %d ms; held=%d", mode,
        round, earlierTables, elapsed, HoldNsmLookup.HELD.get()));
      return "M2_OK";
    } finally {
      HoldNsmLookup.armed = false;
      ((org.apache.logging.log4j.core.Logger) org.apache.logging.log4j.LogManager
        .getLogger(HMaster.class)).removeAppender(appender);
      t.util.shutdownMiniCluster();
    }
  }

  @Test
  public void repro() throws Exception {
    String mode = System.getenv("MC1_MODE");
    int rounds = Integer.parseInt(System.getenv("MC1_ROUNDS"));
    int tables = Integer.parseInt(System.getenv("MC1_TABLES"));
    int fired = 0;
    for (int r = 1; r <= rounds; r++) {
      String outcome = trial(mode, r, tables);
      say(String.format("OUTCOME mode=%s round=%d tables=%d => %s", mode, r, tables, outcome));
      if (outcome.equals("TARGET_FIRED")) {
        fired++;
      }
    }
    say(String.format("SUMMARY mode=%s tables=%d fired=%d/%d", mode, tables, fired, rounds));
    if (mode.equals("hold")) {
      assertEquals(rounds, fired, "hold mode should fire the target every round");
    }
  }
}
JAVA

STAMP=$MODE-$TABLES-$(date +%H%M%S)
REPORT=$LOGS/$STAMP.report.txt; : > "$REPORT"
timeout 300 mvn -B -o -q test-compile -pl hbase-server -Denforcer.skip=true -Dmaven.javadoc.skip=true \
  > "$LOGS/$STAMP.compile.log" 2>&1 || { echo "TEST COMPILE FAILED"; grep -E 'ERROR.*java|BUILD' "$LOGS/$STAMP.compile.log" | head -20; exit 3; }

MC1_MODE=$MODE MC1_ROUNDS=$ROUNDS MC1_TABLES=$TABLES MC1_REPORT=$REPORT \
timeout "${MC1_TIMEOUT:-1500}" mvn -B -o surefire:test -pl hbase-server -Dtest='SpeculaMC1ReproTest#repro' \
  -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false -Dsurefire.timeout=1450 \
  > "$LOGS/$STAMP.mvn.log" 2>&1
RC=$?
cp hbase-server/target/surefire-reports/*SpeculaMC1ReproTest*-output.txt "$LOGS/$STAMP.server-output.txt" 2>/dev/null
echo "== command: $0 $MODE $ROUNDS $TABLES   (surefire exit=$RC)"
cat "$REPORT"
grep -E 'Tests run:.*SpeculaMC1|Tests run:.*Fail|BUILD ' "$LOGS/$STAMP.mvn.log" | tail -3
echo "== logs: $LOGS/$STAMP.*"
exit $RC
