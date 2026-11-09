/**
 * Specula reproduction for finding MC-2 (Scenario 2: master failover after the HDFS descriptor
 * write).  Variant of TestTableDescriptorModificationFromClient#testAddColumn (same module, same
 * package, same table shape: cf0, disabled, then Admin.addColumnFamily(cf1)).
 *
 * Counterexample (spec/output/MC_hunt_s2_failover_bfs.out) realized step by step:
 *   s2-s5   client sends addColumn(cf1) with nonce 1; handler passes the guard (old={cf0}) and
 *           submits ModifyTableProcedure; the handler blocks on the prepare latch.
 *   s6-s9   procedure runs PREPARE, PRE_OPERATION, UPDATE_TABLE_DESCRIPTOR; the new tableinfo
 *           (cf0,cf1) is written to HDFS (FSTableDescriptors.java:590).
 *   s10     the active master crashes before the procedure finishes and before the reply.
 *   s11     the client's in-flight call fails retriably.
 *   s12-13  a (replacement) master becomes active, reloads the procedure, preloads descriptors from HDFS.
 *   s14-16  HBaseAdmin retries with a fresh nonce; the new master's guard at HMaster.java:2253
 *           sees cf1 and throws InvalidFamilyOperationException at HMaster.java:2255.
 *
 * Only codebase test utilities are used:
 *   - timing: a MasterObserver that holds the procedure thread in postCompletedModifyTableAction
 *     (MODIFY_TABLE_POST_OPERATION, the first coprocessor hook after the HDFS write) until the
 *     master has been aborted.  It never touches table descriptors (the guard's operands).
 *   - fault:  MiniHBaseCluster.abortMaster(int) (the single master crash the counterexample uses).
 * No source of the system under test is modified.
 */
package org.apache.hadoop.hbase.master.procedure;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import java.io.IOException;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hbase.HBaseClassTestRule;
import org.apache.hadoop.hbase.HBaseTestingUtility;
import org.apache.hadoop.hbase.HColumnDescriptor;
import org.apache.hadoop.hbase.HConstants;
import org.apache.hadoop.hbase.HTableDescriptor;
import org.apache.hadoop.hbase.InvalidFamilyOperationException;
import org.apache.hadoop.hbase.MiniHBaseCluster;
import org.apache.hadoop.hbase.ServerName;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.Admin;
import org.apache.hadoop.hbase.client.TableDescriptor;
import org.apache.hadoop.hbase.coprocessor.CoprocessorHost;
import org.apache.hadoop.hbase.coprocessor.MasterCoprocessor;
import org.apache.hadoop.hbase.coprocessor.MasterCoprocessorEnvironment;
import org.apache.hadoop.hbase.coprocessor.MasterObserver;
import org.apache.hadoop.hbase.coprocessor.ObserverContext;
import org.apache.hadoop.hbase.master.HMaster;
import org.apache.hadoop.hbase.master.MasterFileSystem;
import org.apache.hadoop.hbase.procedure2.Procedure;
import org.apache.hadoop.hbase.procedure2.ProcedureExecutor;
import org.apache.hadoop.hbase.testclassification.LargeTests;
import org.apache.hadoop.hbase.testclassification.MasterTests;
import org.apache.hadoop.hbase.util.Bytes;
import org.apache.hadoop.hbase.util.FSTableDescriptors;
import org.apache.hadoop.hbase.util.JVMClusterUtil;
import org.junit.AfterClass;
import org.junit.BeforeClass;
import org.junit.ClassRule;
import org.junit.Test;
import org.junit.experimental.categories.Category;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

@Category({MasterTests.class, LargeTests.class})
public class TestSpeculaBugMC2FailoverAddColumn {

  @ClassRule
  public static final HBaseClassTestRule CLASS_RULE =
      HBaseClassTestRule.forClass(TestSpeculaBugMC2FailoverAddColumn.class);

  private static final Logger LOG = LoggerFactory.getLogger(TestSpeculaBugMC2FailoverAddColumn.class);
  private static final HBaseTestingUtility TEST_UTIL = new HBaseTestingUtility();
  private static final TableName TABLE_NAME = TableName.valueOf("testAddColumn");
  private static final byte[] FAMILY_0 = Bytes.toBytes("cf0");
  private static final byte[] FAMILY_1 = Bytes.toBytes("cf1");

  // ---- timing control (codebase coprocessor hook), shared across the in-process masters ----
  static final AtomicBoolean ARMED = new AtomicBoolean(false);
  static final AtomicReference<ServerName> HELD_ON = new AtomicReference<>();
  static final CountDownLatch REACHED_POST_OP = new CountDownLatch(1);
  static final CountDownLatch CRASHED = new CountDownLatch(1);

