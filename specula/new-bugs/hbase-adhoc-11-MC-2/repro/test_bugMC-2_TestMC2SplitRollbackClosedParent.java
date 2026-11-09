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
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Random;
import java.util.TreeMap;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.stream.Collectors;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hbase.HBaseTestingUtil;
import org.apache.hadoop.hbase.HConstants;
import org.apache.hadoop.hbase.MetaTableAccessor;
import org.apache.hadoop.hbase.NamespaceDescriptor;
import org.apache.hadoop.hbase.ServerName;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.Admin;
import org.apache.hadoop.hbase.client.Connection;
import org.apache.hadoop.hbase.client.ConnectionFactory;
import org.apache.hadoop.hbase.client.DoNotRetryRegionException;
import org.apache.hadoop.hbase.client.Get;
import org.apache.hadoop.hbase.client.Put;
import org.apache.hadoop.hbase.client.RegionInfo;
import org.apache.hadoop.hbase.client.Result;
import org.apache.hadoop.hbase.client.Table;
import org.apache.hadoop.hbase.master.HMaster;
import org.apache.hadoop.hbase.master.RegionState;
import org.apache.hadoop.hbase.master.TableNamespaceManager;
import org.apache.hadoop.hbase.master.assignment.AssignmentManager;
import org.apache.hadoop.hbase.master.assignment.RegionStateNode;
import org.apache.hadoop.hbase.master.assignment.RegionStateStore;
import org.apache.hadoop.hbase.master.assignment.SplitTableRegionProcedure;
import org.apache.hadoop.hbase.master.assignment.TransitRegionStateProcedure;
import org.apache.hadoop.hbase.master.locking.LockManager;
import org.apache.hadoop.hbase.procedure2.LockType;
import org.apache.hadoop.hbase.procedure2.Procedure;
import org.apache.hadoop.hbase.quotas.QuotaUtil;
import org.apache.hadoop.hbase.testclassification.LargeTests;
import org.apache.hadoop.hbase.util.Bytes;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInfo;

/**
 * MC-2 reproduction: a variant of {@link TestRegionMove#testDisableAndMove} (copy of its table
 * setup, same unassign-then-assign sequence). It never writes region state: state nodes are only
 * read to time requests and to report. The PRE_OPERATION failure of the counterexample comes from
 * a real namespace region quota (MasterQuotaManager.onRegionSplit), so no coprocessor or mock is
 * involved. Levels: testLevel0 is a pure client-side race; testLevel1 realises the counterexample
 * order deterministically with the master's own LockManager table lock (timing only).
 */
@Tag(LargeTests.TAG)
public class TestMC2SplitRollbackClosedParent {

  private static final String F1 = "f1";
  private static final String NS = "mc2";
  private static final String TARGET_FRAME = "preTransitCheck(AssignmentManager.java:769)";

  private HBaseTestingUtil util;
  private Admin admin;
  private TableName tableName;
  private Table table;
  private ExecutorService pool;
  private String method;

  private static void say(String s) {
    System.out.println("MC2: " + s);
    System.out.flush();
  }

  @BeforeEach
  public void setup(TestInfo info) throws Exception {
    method = info.getTestMethod().get().getName();
    util = new HBaseTestingUtil();
    Configuration conf = util.getConfiguration();
    // Namespace region quotas are a production feature; this is how they are enabled.
    conf.setBoolean(QuotaUtil.QUOTA_CONF_KEY, true);
    // RIT chore runs every 60s by default. Shorten it: if it healed the state we would see that.
    conf.setInt(AssignmentManager.RIT_CHORE_INTERVAL_MSEC_CONF_KEY, 1000);
    util.startMiniCluster(2);
    admin = util.getAdmin();
    pool = Executors.newCachedThreadPool();
  }

  @AfterEach
  public void teardown() throws Exception {
    pool.shutdownNow();
    util.shutdownMiniCluster();
  }

  private HMaster master() {
    return util.getMiniHBaseCluster().getMaster();
  }

  private RegionStateNode node(RegionInfo r) {
    return master().getAssignmentManager().getRegionStates().getRegionStateNode(r);
  }

