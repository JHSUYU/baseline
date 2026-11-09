/**
 * Specula CR-6 reproduction (hdfs-adhoc-24, target BlockPoolSliceStorage.java:421).
 *
 * Installed by repro/test_bugCR-6_rollback_missed_volume.sh as
 * hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/SpeculaAdhocCR6Test.java
 * in a pristine checkout at 734dd8a67cd. No main-source file is modified.
 *
 * Every test is a variant of the workload TestDFSUpgrade#testUpgrade (same module, same package):
 * the workload's own "Normal NameNode/DataNode upgrade" steps (NN started with UPGRADE, DN started
 * REGULAR over the old storage), followed by the documented rollback of TestDFSRollback
 * (NameNode.doRollback = "hdfs namenode -rollback", DataNode started with -rollback).
 * The storage is created by the system itself (fresh format, real writes); no VERSION file is
 * hand-written, so the guard operands (layoutVersion, cTime) are only ever written by HDFS code.
 *
 * Faults (all in the brief's fault model):
 *   - a volume offline during the DN -rollback start (DataNodeTestUtils.injectDataDirFailure, the
 *     codebase's own volume-failure utility; dfs.datanode.failed.volumes.tolerated = 1), later back
 *     and re-added by hot swap (DataNode#reconfigurePropertyImpl, what the ReconfigurationThread of
 *     "dfsadmin -reconfig datanode ... start" runs) or by a regular DN restart     [Level 0]
 *   - a DataNode crash right after BlockPoolSliceStorage.java:637 rename(current, removed.tmp):
 *     the DN runs in its own JVM (DataNode.main -rollback, i.e. "hdfs datanode -rollback"), a JDI
 *     breakpoint at L640 only pauses it there, and the JVM is killed with SIGKILL; the DN is then
 *     restarted with default options                                              [Level 1]
 *
 * Tests: a no-fault control; hot swap; regular restart with the stale volume listed last (the
 * NN rejects the DN's registration, which carries the stale cTime left in the shared
 * BlockPoolSliceStorage) or first (the stale slice is served and the NN's FinalizeCommand deletes
 * its previous/); the crash on the second and on the first volume. Each failing case ends with
 * the documented remedy, a DN restart with -rollback.
 *
 * Oracle: the IOException thrown by the statement "throw new IOException("Datanode state: LV = "..."
 * that starts at BlockPoolSliceStorage.java:421 (the statement spans L421-L424; javac maps its
 * constructor call to L424, see javap: pc 339 "new java/io/IOException" = line 421, pc 364
 * invokespecial <init> in the line-424 range), so its JVM frame reads
 * BlockPoolSliceStorage.doTransition(BlockPoolSliceStorage.java:424).
 */