  public static class HoldAfterDescriptorWrite implements MasterCoprocessor, MasterObserver {
    @Override
    public Optional<MasterObserver> getMasterObserver() {
      return Optional.of(this);
    }

    @Override
    public void postCompletedModifyTableAction(ObserverContext<MasterCoprocessorEnvironment> ctx,
        TableName tableName, TableDescriptor oldDescriptor, TableDescriptor currentDescriptor)
        throws IOException {
      if (!TABLE_NAME.equals(tableName)) {
        return;
      }
      ServerName me = ctx.getEnvironment().getServerName();
      if (ARMED.compareAndSet(true, false)) {
        HELD_ON.set(me);
        LOG.info("SPECULA-MC2 holding ModifyTableProcedure at POST_OPERATION on {} "
            + "(HDFS tableinfo already written, reply not sent)", me);
        REACHED_POST_OP.countDown();
        try {
          CRASHED.await(120, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
          Thread.currentThread().interrupt();
        }
        // The master is dead: its procedure thread must not make further progress.
        throw new IOException("SPECULA-MC2: master " + me + " crashed");
      }
      if (me.equals(HELD_ON.get())) {
        throw new IOException("SPECULA-MC2: master " + me + " crashed");
      }
      LOG.info("SPECULA-MC2 postCompletedModifyTableAction passes on {}", me);
    }
  }

  @BeforeClass
  public static void beforeAllTests() throws Exception {
    Configuration conf = TEST_UTIL.getConfiguration();
    conf.set(CoprocessorHost.MASTER_COPROCESSOR_CONF_KEY,
        HoldAfterDescriptorWrite.class.getName());
    // Let HBaseAdmin's normal retry loop span a master failover.
    conf.setInt(HConstants.HBASE_CLIENT_RETRIES_NUMBER, 60);
    conf.setLong(HConstants.HBASE_CLIENT_PAUSE, 500);
    conf.setInt(HConstants.HBASE_RPC_TIMEOUT_KEY, 30000);
    // One master + one RS.  After the crash a replacement master is started once the crashed
    // master's thread has exited (in a single-JVM mini cluster both masters would otherwise share
    // one DFSClient lease renewer, and HDFS lease recovery of the procedure WAL can stall).
    TEST_UTIL.startMiniCluster(1, 1);
  }

  @AfterClass
  public static void afterAllTests() throws Exception {
    CRASHED.countDown();
    TEST_UTIL.shutdownMiniCluster();
  }