  private RegionState.State metaState(RegionInfo r) throws IOException {
    Result res = MetaTableAccessor.getRegionResult(util.getConnection(), r);
    return RegionStateStore.getRegionState(res, r);
  }

  private String snap(RegionInfo r) throws IOException {
    RegionStateNode n = node(r);
    return "region=" + r.getEncodedName() + " rsn.state=" + n.getState() + " rsn.location="
      + n.getRegionLocation() + " rsn.procedure="
      + (n.getProcedure() == null ? "none" : "pid=" + n.getProcedure().getProcId())
      + " meta.state=" + metaState(r) + " hostedBy=" + hostedBy(r);
  }

  private List<ServerName> hostedBy(RegionInfo r) {
    List<ServerName> out = new ArrayList<>();
    util.getMiniHBaseCluster().getRegionServerThreads().forEach(t -> {
      if (t.getRegionServer().getRegion(r.getEncodedName()) != null) {
        out.add(t.getRegionServer().getServerName());
      }
    });
    return out;
  }

  /** The table setup of testDisableAndMove, in a namespace whose region quota is saturated. */
  private List<RegionInfo> createSaturatedTable(int numRegions) throws Exception {
    admin.createNamespace(NamespaceDescriptor.create(NS).build());
    tableName = TableName.valueOf(NS, method);
    table = util.createMultiRegionTable(tableName, Bytes.toBytes(F1), numRegions);
    util.waitUntilAllRegionsAssigned(tableName);
    List<RegionInfo> regions = admin.getRegions(tableName);
    for (RegionInfo ri : regions) {
      table.put(rowFor(ri));
    }
    admin.modifyNamespace(NamespaceDescriptor.create(NS)
      .addConfiguration(TableNamespaceManager.KEY_MAX_REGIONS, Integer.toString(regions.size()))
      .build());
    say("table=" + tableName + " regions=" + regions.size() + " namespaceMaxRegions="
      + regions.size());
    return regions;
  }

  private static byte[] keyFor(RegionInfo ri) {
    return org.apache.hbase.thirdparty.com.google.common.primitives.Bytes.concat(ri.getStartKey(),
      Bytes.toBytes("1"));
  }

  private static Put rowFor(RegionInfo ri) {
    Put p = new Put(keyFor(ri));
    p.addColumn(Bytes.toBytes(F1), Bytes.toBytes("q1"), Bytes.toBytes("value"));
    return p;
  }

  private SplitTableRegionProcedure splitProcFor(RegionInfo r) {
    for (Procedure<?> p : master().getMasterProcedureExecutor().getProcedures()) {
      if (p instanceof SplitTableRegionProcedure && p.toString().contains(r.getShortNameToLog())) {
        return (SplitTableRegionProcedure) p;
      }
    }
    return null;
  }

  private void waitUntil(String what, long ms, java.util.function.BooleanSupplier c)
    throws InterruptedException {
    long end = System.currentTimeMillis() + ms;
    while (!c.getAsBoolean()) {
      if (System.currentTimeMillis() > end) {
        fail("timed out waiting for " + what);
      }
      Thread.sleep(5);
    }
  }

  /** The workload's own "Reassign for next stage of test" call. Returns the thrown exception. */
  private DoNotRetryRegionException assignExpectingTarget(RegionInfo r) throws Exception {
    try {
      admin.assign(r.getRegionName());
    } catch (DoNotRetryRegionException e) {
      return e;
    }
    say("assign SUCCEEDED; " + snap(r));
    return null;
  }

  private void reportTarget(DoNotRetryRegionException e) {
    assertNotNull(e, "assign did not throw");
    assertEquals(DoNotRetryRegionException.class, e.getClass());
    say("TARGET FIRED: client received " + e.getClass().getName());
    for (String line : String.valueOf(e.getMessage()).split("\n")) {
      if (
        line.contains("Unexpected state") || line.contains("UNEXPECTED")
          || line.contains("DoNotRetryRegionException") || line.contains("AssignmentManager")
          || line.contains("MasterRpcServices.assignRegion")
      ) {
        say("  server-side: " + line.trim());
      }
    }
    assertTrue(String.valueOf(e.getMessage()).contains(TARGET_FRAME),
      "stack must hold the target frame " + TARGET_FRAME + "; got: " + e.getMessage());
    say("target frame present in server stack: " + TARGET_FRAME);
  }