package org.apache.hadoop.hdfs;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.FileWriter;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.io.PrintWriter;
import java.lang.management.ManagementFactory;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import com.sun.jdi.AbsentInformationException;
import com.sun.jdi.Bootstrap;
import com.sun.jdi.Location;
import com.sun.jdi.ReferenceType;
import com.sun.jdi.StackFrame;
import com.sun.jdi.ThreadReference;
import com.sun.jdi.VirtualMachine;
import com.sun.jdi.connect.AttachingConnector;
import com.sun.jdi.connect.Connector;
import com.sun.jdi.event.BreakpointEvent;
import com.sun.jdi.event.ClassPrepareEvent;
import com.sun.jdi.event.Event;
import com.sun.jdi.event.EventSet;
import com.sun.jdi.event.VMDeathEvent;
import com.sun.jdi.event.VMDisconnectEvent;
import com.sun.jdi.request.BreakpointRequest;
import com.sun.jdi.request.ClassPrepareRequest;
import com.sun.jdi.request.EventRequest;
import com.sun.jdi.request.EventRequestManager;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.conf.ReconfigurationException;
import org.apache.hadoop.fs.CommonConfigurationKeysPublic;
import org.apache.hadoop.fs.FileUtil;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.fs.SafeModeAction;
import org.apache.hadoop.hdfs.client.HdfsClientConfigKeys;
import org.apache.hadoop.hdfs.server.common.HdfsServerConstants.StartupOption;
import org.apache.hadoop.hdfs.server.common.Storage;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.hdfs.server.datanode.DataNodeTestUtils;
import org.apache.hadoop.hdfs.server.datanode.ReplicaNotFoundException;
import org.apache.hadoop.hdfs.server.datanode.fsdataset.FsDatasetSpi;
import org.apache.hadoop.hdfs.server.datanode.fsdataset.FsVolumeSpi;
import org.apache.hadoop.hdfs.server.namenode.NameNode;
import org.apache.hadoop.net.NetUtils;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class SpeculaAdhocCR6Test {
  private static final Logger LOG =
      LoggerFactory.getLogger(SpeculaAdhocCR6Test.class);

  private static final String TARGET_MSG = "Datanode state: LV = ";
  private static final String TARGET_FRAME =
      "org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage"
      + ".doTransition(BlockPoolSliceStorage.java:424)";
  private static final String BPSS =
      "org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage";
  /** First line after rename(curDir, tmpDir) at L637 in doRollback. */
  private static final int CRASH_LINE = 640;
  private static final int NUM_PRE = 4;
  private static final int NUM_POST = 4;

  private File base;
  private File nameDir;
  private File vol1;
  private File vol2;
  private Configuration conf;
  private MiniDFSCluster cluster;
  private String bpid;
  private long cTimeBeforeUpgrade;
  private long cTimeAfterUpgrade;
  private final Map<Path, Long> preBlocks = new LinkedHashMap<>();
  private final Map<Path, File> preVolume = new LinkedHashMap<>();
  private final Map<Path, Long> postBlocks = new LinkedHashMap<>();
  private final Map<Path, File> postVolume = new LinkedHashMap<>();

  @AfterEach
  public void tearDown() {
    if (cluster != null) {
      cluster.shutdown();
      cluster = null;
    }
  }

  private static void say(String fmt, Object... args) {
    String s = "[CR-6] " + String.format(fmt, args);
    System.out.println(s);
    LOG.info(s);
  }

  // ------------------------------------------------------------------ tests

  /** Control: the documented procedure without a fault never reaches L421. */
  @Test
  @Timeout(value = 300)
  public void testControlNoFault() throws Exception {
    setUp("control", true);
    formatAndWriteBeforeUpgrade();
    upgradeAndChangeData();
    rollbackNameNode();
    say("Phase D: DN started with -rollback, all volumes online");
    LogCapturer logs = LogCapturer.captureLogs(Storage.LOG);
    cluster = new MiniDFSCluster.Builder(conf).numDataNodes(0).format(false)
        .manageDataDfsDirs(false).manageNameDfsDirs(false)
        .dnStartupOption(StartupOption.ROLLBACK).build();
    cluster.startDataNodes(conf, 1, false, StartupOption.ROLLBACK, null);
    cluster.waitActive();
    say("Phase E: DN restarted with default options");
    cluster.stopDataNode(0);
    cluster.startDataNodes(conf, 1, false, StartupOption.REGULAR, null);
    cluster.waitActive();
    logs.stopCapturing();
    DataNode dn = cluster.getDataNodes().get(0);
    say("control: BP alive=%s, %s; NN cTime=%d, L421 message logged=%s",
        dn.isBPServiceAlive(bpid), describeAll(), nnCTime(),
        logs.getOutput().contains(TARGET_MSG));
    assertFalse(logs.getOutput().contains(TARGET_MSG));
    assertTrue(dn.isBPServiceAlive(bpid));
    waitSafeModeOff();
    DistributedFileSystem fs = cluster.getFileSystem();
    for (Path p : preBlocks.keySet()) {
      DFSTestUtil.readFile(fs, p);
    }
    say("control: all %d files restored by the rollback are readable",
        preBlocks.size());
  }

  /** 2b, offline form: the volume misses the -rollback start, then hot swap. */
  @Test
  @Timeout(value = 300)
  public void testVolumeOfflineAtDnRollbackThenHotSwap() throws Exception {
    setUp("hotswap", true);
    formatAndWriteBeforeUpgrade();
    upgradeAndChangeData();
    rollbackNameNode();
    startDnRollbackWithVolumeOffline(vol2);
    final DataNode dn = cluster.getDataNodes().get(0);

    // DataNode#reconfigurePropertyImpl is what "dfsadmin -reconfig datanode
    // <host:ipc> start" runs (ReconfigurableBase.ReconfigurationThread) and
    // what TestDataNodeHotSwapVolumes calls.
    say("Phase E: the disk %s is back; re-add it by hot swap"
        + " (DataNode#reconfigurePropertyImpl %s=%s)", vol2,
        DFSConfigKeys.DFS_DATANODE_DATA_DIR_KEY,
        conf.get(DFSConfigKeys.DFS_DATANODE_DATA_DIR_KEY));
    DataNodeTestUtils.restoreDataDirFromFailure(vol2);
    say("before hot swap: %s; NN cTime=%d", describe(vol2), nnCTime());
    LogCapturer logs = LogCapturer.captureLogs(Storage.LOG);
    ReconfigurationException re = assertThrows(
        ReconfigurationException.class,
        () -> dn.reconfigurePropertyImpl(
            DFSConfigKeys.DFS_DATANODE_DATA_DIR_KEY,
            conf.get(DFSConfigKeys.DFS_DATANODE_DATA_DIR_KEY)));
    logs.stopCapturing();
    say("hot swap failed: %s", re.getCause());
    checkTargetEvidence(logs.getOutput());

    FsDatasetSpi<?> ds = DataNodeTestUtils.getFSDataset(dn);
    List<String> served = servedVolumes(ds);
    say("after hot swap: volumes in service %s, failed volumes %d",
        served, ds.getNumFailedVolumes());
    assertFalse(served.contains(vol2.getAbsolutePath()));
    checkFilesUnreadable(filesOn(vol2), true);
    say("after the failed hot swap: %s (previous/ kept: the volume is not in"
        + " DataStorage, so DNA_FINALIZE does not reach it)", describe(vol2));
    assertTrue(new File(bpRoot(vol2), "previous").isDirectory());
  }

  /**
   * 2b, offline form, regular restart, the offline volume listed last: the
   * failed L421 load leaves the upgraded cTime in the shared
   * BlockPoolSliceStorage, the DN registers with it, and the NN rejects the
   * block pool service of the whole DataNode.
   */
  @Test
  @Timeout(value = 300)
  public void testLastVolumeOfflineAtDnRollbackThenRegularRestart()
      throws Exception {
    setUp("restart-last", true);
    formatAndWriteBeforeUpgrade();
    upgradeAndChangeData();
    rollbackNameNode();
    startDnRollbackWithVolumeOffline(vol2);
    say("Phase E: DN stopped; the disk %s is back; DN restarted with"
        + " default options", vol2);
    cluster.stopDataNode(0);
    DataNodeTestUtils.restoreDataDirFromFailure(vol2);
    restartRegularExpectBlockPoolRejected(vol2);
    operatorRestartsDnWithRollback(vol2, true);
  }

  /**
   * 2b, offline form, regular restart, the offline volume listed first: the
   * stale slice is served, and the FinalizeCommand of the rolled-back NN
   * deletes its previous/, the only copy of replicas the rollback restored.
   */
  @Test
  @Timeout(value = 300)
  public void testFirstVolumeOfflineAtDnRollbackThenRegularRestart()
      throws Exception {
    setUp("restart-first", true);
    formatAndWriteBeforeUpgrade();
    upgradeAndChangeData();
    rollbackNameNode();
    startDnRollbackWithVolumeOffline(vol1);
    say("Phase E: DN stopped; the disk %s is back; DN restarted with"
        + " default options", vol1);
    cluster.stopDataNode(0);
    DataNodeTestUtils.restoreDataDirFromFailure(vol1);
    restartRegularExpectStaleVolumeServedAndFinalized(vol1);
    operatorRestartsDnWithRollback(vol1, false);
  }

  /** 2b, crash form: crash after L637 on the second volume, default restart. */
  @Test
  @Timeout(value = 400)
  public void testDnCrashAfterRemovedTmpRenameThenDefaultRestart()
      throws Exception {
    runCrashScenario("crash2", 2);
    restartRegularExpectBlockPoolRejected(vol2);
    operatorRestartsDnWithRollback(vol2, true);
  }

  /** 2b, crash form: crash after L637 on the first volume, default restart. */
  @Test
  @Timeout(value = 400)
  public void testDnCrashOnFirstVolumeThenDefaultRestart() throws Exception {
    runCrashScenario("crash1", 1);
    say("Phase E': DN restarted with default options (supervisor restart)");
    LogCapturer logs = LogCapturer.captureLogs(Storage.LOG);
    LogCapturer dnLogs = LogCapturer.captureLogs(DataNode.LOG);
    cluster.startDataNodes(conf, 1, false, StartupOption.REGULAR, null);
    final DataNode dn = cluster.getDataNodes().get(0);
    GenericTestUtils.waitFor(() -> !dn.isBPServiceAlive(bpid), 100, 60000);
    logs.stopCapturing();
    dnLogs.stopCapturing();
    printLines(logs.getOutput(), "from previous rollback");
    checkTargetEvidence(logs.getOutput());
    printLines(dnLogs.getOutput(), "Initialization failed");
    say("after the restart: %s; NN cTime=%d", describeAll(), nnCTime());
    say("block pool %s alive on the restarted DN: %s", bpid,
        dn.isBPServiceAlive(bpid));
    assertFalse(dn.isBPServiceAlive(bpid));
    assertEquals(cTimeAfterUpgrade, bpCTime(vol1, "current"));
    assertEquals(cTimeAfterUpgrade, bpCTime(vol2, "current"));
    operatorRestartsDnWithRollback(vol1, true);
  }

  // ---------------------------------------------------------------- phases

  private void setUp(String name, boolean tolerateOneFailedVolume)
      throws IOException {
    say("==== %s ====", name);
    base = GenericTestUtils.getTestDir("specula-cr6-" + name);
    FileUtil.fullyDelete(base);
    nameDir = new File(base, "name1");
    vol1 = new File(base, "data1");
    vol2 = new File(base, "data2");
    conf = new HdfsConfiguration();
    conf.set(DFSConfigKeys.DFS_NAMENODE_NAME_DIR_KEY,
        nameDir.getAbsolutePath());
    conf.set(DFSConfigKeys.DFS_NAMENODE_EDITS_DIR_KEY,
        nameDir.getAbsolutePath());
    conf.set(DFSConfigKeys.DFS_DATANODE_DATA_DIR_KEY,
        vol1.getAbsolutePath() + "," + vol2.getAbsolutePath());
    // as TestDFSUpgrade#testUpgrade and TestDFSRollback#testRollback
    conf.setBoolean(DFSConfigKeys.DFS_DATANODE_DUPLICATE_REPLICA_DELETION,
        false);
    conf.setInt(DFSConfigKeys.DFS_DATANODE_SCAN_PERIOD_HOURS_KEY, -1);
    conf.setLong(DFSConfigKeys.DFS_HEARTBEAT_INTERVAL_KEY, 1);
    conf.setInt(HdfsClientConfigKeys.Retry.WINDOW_BASE_KEY, 10);
    if (tolerateOneFailedVolume) {
      conf.setInt(DFSConfigKeys.DFS_DATANODE_FAILED_VOLUMES_TOLERATED_KEY, 1);
    }
  }

  private void formatAndWriteBeforeUpgrade() throws Exception {
    say("Phase A: format a cluster (1 NN, 1 DN, volumes %s, %s), write %d"
        + " files", vol1, vol2, NUM_PRE);
    cluster = new MiniDFSCluster.Builder(conf).numDataNodes(0).format(true)
        .manageNameDfsDirs(false).manageDataDfsDirs(false).build();
    cluster.startDataNodes(conf, 1, false, StartupOption.REGULAR, null);
    cluster.waitActive();
    waitSafeModeOff();
    bpid = cluster.getNamesystem().getBlockPoolId();
    cTimeBeforeUpgrade = nnCTime();
    DistributedFileSystem fs = cluster.getFileSystem();
    for (int i = 0; i < NUM_PRE; i++) {
      Path p = new Path("/pre-" + i);
      DFSTestUtil.createFile(fs, p, 4096, (short) 1, 1000L + i);
      preBlocks.put(p, DFSTestUtil.getFirstBlock(fs, p).getBlockId());
    }
    cluster.shutdown();
    cluster = null;
    for (Map.Entry<Path, Long> e : preBlocks.entrySet()) {
      preVolume.put(e.getKey(), volumeHolding(e.getValue(), "current"));
    }
    say("C0 = NN cTime at format = %d, bpid=%s; vol1 BP %s cTime=%d,"
        + " vol2 BP %s cTime=%d", cTimeBeforeUpgrade, bpid, layout(vol1),
        bpCTime(vol1, "current"), layout(vol2), bpCTime(vol2, "current"));
    say("pre-upgrade files: %s", placement(preBlocks, preVolume));
    assertNotNull(volumeOf(preVolume, vol1), "a pre-upgrade block on vol1");
    assertNotNull(volumeOf(preVolume, vol2), "a pre-upgrade block on vol2");
  }

  private void upgradeAndChangeData() throws Exception {
    say("Phase B: NN started with -upgrade, DN started REGULAR (the"
        + " workload's 'Normal DataNode upgrade'); write %d files, delete"
        + " the %d old ones", NUM_POST, NUM_PRE);
    cluster = new MiniDFSCluster.Builder(conf).numDataNodes(0).format(false)
        .manageDataDfsDirs(false).manageNameDfsDirs(false)
        .startupOption(StartupOption.UPGRADE).build();
    cluster.startDataNodes(conf, 1, false, StartupOption.REGULAR, null);
    cluster.waitActive();
    waitSafeModeOff();
    cTimeAfterUpgrade = nnCTime();
    assertTrue(cTimeAfterUpgrade > cTimeBeforeUpgrade);
    for (File v : new File[] {vol1, vol2}) {
      assertEquals(cTimeAfterUpgrade, bpCTime(v, "current"));
      assertEquals(cTimeBeforeUpgrade, bpCTime(v, "previous"));
    }
    DistributedFileSystem fs = cluster.getFileSystem();
    for (int i = 0; i < NUM_POST; i++) {
      Path p = new Path("/post-" + i);
      DFSTestUtil.createFile(fs, p, 4096, (short) 1, 2000L + i);
      postBlocks.put(p, DFSTestUtil.getFirstBlock(fs, p).getBlockId());
    }
    for (Path p : preBlocks.keySet()) {
      assertTrue(fs.delete(p, false));
    }
    GenericTestUtils.waitFor(() -> preBlocks.values().stream()
        .allMatch(id -> volumeHolding(id, "current") == null), 100, 60000);
    cluster.shutdown();
    cluster = null;
    for (Map.Entry<Path, Long> e : postBlocks.entrySet()) {
      postVolume.put(e.getKey(), volumeHolding(e.getValue(), "current"));
    }
    for (Map.Entry<Path, Long> e : preBlocks.entrySet()) {
      assertTrue(hasBlockFile(preVolume.get(e.getKey()), "previous",
          e.getValue()));
    }
    say("C1 = NN cTime after upgrade = %d; vol1 BP %s, vol2 BP %s (current"
        + " cTime=%d, previous cTime=%d)", cTimeAfterUpgrade, layout(vol1),
        layout(vol2), bpCTime(vol2, "current"), bpCTime(vol2, "previous"));
    say("post-upgrade files: %s; old replicas now only in previous/",
        placement(postBlocks, postVolume));
  }

  private void rollbackNameNode() throws Exception {
    say("Phase C: NN rollback (NameNode.doRollback = hdfs namenode -rollback)");
    NameNode.doRollback(conf, false);
  }

  private void startDnRollbackWithVolumeOffline(File offline) throws Exception {
    File online = offline.equals(vol1) ? vol2 : vol1;
    say("Phase D: disk %s offline (DataNodeTestUtils.injectDataDirFailure);"
        + " DN started with -rollback", offline);
    DataNodeTestUtils.injectDataDirFailure(offline);
    cluster = new MiniDFSCluster.Builder(conf).numDataNodes(0).format(false)
        .manageDataDfsDirs(false).manageNameDfsDirs(false)
        .dnStartupOption(StartupOption.ROLLBACK).build();
    cluster.startDataNodes(conf, 1, false, StartupOption.ROLLBACK, null);
    cluster.waitActive();
    DataNode dn = cluster.getDataNodes().get(0);
    assertEquals(cTimeBeforeUpgrade, nnCTime());
    assertTrue(dn.isBPServiceAlive(bpid));
    assertEquals(cTimeBeforeUpgrade, bpCTime(online, "current"));
    assertFalse(new File(bpRoot(online), "previous").exists());
    say("after the -rollback start: NN cTime=%d; %s (rolled back); %s skipped"
        + " (failed volumes=%d)", nnCTime(), describe(online),
        offline.getName(),
        DataNodeTestUtils.getFSDataset(dn).getNumFailedVolumes());
  }

  /**
   * NN up after its rollback; the DN is started with -rollback in its own
   * JVM and killed with SIGKILL right after rename(current, removed.tmp) of
   * the crashAtHit-th volume.
   */
  private void runCrashScenario(String name, int crashAtHit) throws Exception {
    setUp(name, false);
    formatAndWriteBeforeUpgrade();
    upgradeAndChangeData();
    rollbackNameNode();
    say("Phase D: NN restarted after its rollback; DN started with -rollback"
        + " in its own JVM (DataNode.main -rollback)");
    cluster = new MiniDFSCluster.Builder(conf).numDataNodes(0).format(false)
        .manageDataDfsDirs(false).manageNameDfsDirs(false).build();
    cluster.waitActive();
    assertEquals(cTimeBeforeUpgrade, nnCTime());
    File crashed = crashAtHit == 1 ? vol1 : vol2;
    crashChildDataNodeDuringRollback(crashAtHit, crashed);
    say("after the crash: %s", describeAll());
    assertTrue(new File(bpRoot(crashed), "removed.tmp").isDirectory());
    assertFalse(new File(bpRoot(crashed), "current").exists());
    assertTrue(new File(bpRoot(crashed), "previous").isDirectory());
  }

  /**
   * Default restart with the stale volume loaded after a healthy one. L421
   * fires for it; the upgraded cTime it read at L388 stays in the shared
   * BlockPoolSliceStorage, DataNode#createBPRegistration sends it, and the NN
   * rejects the heartbeat (registration ID mismatch): the block pool service
   * of the whole DN ends.
   */
  private void restartRegularExpectBlockPoolRejected(File stale)
      throws Exception {
    say("before the restart: %s", describeAll());
    say("Phase E': DN started with default options");
    LogCapturer storageLogs = LogCapturer.captureLogs(Storage.LOG);
    LogCapturer nnLogs = LogCapturer.captureLogs(NameNode.LOG);
    LogCapturer dnLogs = LogCapturer.captureLogs(DataNode.LOG);
    cluster.startDataNodes(conf, 1, false, StartupOption.REGULAR, null);
    final DataNode dn =
        cluster.getDataNodes().get(cluster.getDataNodes().size() - 1);
    GenericTestUtils.waitFor(() -> !dn.isBPServiceAlive(bpid), 100, 60000);
    storageLogs.stopCapturing();
    nnLogs.stopCapturing();
    dnLogs.stopCapturing();
    String st = storageLogs.getOutput();
    printLines(st, "from previous rollback");
    checkTargetEvidence(st);
    printLines(dnLogs.getOutput(), "successfully registered");
    printLines(nnLogs.getOutput(), "Registration IDs mismatched");
    printLines(dnLogs.getOutput(), "is shutting down");
    printLines(dnLogs.getOutput(), "Ending block pool service");
    assertTrue(nnLogs.getOutput().contains("Registration IDs mismatched: the"
        + " DatanodeRegistration ID is NS-"));
    assertTrue(nnLogs.getOutput().contains("-" + cTimeAfterUpgrade
        + " but the expected ID is"));
    say("block pool %s alive on the restarted DN: %s; %s; NN cTime=%d", bpid,
        dn.isBPServiceAlive(bpid), describeAll(), nnCTime());
    assertFalse(dn.isBPServiceAlive(bpid));
    assertEquals(cTimeAfterUpgrade, bpCTime(stale, "current"));
    assertTrue(new File(bpRoot(stale), "previous").isDirectory());
    checkFilesUnreadable(preBlocks.keySet(), false);
  }

  /**
   * Default restart with the stale volume loaded before a healthy one. L421
   * fires for it, the exception is only logged, the volume stays in service
   * with its upgraded slice, and the FinalizeCommand that the rolled-back NN
   * returns for the block report deletes the volume's previous/.
   */
  private void restartRegularExpectStaleVolumeServedAndFinalized(File stale)
      throws Exception {
    List<Path> onlyInStalePrevious = filesOn(stale);
    for (Path p : onlyInStalePrevious) {
      assertTrue(hasBlockFile(stale, "previous", preBlocks.get(p)));
    }
    say("before the restart: %s; the only replicas of %s (files of the"
        + " rolled-back namespace) are in %s BP previous/", describeAll(),
        onlyInStalePrevious, stale.getName());
    say("Phase E': DN started with default options");
    LogCapturer storageLogs = LogCapturer.captureLogs(Storage.LOG);
    LogCapturer dnLogs = LogCapturer.captureLogs(DataNode.LOG);
    cluster.startDataNodes(conf, 1, false, StartupOption.REGULAR, null);
    cluster.waitActive();
    final DataNode dn =
        cluster.getDataNodes().get(cluster.getDataNodes().size() - 1);
    checkTargetEvidence(storageLogs.getOutput());
    assertTrue(dn.isBPServiceAlive(bpid));
    FsDatasetSpi<?> ds = DataNodeTestUtils.getFSDataset(dn);
    List<String> served = servedVolumes(ds);
    say("volumes in service: %s, failed volumes: %d", served,
        ds.getNumFailedVolumes());
    assertTrue(served.contains(stale.getAbsolutePath()));
    assertEquals(0, ds.getNumFailedVolumes());
    for (Map.Entry<Path, Long> e : postBlocks.entrySet()) {
      if (stale.equals(postVolume.get(e.getKey()))) {
        say("DN replica map: %s (written after the upgrade, unknown to the"
            + " rolled-back namespace) blk_%d in replica map: %s", e.getKey(),
            e.getValue(), inReplicaMap(ds, e.getValue()));
      }
    }

    GenericTestUtils.waitFor(
        () -> !new File(bpRoot(stale), "previous").exists()
            && !new File(bpRoot(stale), "finalized.tmp").exists(),
        100, 60000);
    storageLogs.stopCapturing();
    dnLogs.stopCapturing();
    printLines(dnLogs.getOutput(), "Got finalize command");
    printLines(storageLogs.getOutput(), "Finalizing upgrade for storage");
    printLines(storageLogs.getOutput(), "Finalize upgrade for");
    say("after the finalize: %s; NN cTime=%d", describeAll(), nnCTime());
    assertEquals(cTimeAfterUpgrade, bpCTime(stale, "current"));
    for (Path p : onlyInStalePrevious) {
      long id = preBlocks.get(p);
      boolean onDisk = find(vol1, "blk_" + id) != null
          || find(vol2, "blk_" + id) != null;
      say("replica of %s (blk_%d) still anywhere on the DN's disks: %s", p,
          id, onDisk);
      assertFalse(onDisk);
      assertFalse(inReplicaMap(ds, id));
    }
    checkFilesUnreadable(onlyInStalePrevious, true);
  }

  /** The documented remedy: restart the DN with -rollback. */
  private void operatorRestartsDnWithRollback(File stale,
      boolean expectRecovered) throws Exception {
    say("Phase F: the operator restarts the DN with -rollback");
    cluster.stopDataNode(0);
    LogCapturer logs = LogCapturer.captureLogs(Storage.LOG);
    cluster.startDataNodes(conf, 1, false, StartupOption.ROLLBACK, null);
    cluster.waitActive();
    final DataNode dn = cluster.getDataNodes().get(0);
    final DistributedFileSystem fs = cluster.getFileSystem();
    if (expectRecovered) {
      GenericTestUtils.waitFor(() -> allReadable(fs), 500, 60000);
      logs.stopCapturing();
      say("after the -rollback restart: %s; L421 logged: %s; BP alive: %s;"
          + " all %d files readable", describeAll(),
          logs.getOutput().contains(TARGET_MSG), dn.isBPServiceAlive(bpid),
          preBlocks.size());
      assertFalse(logs.getOutput().contains(TARGET_MSG));
    } else {
      cluster.triggerBlockReports();
      Thread.sleep(2000);
      logs.stopCapturing();
      checkTargetEvidence(logs.getOutput());
      say("after the -rollback restart: %s (no previous/ left on %s)",
          describeAll(), stale.getName());
      for (final Path p : filesOn(stale)) {
        IOException ioe = assertThrows(IOException.class,
            () -> DFSTestUtil.readFile(fs, p));
        say("after the -rollback restart, read %s: %s", p,
            ioe.getClass().getSimpleName());
      }
      say("NN missing blocks: %d",
          cluster.getNamesystem().getMissingBlocksCount());
    }
  }

  private boolean inReplicaMap(FsDatasetSpi<?> ds, long blockId)
      throws IOException {
    try {
      return ds.getStoredBlock(bpid, blockId) != null;
    } catch (ReplicaNotFoundException e) {
      return false;
    }
  }

  private boolean allReadable(DistributedFileSystem fs) {
    try {
      for (Path p : preBlocks.keySet()) {
        DFSTestUtil.readFile(fs, p);
      }
      return true;
    } catch (IOException e) {
      return false;
    }
  }

  private static void printLines(String log, String needle) {
    for (String l : log.split("\n")) {
      if (l.contains(needle)) {
        say("  log| %s", l.length() > 420 ? l.substring(0, 420) : l);
      }
    }
  }

  private void checkFilesUnreadable(Collection<Path> expectMissing,
      boolean checkMissingCount) throws Exception {
    final DistributedFileSystem fs = cluster.getFileSystem();
    cluster.triggerBlockReports();
    Thread.sleep(2000);
    say("NN safe mode: %s; status: %s", cluster.getNameNode().isInSafeMode(),
        cluster.getNamesystem().getSafemode().replace('\n', ' '));
    if (cluster.getNameNode().isInSafeMode()) {
      say("operator forces the NN out of safe mode (dfsadmin -safemode"
          + " leave)");
      fs.setSafeMode(SafeModeAction.LEAVE);
    }
    if (cluster.getNameNode().isInSafeMode()) {
      // BlockManagerSafeMode refuses "leave" while blocks with future
      // generation stamps are reported, and its status tells the operator
      // that during a rollback it is safe to use -safemode forceExit.
      say("NN refused 'leave' (blocks with future generation stamps were"
          + " reported); operator follows the NN's advice for a rollback:"
          + " dfsadmin -safemode forceExit");
      fs.setSafeMode(SafeModeAction.FORCE_EXIT);
    }
    assertFalse(cluster.getNameNode().isInSafeMode());
    for (Map.Entry<Path, Long> e : preBlocks.entrySet()) {
      final Path p = e.getKey();
      String where = preVolume.get(p).getName();
      if (expectMissing.contains(p)) {
        IOException ioe = assertThrows(IOException.class,
            () -> DFSTestUtil.readFile(fs, p));
        String msg = String.valueOf(ioe.getMessage()).replace('\n', ' ');
        say("read %s (in the rolled-back namespace; replica on %s): %s: %s",
            p, where, ioe.getClass().getSimpleName(),
            msg.length() > 240 ? msg.substring(0, 240) : msg);
      } else {
        DFSTestUtil.readFile(fs, p);
        say("read %s (replica on %s): OK", p, where);
      }
    }
    if (checkMissingCount) {
      final int expected = expectMissing.size();
      GenericTestUtils.waitFor(
          () -> cluster.getNamesystem().getMissingBlocksCount() == expected,
          200, 30000);
      say("NN missing blocks: %d (expected %d)",
          cluster.getNamesystem().getMissingBlocksCount(), expected);
    }
  }

  private List<Path> filesOn(File vol) {
    List<Path> out = new ArrayList<>();
    for (Map.Entry<Path, File> e : preVolume.entrySet()) {
      if (vol.equals(e.getValue())) {
        out.add(e.getKey());
      }
    }
    return out;
  }

  private String describe(File vol) {
    StringBuilder sb = new StringBuilder(vol.getName()).append(" BP ")
        .append(layout(vol));
    for (String d : new String[] {"current", "previous", "removed.tmp"}) {
      File v = new File(new File(bpRoot(vol), d), "VERSION");
      if (v.isFile()) {
        Properties p = new Properties();
        try (InputStream in = new FileInputStream(v)) {
          p.load(in);
          sb.append(' ').append(d).append(".cTime=")
              .append(p.getProperty("cTime"));
        } catch (IOException e) {
          sb.append(' ').append(d).append(".cTime=?");
        }
      }
    }
    return sb.toString();
  }

  private String describeAll() {
    return describe(vol1) + "; " + describe(vol2);
  }

  // ------------------------------------------------------ crash (Level 1)

  private void crashChildDataNodeDuringRollback(int crashAtHit, File expectVol)
      throws Exception {
    File childDir = new File(base, "child-dn");
    File childConf = new File(childDir, "conf");
    assertTrue(childConf.mkdirs());
    Configuration dnConf = new HdfsConfiguration(conf);
    NameNode nn = cluster.getNameNode();
    dnConf.set(CommonConfigurationKeysPublic.FS_DEFAULT_NAME_KEY,
        "hdfs://" + NetUtils.getHostPortString(nn.getNameNodeAddress()));
    dnConf.set(DFSConfigKeys.DFS_NAMENODE_RPC_ADDRESS_KEY,
        NetUtils.getHostPortString(nn.getNameNodeAddress()));
    dnConf.set(DFSConfigKeys.DFS_NAMENODE_SERVICE_RPC_ADDRESS_KEY,
        NetUtils.getHostPortString(nn.getServiceRpcAddress()));
    dnConf.set(DFSConfigKeys.DFS_DATANODE_ADDRESS_KEY, "127.0.0.1:0");
    dnConf.set(DFSConfigKeys.DFS_DATANODE_HTTP_ADDRESS_KEY, "127.0.0.1:0");
    dnConf.set(DFSConfigKeys.DFS_DATANODE_IPC_ADDRESS_KEY, "127.0.0.1:0");
    dnConf.set(DFSConfigKeys.DFS_DATANODE_HOST_NAME_KEY, "127.0.0.1");
    try (OutputStream out =
        new FileOutputStream(new File(childConf, "hdfs-site.xml"))) {
      dnConf.writeXml(out);
    }

    List<String> cmd = new ArrayList<>();
    cmd.add(System.getProperty("java.home") + File.separator + "bin"
        + File.separator + "java");
    List<String> jvmArgs =
        ManagementFactory.getRuntimeMXBean().getInputArguments();
    for (int i = 0; i < jvmArgs.size(); i++) {
      String a = jvmArgs.get(i);
      if (a.equals("--add-opens") || a.equals("--add-exports")) {
        cmd.add(a);
        cmd.add(jvmArgs.get(++i));
      } else if (a.startsWith("--add-opens=") || a.startsWith("--add-exports=")
          || a.startsWith("-Djava.net.preferIPv4Stack")) {
        cmd.add(a);
      }
    }
    cmd.add("-Xmx1g");
    cmd.add("-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,"
        + "address=127.0.0.1:0");
    cmd.add("-cp");
    cmd.add(childConf.getAbsolutePath() + File.pathSeparator
        + System.getProperty("java.class.path"));
    cmd.add("org.apache.hadoop.hdfs.server.datanode.DataNode");
    cmd.add("-rollback");
    say("child DataNode command: java ... -agentlib:jdwp=...suspend=y ..."
        + " org.apache.hadoop.hdfs.server.datanode.DataNode -rollback");
    final File childLog = new File(childDir, "datanode.log");
    final Process proc = new ProcessBuilder(cmd).redirectErrorStream(true)
        .start();
    final AtomicInteger port = new AtomicInteger(-1);
    final CountDownLatch portSeen = new CountDownLatch(1);
    Thread pump = new Thread(() -> {
      try (BufferedReader r = new BufferedReader(new InputStreamReader(
          proc.getInputStream(), StandardCharsets.UTF_8));
          PrintWriter w = new PrintWriter(new FileWriter(childLog))) {
        String line;
        while ((line = r.readLine()) != null) {
          w.println(line);
          w.flush();
          if (port.get() < 0
              && line.contains("Listening for transport dt_socket at address:")) {
            port.set(Integer.parseInt(
                line.substring(line.lastIndexOf(':') + 1).trim()));
            portSeen.countDown();
          }
        }
      } catch (IOException ignored) {
        // child gone
      }
    }, "child-dn-output");
    pump.setDaemon(true);
    pump.start();
    try {
      assertTrue(portSeen.await(60, TimeUnit.SECONDS),
          "child JVM did not open its JDWP port");
      AttachingConnector socket = null;
      for (AttachingConnector c :
          Bootstrap.virtualMachineManager().attachingConnectors()) {
        if ("com.sun.jdi.SocketAttach".equals(c.name())) {
          socket = c;
        }
      }
      assertNotNull(socket);
      Map<String, Connector.Argument> args = socket.defaultArguments();
      args.get("hostname").setValue("127.0.0.1");
      args.get("port").setValue(Integer.toString(port.get()));
      VirtualMachine vm = socket.attach(args);
      EventRequestManager erm = vm.eventRequestManager();
      ClassPrepareRequest cpr = erm.createClassPrepareRequest();
      cpr.addClassFilter(BPSS);
      cpr.setSuspendPolicy(EventRequest.SUSPEND_ALL);
      cpr.enable();
      vm.resume();

      int hits = 0;
      boolean crashed = false;
      long deadline = System.currentTimeMillis() + 180000;
      while (!crashed) {
        long left = deadline - System.currentTimeMillis();
        if (left <= 0) {
          fail("breakpoint hit #" + crashAtHit + " not reached; hits=" + hits);
        }
        EventSet set = vm.eventQueue().remove(left);
        if (set == null) {
          continue;
        }
        for (Event ev : set) {
          if (ev instanceof ClassPrepareEvent) {
            ReferenceType rt = ((ClassPrepareEvent) ev).referenceType();
            List<Location> locs = rt.locationsOfLine(CRASH_LINE);
            assertEquals(1, locs.size());
            BreakpointRequest br = erm.createBreakpointRequest(locs.get(0));
            br.setSuspendPolicy(EventRequest.SUSPEND_ALL);
            br.enable();
            say("JDI: breakpoint at %s.%s line %d", rt.name(),
                locs.get(0).method().name(), locs.get(0).lineNumber());
          } else if (ev instanceof BreakpointEvent) {
            BreakpointEvent be = (BreakpointEvent) ev;
            hits++;
            say("JDI: DataNode paused, hit #%d at %s.%s:%d (L637"
                + " rename(current, removed.tmp) done); stack:%n%s", hits,
                be.location().declaringType().name(),
                be.location().method().name(), be.location().lineNumber(),
                stack(be.thread()));
            say("on disk now: vol1 BP %s ; vol2 BP %s", layout(vol1),
                layout(vol2));
            if (hits == crashAtHit) {
              assertTrue(new File(bpRoot(expectVol), "removed.tmp").isDirectory());
              say("CRASH: SIGKILL the DataNode JVM pid %d inside"
                  + " BlockPoolSliceStorage.doRollback (volume %s)",
                  proc.pid(), expectVol);
              proc.destroyForcibly();
              assertTrue(proc.waitFor(60, TimeUnit.SECONDS));
              say("DataNode JVM exit value %d", proc.exitValue());
              crashed = true;
              break;
            }
          } else if (ev instanceof VMDeathEvent
              || ev instanceof VMDisconnectEvent) {
            fail("DataNode JVM ended before the crash point; hits=" + hits);
          }
        }
        if (!crashed) {
          set.resume();
        }
      }
      try {
        vm.dispose();
      } catch (RuntimeException ignored) {
        // the VM is gone
      }
    } finally {
      if (proc.isAlive()) {
        proc.destroyForcibly();
        proc.waitFor(60, TimeUnit.SECONDS);
      }
      pump.join(10000);
      say("child DataNode log (%s), rollback lines:", childLog);
      for (String l : java.nio.file.Files.readAllLines(childLog.toPath())) {
        if (l.contains("Rolling back storage directory")
            || l.contains("Rollback of") || l.contains("Layout version rolled")
            || l.contains("STARTUP_MSG:   args")
            || l.contains("Listening for transport")) {
          System.out.println("    [child-dn] " + l);
        }
      }
    }
  }

  private static String stack(ThreadReference t) throws Exception {
    StringBuilder sb = new StringBuilder();
    int n = 0;
    for (StackFrame f : t.frames()) {
      Location l = f.location();
      String src;
      try {
        src = l.sourceName();
      } catch (AbsentInformationException e) {
        src = "?";
      }
      sb.append("        at ").append(l.declaringType().name()).append('.')
          .append(l.method().name()).append('(').append(src).append(':')
          .append(l.lineNumber()).append(")\n");
      if (++n >= 16) {
        break;
      }
    }
    return sb.toString();
  }

  // --------------------------------------------------------------- helpers

  private void checkTargetEvidence(String captured) {
    String[] lines = captured.split("\n");
    List<String> shown = new ArrayList<>();
    for (int i = 0; i < lines.length && shown.size() < 2; i++) {
      if (lines[i].contains(TARGET_MSG)) {
        StringBuilder sb = new StringBuilder();
        for (int j = Math.max(0, i - 1);
             j < Math.min(lines.length, i + 10); j++) {
          sb.append("    ").append(lines[j]).append('\n');
        }
        if (!shown.contains(sb.toString())) {
          shown.add(sb.toString());
          say("TARGET exception (excerpt %d):%n%s", shown.size(), sb);
        }
      }
    }
    assertTrue(captured.contains(TARGET_MSG), "L421 exception not logged");
    assertTrue(captured.contains(TARGET_FRAME), "L421 frame not logged");
  }

  private long nnCTime() throws IOException {
    return cluster.getNameNodeRpc().versionRequest().getCTime();
  }

  private void waitSafeModeOff() throws Exception {
    GenericTestUtils.waitFor(() -> !cluster.getNameNode().isInSafeMode(),
        100, 60000);
  }

  private File bpRoot(File vol) {
    return new File(vol, "current" + File.separator + bpid);
  }

  private long bpCTime(File vol, String sub) throws IOException {
    Properties p = new Properties();
    try (InputStream in = new FileInputStream(
        new File(new File(bpRoot(vol), sub), "VERSION"))) {
      p.load(in);
    }
    return Long.parseLong(p.getProperty("cTime"));
  }

  private String layout(File vol) {
    List<String> present = new ArrayList<>();
    for (String d : new String[] {"current", "previous", "previous.tmp",
        "removed.tmp", "finalized.tmp"}) {
      if (new File(bpRoot(vol), d).exists()) {
        present.add(d);
      }
    }
    return present.toString();
  }

  private boolean hasBlockFile(File vol, String sub, long blockId) {
    return find(new File(new File(bpRoot(vol), sub), "finalized"),
        "blk_" + blockId) != null;
  }

  private File volumeHolding(long blockId, String sub) {
    for (File v : new File[] {vol1, vol2}) {
      if (hasBlockFile(v, sub, blockId)) {
        return v;
      }
    }
    return null;
  }

  private static File find(File dir, String name) {
    File[] kids = dir.listFiles();
    if (kids == null) {
      return null;
    }
    for (File k : kids) {
      if (k.isDirectory()) {
        File f = find(k, name);
        if (f != null) {
          return f;
        }
      } else if (k.getName().equals(name)) {
        return k;
      }
    }
    return null;
  }

  private static Path volumeOf(Map<Path, File> placement, File vol) {
    for (Map.Entry<Path, File> e : placement.entrySet()) {
      if (vol.equals(e.getValue())) {
        return e.getKey();
      }
    }
    return null;
  }

  private String placement(Map<Path, Long> blocks, Map<Path, File> vols) {
    StringBuilder sb = new StringBuilder();
    for (Map.Entry<Path, Long> e : blocks.entrySet()) {
      File v = vols.get(e.getKey());
      sb.append(e.getKey()).append("=blk_").append(e.getValue()).append('@')
          .append(v == null ? "?" : v.getName()).append(' ');
    }
    return sb.toString().trim();
  }

  private static List<String> servedVolumes(FsDatasetSpi<?> ds)
      throws IOException {
    List<String> out = new ArrayList<>();
    try (FsDatasetSpi.FsVolumeReferences refs = ds.getFsVolumeReferences()) {
      for (FsVolumeSpi v : refs) {
        out.add(new File(v.getBaseURI()).getAbsolutePath());
      }
    }
    return out;
  }
}
