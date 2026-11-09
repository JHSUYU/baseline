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
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.util.Collections;
import java.util.List;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hbase.HBaseTestingUtil;
import org.apache.hadoop.hbase.HConstants;
import org.apache.hadoop.hbase.NamespaceDescriptor;
import org.apache.hadoop.hbase.SingleProcessHBaseCluster;
import org.apache.hadoop.hbase.StartTestingClusterOption;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.Admin;
import org.apache.hadoop.hbase.client.ColumnFamilyDescriptorBuilder;
import org.apache.hadoop.hbase.client.RegionInfo;
import org.apache.hadoop.hbase.client.RegionReplicaUtil;
import org.apache.hadoop.hbase.client.TableDescriptor;
import org.apache.hadoop.hbase.client.TableDescriptorBuilder;
import org.apache.hadoop.hbase.coprocessor.CoprocessorHost;
import org.apache.hadoop.hbase.coprocessor.RegionServerObserver;
import org.apache.hadoop.hbase.master.HMaster;
import org.apache.hadoop.hbase.master.TableNamespaceManager;
import org.apache.hadoop.hbase.quotas.QuotaExceededException;
import org.apache.hadoop.hbase.quotas.QuotaUtil;
import org.apache.hadoop.hbase.testclassification.LargeTests;
import org.apache.hadoop.hbase.util.Bytes;
import org.apache.hadoop.hbase.util.JVMClusterUtil;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.Order;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestMethodOrder;

/**
 * MC-4 reproduction, a variant of TestNamespaceAuditor#testRestoreSnapshot: same setup, same quota
 * of 10, same snapshot/disable/restore. Region counts move only through Admin calls; the only fault
 * is the counterexample's master crash. The cache is only read, never written.
 */
@Tag(LargeTests.TAG)
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
public class SpeculaAdhocMC4RebuildReplicasTest {

  private static final HBaseTestingUtil UTIL = new HBaseTestingUtil();
  private static final byte[] FAMILY = Bytes.toBytes("fam1");
  private static Admin ADMIN;

  @BeforeAll
  public static void before() throws Exception {
    Configuration conf = UTIL.getConfiguration();
    conf.set(CoprocessorHost.REGION_COPROCESSOR_CONF_KEY,
      TestNamespaceAuditor.CustomObserver.class.getName());
    conf.setStrings(CoprocessorHost.MASTER_COPROCESSOR_CONF_KEY,
      TestNamespaceAuditor.MasterSyncObserver.class.getName(),
      TestNamespaceAuditor.CPMasterObserver.class.getName());
    conf.setInt(HConstants.HBASE_CLIENT_RETRIES_NUMBER, 5);
    conf.setBoolean(QuotaUtil.QUOTA_CONF_KEY, true);
    conf.setClass("hbase.coprocessor.regionserver.classes",
      TestNamespaceAuditor.CPRegionServerObserver.class, RegionServerObserver.class);
    // Two region servers, so that a replica of a region has somewhere to open. Enough standby
    // masters for every failover below: the client's registry only knows the initial masters.
    UTIL.startMiniCluster(
      StartTestingClusterOption.builder().numMasters(5).numRegionServers(2).build());
    TestNamespaceAuditor.waitForQuotaInitialize(UTIL);
    ADMIN = UTIL.getAdmin();
  }

  @AfterAll
  public static void tearDown() throws Exception {
    UTIL.shutdownMiniCluster();
  }

  private static void log(String message) {
    System.out.println("MC4>> " + message);
  }

  private static String createNamespace(String name) throws Exception {
    ADMIN.createNamespace(NamespaceDescriptor.create(name)
      .addConfiguration(TableNamespaceManager.KEY_MAX_REGIONS, "10").build());
    return name;
  }

  private static TableName table(String namespace, String qualifier) {
    return TableName.valueOf(namespace + TableName.NAMESPACE_DELIM + qualifier);
  }

  private static void create(TableName name, int regions, int replication) throws Exception {
    TableDescriptor desc = TableDescriptorBuilder.newBuilder(name).setRegionReplication(replication)
      .setColumnFamily(ColumnFamilyDescriptorBuilder.of(FAMILY)).build();
    if (regions == 1) {
      ADMIN.createTable(desc);
    } else {
      ADMIN.createTable(desc, Bytes.toBytes("AAA"), Bytes.toBytes("ZZZ"), regions);
    }
    UTIL.waitUntilAllRegionsAssigned(name);
  }