  /** Reader with short retries: does a real client get the data? */
  private String readAs(RegionInfo r) throws IOException {
    Configuration c = new Configuration(util.getConfiguration());
    c.setInt(HConstants.HBASE_CLIENT_RETRIES_NUMBER, 2);
    c.setInt(HConstants.HBASE_CLIENT_OPERATION_TIMEOUT, 15000);
    c.setInt(HConstants.HBASE_RPC_TIMEOUT_KEY, 3000);
    try (Connection conn = ConnectionFactory.createConnection(c);
      Table t = conn.getTable(tableName)) {
      Result res = t.get(new Get(keyFor(r)));
      return "read OK, empty=" + res.isEmpty();
    } catch (IOException e) {
      return "read FAILED: " + e.getClass().getName() + ": "
        + String.valueOf(e.getMessage()).split("\n")[0];
    }
  }

  /** Assert the leaked state of the finding: state node OPEN, no location, meta CLOSED. */
  private void assertLeak(RegionInfo r) throws Exception {
    say("after split rollback: " + snap(r));
    RegionStateNode n = node(r);
    assertEquals(RegionState.State.OPEN, n.getState());
    assertNull(n.getRegionLocation());
    assertNull(n.getProcedure());
    assertEquals(RegionState.State.CLOSED, metaState(r));
    assertTrue(hostedBy(r).isEmpty(), "no region server may host the region");
  }

  /**
   * Realises counterexample states 2-15 with real RPCs. The master's table lock only holds the
   * procedures back, so that the unassign is ahead of the split and the state node still reads OPEN
   * when the split request is checked.
   */
  private void driveToLeak(RegionInfo r) throws Exception {
    assertEquals(RegionState.State.OPEN, node(r).getState());
    LockManager.MasterLock lock = master().getLockManager().createMasterLock(tableName,
      LockType.EXCLUSIVE, "MC-2 ordering (timing only)");
    assertTrue(lock.tryAcquire(60_000), "table lock");
    Future<Void> unassign;
    Future<Void> split;
    try {
      unassign = pool.submit(() -> {
        admin.unassign(r.getRegionName(), true);
        return null;
      });
      waitUntil("unassign attached and submitted", 30_000, () -> {
        TransitRegionStateProcedure p = node(r).getProcedure();
        return p != null && p.getProcId() != Procedure.NO_PROC_ID;
      });
      say("CE state 2 (unassign accepted): " + snap(r));
      split = admin.splitRegionAsync(r.getRegionName(), keyFor(r));
      waitUntil("split accepted", 30_000, () -> splitProcFor(r) != null || split.isDone());
      assertNotNull(splitProcFor(r), "split request must be accepted");
      say("CE state 3 (split accepted while state node OPEN): " + splitProcFor(r) + "; " + snap(r));
    } finally {
      lock.release();
    }
    unassign.get(120, TimeUnit.SECONDS);
    say("unassign RPC returned, CE state 9 passed (split may already have run its rollback): " + snap(r));
    awaitSplitVeto(r, split);
    assertLeak(r);
  }

  private void awaitSplitVeto(RegionInfo r, Future<Void> split) throws Exception {
    try {
      split.get(120, TimeUnit.SECONDS);
      fail("split must be vetoed");
    } catch (ExecutionException e) {
      say("CE states 12-13 (PRE_OPERATION fails, rollback): split future failed with "
        + rootCauseLine(e));
    }
    SplitTableRegionProcedure p = splitProcFor(r);
    if (p != null) {
      waitUntil("split finished", 60_000, p::isFinished);
      say("split procedure finished: " + p);
    }
    waitUntil("region transition settled", 60_000, () -> node(r).getProcedure() == null);
  }

  private static String rootCauseLine(Throwable t) {
    Throwable c = t;
    while (c.getCause() != null && c.getCause() != c) {
      c = c.getCause();
    }
    return c.getClass().getName() + ": " + String.valueOf(c.getMessage()).split("\n")[0];
  }