  @Test
  public void testAddColumnRetryAfterFailover() throws Exception {
    MiniHBaseCluster cluster = TEST_UTIL.getMiniHBaseCluster();
    Admin admin = TEST_UTIL.getAdmin();
    HTableDescriptor baseHtd = new HTableDescriptor(TABLE_NAME);
    baseHtd.addFamily(new HColumnDescriptor(FAMILY_0));
    admin.createTable(baseHtd);
    admin.disableTable(TABLE_NAME);
    verifyTableDescriptor(FAMILY_0);

    final HMaster oldActive = cluster.getMaster();
    LOG.info("SPECULA-MC2 active master before crash: {}", oldActive.getServerName());

    // Crasher: once the procedure has written the HDFS descriptor and is held before
    // completion (so the addColumn handler is still blocked and no reply was sent),
    // crash the active master.
    Thread crasher = new Thread(() -> {
      try {
        if (!REACHED_POST_OP.await(120, TimeUnit.SECONDS)) {
          LOG.error("SPECULA-MC2 procedure never reached POST_OPERATION");
          return;
        }
        // Evidence that the HDFS write (FSTableDescriptors.java:590) already happened.
        MasterFileSystem mfs = oldActive.getMasterFileSystem();
        TableDescriptor onFs =
            FSTableDescriptors.getTableDescriptorFromFs(mfs.getFileSystem(), mfs.getRootDir(),
              TABLE_NAME);
        LOG.info("SPECULA-MC2 before crash: HDFS tableinfo families={} ; handler reply pending",
            onFs.getColumnFamilyNames().size());
        System.out.println("SPECULA-MC2 BEFORE-CRASH hdfsHasCf1=" + onFs.hasColumnFamily(FAMILY_1));
        int idx = -1;
        List<JVMClusterUtil.MasterThread> mts = cluster.getMasterThreads();
        for (int i = 0; i < mts.size(); i++) {
          if (mts.get(i).getMaster() == oldActive) {
            idx = i;
          }
        }
        System.out.println("SPECULA-MC2 CRASH active master index=" + idx + " "
            + oldActive.getServerName());
        cluster.abortMaster(idx);
        CRASHED.countDown();
        cluster.waitOnMaster(idx);
        System.out.println("SPECULA-MC2 CRASHED master thread exited; starting replacement master");
        JVMClusterUtil.MasterThread nm = cluster.startMaster();
        System.out.println("SPECULA-MC2 STARTED replacement master " + nm.getMaster().getServerName());
      } catch (Throwable t) {
        LOG.error("SPECULA-MC2 crasher failed", t);
      } finally {
        CRASHED.countDown();
      }
    }, "specula-mc2-crasher");
    crasher.setDaemon(true);
    crasher.start();

    ARMED.set(true);
    Throwable observed = null;
    long t0 = System.currentTimeMillis();
    try {
      // The client's single logical addColumn request (cf1 is NOT in the table yet).
      admin.addColumnFamily(TABLE_NAME, new HColumnDescriptor(FAMILY_1));
    } catch (Throwable t) {
      observed = t;
    }
    long elapsed = System.currentTimeMillis() - t0;
    crasher.join(TimeUnit.SECONDS.toMillis(60));

    assertTrue("new master should be active", cluster.waitForActiveAndReadyMaster(120000));
    HMaster newActive = cluster.getMaster();
    System.out.println("SPECULA-MC2 new active master=" + newActive.getServerName()
        + " (old=" + oldActive.getServerName() + ", oldAborted=" + oldActive.isAborted() + ")");
    System.out.println("SPECULA-MC2 addColumnFamily elapsedMs=" + elapsed);

    // Did the reloaded procedure finish the add on the new master?
    ProcedureExecutor<MasterProcedureEnv> pe = newActive.getMasterProcedureExecutor();
    long deadline = System.currentTimeMillis() + 60000;
    boolean allDone = false;
    while (System.currentTimeMillis() < deadline) {
      allDone = true;
      for (Procedure<?> p : pe.getProcedures()) {
        if (p instanceof ModifyTableProcedure && !p.isFinished()) {
          allDone = false;
        }
      }
      if (allDone) {
        break;
      }
      Thread.sleep(200);
    }
    for (Procedure<?> p : pe.getProcedures()) {
      if (p instanceof ModifyTableProcedure) {
        System.out.println("SPECULA-MC2 new-master procedure: " + p + " finished=" + p.isFinished()
            + " success=" + p.isSuccess());
      }
    }
    TableDescriptor finalTd = admin.getDescriptor(TABLE_NAME);
    System.out.println("SPECULA-MC2 final table families=" + finalTd.getColumnFamilyNames().size()
        + " hasCf1=" + finalTd.hasColumnFamily(FAMILY_1));

    if (observed == null) {
      System.out.println("SPECULA-MC2 RESULT: addColumnFamily SUCCEEDED (target not fired)");
      fail("addColumnFamily succeeded; TargetSafe not violated in this run");
    }
    System.out.println("SPECULA-MC2 RESULT: addColumnFamily threw " + observed.getClass().getName());
    System.out.println("SPECULA-MC2 EXCEPTION-BEGIN");
    observed.printStackTrace(System.out);
    System.out.println("SPECULA-MC2 EXCEPTION-END");

    assertTrue("expected InvalidFamilyOperationException, got " + observed,
        observed instanceof InvalidFamilyOperationException);
    String msg = String.valueOf(observed.getMessage());
    assertTrue("server frame HMaster.addColumn(HMaster.java:2255) expected in remote trace",
        msg.contains("org.apache.hadoop.hbase.master.HMaster.addColumn(HMaster.java:2255)"));
    assertTrue("cf1 was really added by the client's own (first) request",
        finalTd.hasColumnFamily(FAMILY_1));
    System.out.println("SPECULA-MC2 TARGET FIRED: InvalidFamilyOperationException from "
        + "HMaster.addColumn(HMaster.java:2255) on the new master, although the table now has cf1"
        + " via the client's own request");
    admin.deleteTable(TABLE_NAME);
  }

  private void verifyTableDescriptor(byte[]... families) throws IOException {
    TableDescriptor td = TEST_UTIL.getAdmin().getDescriptor(TABLE_NAME);
    assertEquals(families.length, td.getColumnFamilyNames().size());
    for (byte[] f : families) {
      assertNotNull(td.getColumnFamily(f));
    }
  }
}