  private static void mergeFirstTwo(TableName name) throws Exception {
    List<RegionInfo> regions = ADMIN.getRegions(name);
    Collections.sort(regions, RegionInfo.COMPARATOR);
    ADMIN.mergeRegionsAsync(regions.get(0).getEncodedNameAsBytes(),
      regions.get(1).getEncodedNameAsBytes(), false).get();
  }

  private static void deleteTable(TableName name) throws Exception {
    TestNamespaceAuditor.MasterSyncObserver observer = UTIL.getHBaseCluster().getMaster()
      .getMasterCoprocessorHost().findCoprocessor(TestNamespaceAuditor.MasterSyncObserver.class);
    ADMIN.disableTable(name);
    ADMIN.deleteTable(name);
    observer.tableDeletionLatch.await();
  }

  private static int primaries(TableName name) throws Exception {
    return (int) ADMIN.getRegions(name).stream().filter(RegionReplicaUtil::isDefaultReplica)
      .count();
  }

  /** Crashes the active master; a standby takes over. */
  private static void failOver() throws Exception {
    SingleProcessHBaseCluster cluster = UTIL.getHBaseCluster();
    List<JVMClusterUtil.MasterThread> masters = cluster.getMasterThreads();
    for (int i = 0; i < masters.size(); i++) {
      HMaster master = masters.get(i).getMaster();
      if (master.isActiveMaster()) {
        log("abort active master " + master.getServerName());
        cluster.abortMaster(i);
        cluster.waitOnMaster(i);
        break;
      }
    }
    assertTrue(cluster.waitForActiveAndReadyMaster(120000));
    TestNamespaceAuditor.waitForQuotaInitialize(UTIL);
    log("new active master " + cluster.getMaster().getServerName());
  }

  /** Read-only view of the namespace cache that the guard at NamespaceStateManager:127 reads. */
  private static NamespaceTableAndRegionInfo cache(String namespace) throws Exception {
    return UTIL.getHBaseCluster().getMaster().getMasterQuotaManager().getNamespaceQuotaManager()
      .getState(namespace);
  }

  private static void report(String step, String nsp, TableName a, TableName b) throws Exception {
    NamespaceTableAndRegionInfo info = cache(nsp);
    int realA = primaries(a);
    int realB = primaries(b);
    log(step + ": cache{A=" + info.getRegionCountOfTable(a) + ",B=" + info.getRegionCountOfTable(b)
      + ",total=" + info.getRegionCount() + "} primaries{A=" + realA + ",B=" + realB + ",total="
      + (realA + realB) + "} quota=10");
  }

  /**
   * The strict same-bug test: the target's exception type, from the target's file and line. The
   * client sees it as the cause of RestoreSnapshotException, after its failsafe rollback.
   */
  private static void assertRestoreFiresTarget(String snapshot, String step) {
    IOException thrown = assertThrows(IOException.class, () -> ADMIN.restoreSnapshot(snapshot));
    log(step + ": restoreSnapshot threw " + thrown.getClass().getName() + ": "
      + thrown.getMessage());
    Throwable target = thrown;
    while (target != null && !(target instanceof QuotaExceededException)) {
      target = target.getCause();
    }
    assertTrue(target != null, "no QuotaExceededException in the cause chain of " + thrown);
    log("  caused by " + target.getClass().getName() + ": " + target.getMessage());
    boolean found = false;
    for (StackTraceElement frame : target.getStackTrace()) {
      log("    at " + frame);
      if (
        frame.getClassName().equals(NamespaceStateManager.class.getName())
          && frame.getMethodName().equals("checkAndUpdateNamespaceRegionCount")
          && frame.getLineNumber() >= 130 && frame.getLineNumber() <= 133
      ) {
        found = true;
      }
    }
    // The target's "throw new" statement spans lines 130-133; javac gives its constructor call the
    // line of the last argument (133). See MC-4.javap.txt.
    assertTrue(found, "no frame in the target statement, NamespaceStateManager:130-133");
  }