  private RegionInfo regionOnFirstServer(List<RegionInfo> regions) throws Exception {
    HRegionServer rs1 = util.getRSForFirstRegionInTable(tableName);
    List<RegionInfo> onRs1 = admin.getRegions(rs1.getServerName()).stream()
      .filter(ri -> ri.getTable().equals(tableName)).collect(Collectors.toList());
    assertTrue(!onRs1.isEmpty());
    return onRs1.get(0);
  }

  /** Level 0: unassign and split race from two clients. Nothing in the master is touched. */
  @Test
  public void testLevel0() throws Exception {
    List<RegionInfo> regions = new ArrayList<>(createSaturatedTable(30));
    Random rnd = new Random(Long.parseLong(System.getenv().getOrDefault("MC2_SEED", "42")));
    long deadline = System.currentTimeMillis() + Long.getLong("mc2.level0.ms", 300_000L);
    TreeMap<String, Integer> outcomes = new TreeMap<>();
    int round = 0;
    RegionInfo hit = null;
    while (hit == null && System.currentTimeMillis() < deadline) {
      round++;
      RegionInfo r = regions.get(round % regions.size());
      int offsetUs = rnd.nextInt(16_000) - 8_000; // split starts up to 8ms before/after unassign
      CyclicBarrier barrier = new CyclicBarrier(2);
      Future<Void> u = pool.submit(() -> {
        barrier.await();
        if (offsetUs < 0) {
          TimeUnit.MICROSECONDS.sleep(-offsetUs);
        }
        admin.unassign(r.getRegionName(), true);
        return null;
      });
      Future<String> s = pool.submit(() -> {
        barrier.await();
        if (offsetUs > 0) {
          TimeUnit.MICROSECONDS.sleep(offsetUs);
        }
        try {
          admin.splitRegionAsync(r.getRegionName(), keyFor(r)).get(60, TimeUnit.SECONDS);
          return "split-succeeded";
        } catch (ExecutionException | IOException e) {
          String line = rootCauseLine(e);
          return line.contains("QuotaExceeded") || line.contains("quota")
            ? "split-accepted-then-vetoed"
            : "split-rejected";
        }
      });
      u.get(120, TimeUnit.SECONDS);
      String so = s.get(120, TimeUnit.SECONDS);
      outcomes.merge(so, 1, Integer::sum);
      waitUntil("settled", 60_000, () -> node(r).getProcedure() == null);
      // the split may still be parked behind the unassign when its RPC was the last to return
      SplitTableRegionProcedure sp = splitProcFor(r);
      if (sp != null) {
        waitUntil("split finished", 60_000, sp::isFinished);
      }
      RegionStateNode n = node(r);
      if (
        n.getState() == RegionState.State.OPEN && n.getRegionLocation() == null
          && metaState(r) == RegionState.State.CLOSED
      ) {
        hit = r;
        say("LEVEL0 HIT in round " + round + " offsetUs=" + offsetUs + " splitOutcome=" + so);
        break;
      }
      if (n.getState() == RegionState.State.CLOSED) {
        admin.assign(r.getRegionName());
        outcomes.merge("reassign-ok", 1, Integer::sum);
      } else if (n.getState() != RegionState.State.OPEN) {
        say("unexpected state in round " + round + ": " + snap(r));
        outcomes.merge("other-" + n.getState(), 1, Integer::sum);
      }
    }
    say("LEVEL0 rounds=" + round + " outcomes=" + outcomes + " hit=" + (hit != null));
    assertNotNull(hit, "Level 0 race did not hit within the budget");
    assertLeak(hit);
    reportTarget(assignExpectingTarget(hit));
    say("consumer read: " + readAs(hit));
  }