  /** Control: the counterexample's operations without the failover. The restore is admitted. */
  @Test
  @Order(1)
  public void controlNoFailover() throws Exception {
    String nsp = createNamespace("mc4_control");
    TableName a = table(nsp, "A");
    TableName b = table(nsp, "B");
    create(a, 3, 1);
    create(b, 4, 2);
    ADMIN.snapshot("mc4_control_s", a);
    mergeFirstTwo(a);
    report("control before restore", nsp, a, b);
    assertEquals(6, cache(nsp).getRegionCount());
    ADMIN.disableTable(a);
    ADMIN.restoreSnapshot("mc4_control_s");
    ADMIN.enableTable(a);
    report("control after restore", nsp, a, b);
    assertEquals(7, cache(nsp).getRegionCount());
    assertEquals(3, primaries(a));
    log("control: restore ADMITTED (no failover, replication 2)");
  }

  /** Control: the failover with replication 1 everywhere. The restore is admitted. */
  @Test
  @Order(2)
  public void controlFailoverWithoutReplicas() throws Exception {
    String nsp = createNamespace("mc4_norep");
    TableName a = table(nsp, "A");
    TableName b = table(nsp, "B");
    create(a, 3, 1);
    create(b, 4, 1);
    ADMIN.snapshot("mc4_norep_s", a);
    mergeFirstTwo(a);
    failOver();
    report("no-replica control after failover", nsp, a, b);
    assertEquals(6, cache(nsp).getRegionCount());
    ADMIN.disableTable(a);
    ADMIN.restoreSnapshot("mc4_norep_s");
    ADMIN.enableTable(a);
    report("no-replica control after restore", nsp, a, b);
    assertEquals(7, cache(nsp).getRegionCount());
    log("no-replica control: restore ADMITTED (failover, replication 1)");
  }

  /**
   * The counterexample's order: create A, create B with replicas, snapshot A, merge A, master
   * failover, disable A, restore. Then the retry, a wait, and a second failover: does it heal?
   */
  @Test
  @Order(3)
  public void counterexampleOrder() throws Exception {
    String nsp = createNamespace("mc4_ce");
    TableName a = table(nsp, "A");
    TableName b = table(nsp, "B");
    create(a, 3, 1);
    create(b, 4, 2);
    ADMIN.snapshot("mc4_ce_s", a);
    mergeFirstTwo(a);
    report("before failover", nsp, a, b);
    assertEquals(2, cache(nsp).getRegionCountOfTable(a));
    assertEquals(4, cache(nsp).getRegionCountOfTable(b));

    failOver();
    report("after failover", nsp, a, b);
    assertEquals(8, cache(nsp).getRegionCountOfTable(b), "rebuild counts one per located replica");
    assertEquals(4, primaries(b));

    ADMIN.disableTable(a);
    report("before restore", nsp, a, b);
    assertRestoreFiresTarget("mc4_ce_s", "first restore");
    log("guard: 10 - 2 + 3 = 11 > 10; admitting it would really leave 3 + 4 = 7 primaries");
    assertEquals(2, primaries(a), "A was not restored");

    // Does anything downstream resolve the cache? Time and the janitor, then another failover.
    Thread.sleep(20000);
    ADMIN.runCatalogJanitor();
    report("after 20s and a janitor run", nsp, a, b);
    assertRestoreFiresTarget("mc4_ce_s", "retry after wait");

    failOver();
    report("after second failover", nsp, a, b);
    assertEquals(8, cache(nsp).getRegionCountOfTable(b), "rebuild reproduces the inflation");
    assertRestoreFiresTarget("mc4_ce_s", "retry after second failover");

    ADMIN.enableTable(a);
    report("end", nsp, a, b);
  }

  /** The finding's order: A with 3, snapshot, recreate A with 1, B 4 at replication 2. */
  @Test
  @Order(4)
  public void recreateOrder() throws Exception {
    String nsp = createNamespace("mc4_recreate");
    TableName a = table(nsp, "A");
    TableName b = table(nsp, "B");
    create(a, 3, 1);
    ADMIN.snapshot("mc4_recreate_s", a);
    deleteTable(a);
    create(a, 1, 1);
    create(b, 4, 2);
    report("before failover", nsp, a, b);
    assertEquals(5, cache(nsp).getRegionCount());

    failOver();
    report("after failover", nsp, a, b);
    assertEquals(9, cache(nsp).getRegionCount());

    ADMIN.disableTable(a);
    assertRestoreFiresTarget("mc4_recreate_s", "restore");
    log("guard: 9 - 1 + 3 = 11 > 10; admitting it would really leave 3 + 4 = 7 primaries");
    assertEquals(1, primaries(a), "A was not restored");
  }
}