  /** Level 1: the counterexample's order, made deterministic, with both controls. */
  @Test
  public void testLevel1() throws Exception {
    List<RegionInfo> regions = createSaturatedTable(10);
    RegionInfo r = regionOnFirstServer(regions);
    List<RegionInfo> others = new ArrayList<>(regions);
    others.remove(r);

    // Control A: the unmodified workload sequence, no split: assign must work.
    RegionInfo a = others.get(0);
    admin.unassign(a.getRegionName(), true);
    say("control A after unassign: " + snap(a));
    admin.assign(a.getRegionName());
    say("control A after assign (no split involved): " + snap(a));
    assertEquals(RegionState.State.OPEN, node(a).getState());
    assertNotNull(node(a).getRegionLocation());

    // Control B: same quota veto, on an open region with no unassign: no harm, still served.
    RegionInfo b = others.get(1);
    try {
      admin.splitRegionAsync(b.getRegionName(), keyFor(b)).get(120, TimeUnit.SECONDS);
      fail("control B: split must be vetoed by the quota");
    } catch (ExecutionException e) {
      say("control B split vetoed: " + rootCauseLine(e));
    }
    say("control B after rollback: " + snap(b) + "; consumer " + readAs(b));
    assertEquals(RegionState.State.OPEN, node(b).getState());
    assertNotNull(node(b).getRegionLocation());

    // The finding.
    say("read before: " + readAs(r));
    driveToLeak(r);
    reportTarget(assignExpectingTarget(r));
    say("consumer read: " + readAs(r));

    // Is it transient? 30 RIT chore periods later nothing has healed it.
    Thread.sleep(30_000);
    say("after 30s (RIT chore every 1s): " + snap(r));
    assertEquals(RegionState.State.OPEN, node(r).getState());
    assertNull(node(r).getRegionLocation());
    reportTarget(assignExpectingTarget(r));
    say("consumer read after 30s: " + readAs(r));
  }

  /** What each recovery path does on the leaked state. One path per JVM/cluster. */
  private RegionInfo leak() throws Exception {
    List<RegionInfo> regions = createSaturatedTable(10);
    RegionInfo r = regionOnFirstServer(regions);
    driveToLeak(r);
    reportTarget(assignExpectingTarget(r));
    return r;
  }

  private String boundedCall(java.util.concurrent.Callable<?> c, long sec) throws Exception {
    Future<?> f = pool.submit(c);
    try {
      return "returned " + f.get(sec, TimeUnit.SECONDS);
    } catch (TimeoutException e) {
      return "NO RETURN within " + sec + "s";
    } catch (ExecutionException e) {
      return "threw " + rootCauseLine(e);
    }
  }

  @Test
  public void testRecoveryUnassign() throws Exception {
    RegionInfo r = leak();
    say("admin.unassign -> " + boundedCall(() -> {
      admin.unassign(r.getRegionName(), true);
      return null;
    }, 90));
    say("after unassign: " + snap(r));
    say("admin.assign -> " + boundedCall(() -> {
      admin.assign(r.getRegionName());
      return null;
    }, 90));
    say("after assign: " + snap(r) + "; consumer " + readAs(r));
  }

  @Test
  public void testRecoveryMove() throws Exception {
    RegionInfo r = leak();
    ServerName dest = util.getMiniHBaseCluster().getRegionServer(0).getServerName();
    say("admin.move -> " + boundedCall(() -> {
      admin.move(r.getEncodedNameAsBytes(), dest);
      return null;
    }, 90));
    say("after move: " + snap(r) + "; consumer " + readAs(r));
  }

  @Test
  public void testRecoveryHbck() throws Exception {
    RegionInfo r = leak();
    List<String> enc = Collections.singletonList(r.getEncodedName());
    say("hbck.assigns(override=true, force=false) -> " + boundedCall(
      () -> util.getHbck().assigns(enc, true, false), 60));
    say("after hbck override: " + snap(r));
    say("hbck.assigns(override=true, force=true) -> " + boundedCall(
      () -> util.getHbck().assigns(enc, true, true), 60));
    Thread.sleep(5_000);
    say("after hbck force: " + snap(r) + "; consumer " + readAs(r));
  }

  @Test
  public void testRecoveryMasterFailover() throws Exception {
    RegionInfo r = leak();
    ServerName old = util.getMiniHBaseCluster().getMaster().getServerName();
    util.getMiniHBaseCluster().stopMaster(old);
    util.getMiniHBaseCluster().waitForMasterToStop(old, 60_000);
    util.getMiniHBaseCluster().startMaster();
    util.getMiniHBaseCluster().waitForActiveAndReadyMaster(120_000);
    util.invalidateConnection();
    admin = util.getAdmin();
    say("after failover: " + snap(r));
    say("admin.assign -> " + boundedCall(() -> {
      admin.assign(r.getRegionName());
      return null;
    }, 90));
    say("after assign: " + snap(r) + "; consumer " + readAs(r));
  }
}
