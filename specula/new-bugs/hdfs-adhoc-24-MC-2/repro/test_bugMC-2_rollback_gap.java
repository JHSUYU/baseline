/**
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
package org.apache.hadoop.hdfs;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.Properties;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.FileSystem;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.hdfs.client.HdfsClientConfigKeys;
import org.apache.hadoop.hdfs.protocol.LocatedBlocks;
import org.apache.hadoop.hdfs.server.common.HdfsServerConstants.StartupOption;
import org.apache.hadoop.hdfs.server.common.Storage;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.hdfs.server.namenode.NameNode;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Specula MC-2 reproduction (hdfs-adhoc-24, target BlockPoolSliceStorage.java:421).
 *
 * A variant of the workload TestDFSUpgrade#testUpgrade ("Normal DataNode upgrade" step, numDirs = 2),
 * continued with the documented rollback (HdfsUserGuide "Upgrade and Rollback":
 * `hdfs namenode -rollback`, then `start-dfs.sh -rollback` = NameNode regular start + DataNode
 * -rollback; the same calls TestDFSRollback uses).
 *
 * The only fault is the counterexample's MCAttachEmptyVolume: a data dir that is an empty (new or
 * replaced) disk while the NameNode upgrade is not finalized, realised with the workload's own
 * UpgradeUtilities.createEmptyDirs. No VERSION file is written by this test: every block-pool
 * VERSION is a copy of the master storage (UpgradeUtilities.createDataNodeStorageDirs, as in the
 * workload) or written by the DataNode itself. The target method is not edited.
 *
 * Run by repro/test_bugMC-2_rollback_gap.sh, which copies this file to
 * src/test/java/org/apache/hadoop/hdfs/TestBugMC2RollbackGap.java in the worktree.
 */
public class TestBugMC2RollbackGap {
  private static final Logger LOG = LoggerFactory.getLogger(TestBugMC2RollbackGap.class);

  /** The frame the JVM reports for the throw statement at BlockPoolSliceStorage.java:421-424. */
  static final String TARGET_FRAME = "at org.apache.hadoop.hdfs.server.datanode."
      + "BlockPoolSliceStorage.doTransition(BlockPoolSliceStorage.java:424)";
  static final Pattern TARGET_EXC = Pattern.compile(
      "^java\\.io\\.IOException: Datanode state: LV = (-?\\d+) CTime = (-?\\d+) is newer than the "
      + "namespace state: LV = (-?\\d+) CTime = (-?\\d+)$");
  static final String PRE_UPGRADE_FILE = "/TestUpgrade/file1";

  private Configuration conf;
  private MiniDFSCluster cluster = null;
  private String[] nameNodeDirs;
  private String[] dataNodeDirs;
  private String bpid;
  private LogCapturer storageLog;
  private LogCapturer nnLog;
  private LogCapturer dnLog;

  @BeforeAll
  public static void initialize() throws Exception {
    UpgradeUtilities.initialize();
  }

  @BeforeEach
  public void setUp() throws Exception {
    // TestDFSUpgrade#testUpgrade's per-round configuration, numDirs = 2
    conf = new HdfsConfiguration();
    conf = UpgradeUtilities.initializeStorageStateConf(2, conf);
    conf.setBoolean(DFSConfigKeys.DFS_DATANODE_DUPLICATE_REPLICA_DELETION, false);
    nameNodeDirs = conf.getStrings(DFSConfigKeys.DFS_NAMENODE_NAME_DIR_KEY);
    dataNodeDirs = conf.getStrings(DFSConfigKeys.DFS_DATANODE_DATA_DIR_KEY);
    bpid = UpgradeUtilities.getCurrentBlockPoolID(null);
    UpgradeUtilities.createEmptyDirs(nameNodeDirs);
    UpgradeUtilities.createEmptyDirs(dataNodeDirs);
    // DataStorage and BlockPoolSliceStorage log through Storage.LOG
    storageLog = LogCapturer.captureLogs(Storage.LOG);
    nnLog = LogCapturer.captureLogs(NameNode.LOG);
    dnLog = LogCapturer.captureLogs(DataNode.LOG);
  }

  @AfterEach
  public void tearDown() throws Exception {
    storageLog.stopCapturing();
    nnLog.stopCapturing();
    dnLog.stopCapturing();
    if (cluster != null) {
      cluster.shutdown();
      cluster = null;
    }
    UpgradeUtilities.createEmptyDirs(nameNodeDirs);
    UpgradeUtilities.createEmptyDirs(dataNodeDirs);
  }

  private static void ev(String test, String what) {
    String line = "MC2-EVIDENCE[" + test + "] " + what;
    System.out.println(line);
    LOG.info(line);
  }

  /** TestDFSUpgrade.createCluster() with the NameNode startup option as a parameter. */
  private MiniDFSCluster createCluster(StartupOption nnOpt) throws IOException {
    return new MiniDFSCluster.Builder(conf).numDataNodes(0)
                                           .format(false)
                                           .manageDataDfsDirs(false)
                                           .manageNameDfsDirs(false)
                                           .startupOption(nnOpt)
                                           .build();
  }

  private File bpDir(String dataDir, String sub) {
    return new File(new File(new File(new File(dataDir), "current"), bpid), sub);
  }

  /** Read-only: the cTime in a block-pool slice's current/VERSION. */
  private long bpCTime(String dataDir) throws IOException {
    Properties p = new Properties();
    try (InputStream in = new FileInputStream(new File(bpDir(dataDir, "current"), "VERSION"))) {
      p.load(in);
    }
    return Long.parseLong(p.getProperty("cTime"));
  }

  private String sliceState(String dataDir) throws IOException {
    return dataDir + ": BP current/VERSION cTime=" + bpCTime(dataDir) + ", previous/ "
        + (bpDir(dataDir, "previous").exists() ? "present" : "absent");
  }

  /** Workload "Normal DataNode upgrade": NN -upgrade, then a regular DataNode start. */
  private long upgradeWindowStart(String test) throws Exception {
    UpgradeUtilities.createNameNodeStorageDirs(nameNodeDirs, "current");
    cluster = createCluster(StartupOption.UPGRADE);                       // CE: MCNNDoUpgrade
    final long cUp = UpgradeUtilities.getCurrentFsscTime(cluster);
    ev(test, "NameNode -upgrade done, upgraded NameNode cTime = " + cUp
        + " (pre-upgrade cTime = " + UpgradeUtilities.getCurrentFsscTime(null) + ")");
    return cUp;
  }

  /** hdfs namenode -rollback; start-dfs.sh -rollback (NN regular start, DataNode -rollback). */
  private long documentedRollback(String test) throws Exception {
    cluster.shutdown();                                                   // CE: MCDataNodeStop
    cluster = null;
    NameNode.doRollback(conf, false);                                     // CE: MCNNDoRollback
    cluster = createCluster(StartupOption.REGULAR);
    final long c0 = UpgradeUtilities.getCurrentFsscTime(cluster);
    ev(test, "NameNode -rollback done, NameNode cTime = " + c0);
    storageLog.clearOutput();
    nnLog.clearOutput();
    dnLog.clearOutput();
    cluster.startDataNodes(conf, 1, false, StartupOption.ROLLBACK, null); // CE: MCDataNodeStart(ROLLBACK)
    return c0;
  }

  /**
   * Find the logged target exception: a line that is exactly the L421 IOException message, whose
   * next line is the doTransition:424 frame. Returns {failedVolumeLine, excLine, frame1, frame2}.
   */
  private static String[] targetThrow(String log) {
    String[] lines = log.split("\\r?\\n");
    String volumeLine = null;
    for (int i = 0; i < lines.length; i++) {
      if (lines[i].contains("Failed to add storage directory") && i + 1 < lines.length
          && TARGET_EXC.matcher(lines[i + 1].trim()).matches()) {
        volumeLine = lines[i].trim();
      }
    }
    for (int i = 0; i + 2 < lines.length; i++) {
      if (TARGET_EXC.matcher(lines[i].trim()).matches()
          && lines[i + 1].trim().equals(TARGET_FRAME)) {
        return new String[] {volumeLine, lines[i].trim(), lines[i + 1].trim(),
            lines[i + 2].trim()};
      }
    }
    return null;
  }

  private String[] assertTargetThrown(String test, long cUp, long c0, String badDir) {
    String[] t = targetThrow(storageLog.getOutput());
    assertNotNull(t, "target IOException with frame " + TARGET_FRAME + " not logged");
    ev(test, "failed volume : " + t[0]);
    ev(test, "exception     : " + t[1]);
    ev(test, "top frame     : " + t[2]);
    ev(test, "caller frame  : " + t[3]);
    Matcher m = TARGET_EXC.matcher(t[1]);
    assertTrue(m.matches());
    assertEquals(cUp, Long.parseLong(m.group(2)), "slice cTime in the message");
    assertEquals(c0, Long.parseLong(m.group(4)), "namespace cTime in the message");
    assertNotNull(t[0], "DataStorage did not report the failed volume");
    assertTrue(t[0].contains(new File(badDir).getAbsolutePath()), "failed volume is " + badDir);
    return t;
  }

  private void assertNoTargetThrow(String test) {
    assertNull(targetThrow(storageLog.getOutput()), "unexpected target throw");
    assertFalse(storageLog.getOutput().contains("is newer than the namespace state"));
    ev(test, "no 'is newer than the namespace state' IOException logged");
  }

  private FileSystem clientFs() throws IOException {
    // client side only: fail a read of a block that has no location fast
    Configuration c = new Configuration(conf);
    c.setInt(HdfsClientConfigKeys.Retry.WINDOW_BASE_KEY, 10);
    return FileSystem.newInstance(cluster.getURI(), c);
  }

  private int locations(String path) throws IOException {
    LocatedBlocks lbs = cluster.getNameNodeRpc().getBlockLocations(path, 0, Long.MAX_VALUE);
    return lbs.get(0).getLocations().length;
  }

  /** Read-only: number of block replica files (blk_N, not .meta) under a slice directory. */
  private static int countReplicas(File dir) {
    File[] children = dir.listFiles();
    if (children == null) {
      return 0;
    }
    int n = 0;
    for (File c : children) {
      if (c.isDirectory()) {
        n += countReplicas(c);
      } else if (c.getName().matches("blk_-?\\d+")) {
        n++;
      }
    }
    return n;
  }

  private static String oneLine(String s) {
    return s == null ? "null" : s.replaceAll("\\s*\\r?\\n\\s*", " | ");
  }

  /** The consequence when the failed slice is the last one loaded. */
  private void assertDataNodeLeavesService(String test, String goodDir) throws Exception {
    final DataNode dn = cluster.getDataNodes().get(0);
    GenericTestUtils.waitFor(() -> !dn.isBPServiceAlive(bpid), 100, 60000,
        "block-pool service of the DataNode exits");
    ev(test, "DataNode.isBPServiceAlive(" + bpid + ") = " + dn.isBPServiceAlive(bpid));
    String nn = nnLog.getOutput();
    String dnOut = dnLog.getOutput();
    String mismatch = firstLine(nn, "Registration IDs mismatched");
    String exit = firstLine(dnOut, "is shutting down");
    assertNotNull(mismatch, "NameNode did not reject the registration");
    assertNotNull(exit, "BPServiceActor did not exit");
    ev(test, "NameNode      : " + mismatch);
    ev(test, "DataNode      : " + exit);
    ev(test, "DataNode      : " + firstLine(dnOut, "UnregisteredNodeException"));
    // the pre-upgrade replicas are intact on the correctly rolled-back slice ...
    int onDisk = countReplicas(bpDir(goodDir, "current"));
    ev(test, onDisk + " pre-upgrade replica files on disk in the rolled-back slice of " + goodDir);
    assertTrue(onDisk > 0);
    // ... but the cluster cannot serve them: no block report ever reaches the NameNode
    try (FileSystem fs = clientFs()) {
      DFSTestUtil.readFile(fs, new Path(PRE_UPGRADE_FILE));
      fail("read of a pre-upgrade file succeeded");
    } catch (IOException e) {
      ev(test, "client read of " + PRE_UPGRADE_FILE + " failed: " + e.getClass().getName()
          + ": " + oneLine(e.getMessage()));
    }
    // nothing retries: 5 s later the block pool is still down and the NameNode still in safe mode
    Thread.sleep(5000);
    ev(test, "5 s later: DataNode.isBPServiceAlive = " + dn.isBPServiceAlive(bpid)
        + "; NameNode in safe mode = " + cluster.getNameNode().isInSafeMode());
    assertFalse(dn.isBPServiceAlive(bpid));
    assertTrue(cluster.getNameNode().isInSafeMode());
  }

  private static String firstLine(String log, String part) {
    for (String l : log.split("\\r?\\n")) {
      if (l.contains(part)) {
        return l.trim();
      }
    }
    return null;
  }

  private void assertPreUpgradeFileReadable(String test) throws Exception {
    GenericTestUtils.waitFor(() -> {
      try {
        return locations(PRE_UPGRADE_FILE) > 0;
      } catch (IOException e) {
        return false;
      }
    }, 100, 60000, "block report of the rolled-back DataNode");
    try (FileSystem fs = clientFs()) {
      String content = DFSTestUtil.readFile(fs, new Path(PRE_UPGRADE_FILE));
      ev(test, "client read of " + PRE_UPGRADE_FILE + " ok, " + content.length() + " chars; "
          + "block locations = " + locations(PRE_UPGRADE_FILE));
    }
  }

  /** A regular DataNode restart under the rolled-back NameNode. */
  private void restartDataNodeRegular(String test) throws Exception {
    cluster.stopDataNode(0);
    storageLog.clearOutput();
    nnLog.clearOutput();
    dnLog.clearOutput();
    cluster.startDataNodes(conf, 1, false, StartupOption.REGULAR, null);
    ev(test, "DataNode restarted (regular) under the rolled-back NameNode");
  }

  /**
   * Exact order of the crash-free counterexample spec/output/MC_char_rollback_gap_attach_bfs.out:
   * NN upgrade; v1 (data1) is an empty disk, v2 (data2) holds the pre-upgrade data; DataNode
   * start (v1 formatted with the upgraded cTime, v2 upgraded); DataNode stop; NN rollback;
   * DataNode -rollback start: TargetCheck fires on v1.
   */
  @Test
  @Timeout(value = 300)
  public void testCounterexampleOrderEmptyDiskFirst() throws Exception {
    final String test = "ce-order";
    final String empty = dataNodeDirs[0];
    final String full = dataNodeDirs[1];
    long cUp = upgradeWindowStart(test);
    UpgradeUtilities.createEmptyDirs(new String[] {empty});              // CE: MCAttachEmptyVolume(v1)
    UpgradeUtilities.createDataNodeStorageDirs(new String[] {full}, "current");
    cluster.startDataNodes(conf, 1, false, StartupOption.REGULAR, null);  // CE: MCDataNodeStart
    assertTrue(cluster.getDataNodes().get(0).isBPServiceAlive(bpid));
    ev(test, "after the DataNode start in the upgrade window: " + sliceState(empty));
    ev(test, "after the DataNode start in the upgrade window: " + sliceState(full));
    assertEquals(cUp, bpCTime(empty));
    assertFalse(bpDir(empty, "previous").exists());
    assertTrue(bpDir(full, "previous").isDirectory());

    long c0 = documentedRollback(test);
    assertTargetThrown(test, cUp, c0, empty);
    ev(test, "after the documented rollback: " + sliceState(empty));
    ev(test, "after the documented rollback: " + sliceState(full));
    assertEquals(cUp, bpCTime(empty), "the empty-disk slice was not rolled back");
    assertEquals(c0, bpCTime(full));

    // permanent: every later start under the rolled-back namespace fails the slice again
    restartDataNodeRegular(test);
    assertTargetThrown(test, cUp, c0, empty);
    ev(test, "BUG REPRODUCED: L421 throw on the empty-disk slice after the documented rollback,"
        + " and again on a regular restart");
  }

  /**
   * Same counterexample with the empty disk configured last (a new disk appended to
   * dfs.datanode.data.dir): the failed slice's cTime stays in the shared BlockPoolSliceStorage,
   * the DataNode registers with it, and the NameNode rejects the DataNode.
   */
  @Test
  @Timeout(value = 300)
  public void testEmptyDiskLastDataNodeLeavesService() throws Exception {
    final String test = "empty-last";
    final String full = dataNodeDirs[0];
    final String empty = dataNodeDirs[1];
    long cUp = upgradeWindowStart(test);
    UpgradeUtilities.createDataNodeStorageDirs(new String[] {full}, "current");
    UpgradeUtilities.createEmptyDirs(new String[] {empty});              // CE: MCAttachEmptyVolume
    cluster.startDataNodes(conf, 1, false, StartupOption.REGULAR, null);
    assertTrue(cluster.getDataNodes().get(0).isBPServiceAlive(bpid));
    ev(test, "after the DataNode start in the upgrade window: " + sliceState(full));
    ev(test, "after the DataNode start in the upgrade window: " + sliceState(empty));
    assertEquals(cUp, bpCTime(empty));
    assertFalse(bpDir(empty, "previous").exists());

    long c0 = documentedRollback(test);
    assertTargetThrown(test, cUp, c0, empty);
    ev(test, "after the documented rollback: " + sliceState(full));
    ev(test, "after the documented rollback: " + sliceState(empty));
    assertEquals(c0, bpCTime(full));
    assertDataNodeLeavesService(test, full);

    restartDataNodeRegular(test);
    assertTargetThrown(test, cUp, c0, empty);
    assertDataNodeLeavesService(test, full);
    ev(test, "BUG REPRODUCED: L421 throw, then the DataNode is rejected by the NameNode and its"
        + " pre-upgrade replicas are unavailable; same again after a regular restart");
  }

  /**
   * Production order: the DataNode upgrades both disks; later in the (days-long) unfinalized
   * window the second disk is replaced by an empty one and the DataNode restarts; then the
   * documented rollback.
   */
  @Test
  @Timeout(value = 300)
  public void testDiskReplacedDuringUpgradeWindow() throws Exception {
    final String test = "replaced";
    final String kept = dataNodeDirs[0];
    final String replaced = dataNodeDirs[1];
    long cUp = upgradeWindowStart(test);
    UpgradeUtilities.createDataNodeStorageDirs(dataNodeDirs, "current");
    cluster.startDataNodes(conf, 1, false, StartupOption.REGULAR, null);
    assertTrue(bpDir(kept, "previous").isDirectory());
    assertTrue(bpDir(replaced, "previous").isDirectory());
    cluster.stopDataNode(0);
    UpgradeUtilities.createEmptyDirs(new String[] {replaced});           // the disk is replaced
    cluster.startDataNodes(conf, 1, false, StartupOption.REGULAR, null);
    assertTrue(cluster.getDataNodes().get(0).isBPServiceAlive(bpid));
    ev(test, "after the disk replacement and DataNode restart: " + sliceState(kept));
    ev(test, "after the disk replacement and DataNode restart: " + sliceState(replaced));
    assertEquals(cUp, bpCTime(replaced));
    assertFalse(bpDir(replaced, "previous").exists());

    long c0 = documentedRollback(test);
    assertTargetThrown(test, cUp, c0, replaced);
    assertEquals(c0, bpCTime(kept));
    assertDataNodeLeavesService(test, kept);
    ev(test, "BUG REPRODUCED: a disk replaced during the unfinalized upgrade breaks the"
        + " documented rollback of the whole DataNode");
  }

  /** Control: the same procedure without an empty disk. */
  @Test
  @Timeout(value = 300)
  public void testControlNoEmptyDisk() throws Exception {
    final String test = "control";
    long cUp = upgradeWindowStart(test);
    UpgradeUtilities.createDataNodeStorageDirs(dataNodeDirs, "current");
    cluster.startDataNodes(conf, 1, false, StartupOption.REGULAR, null);
    assertEquals(cUp, bpCTime(dataNodeDirs[0]));
    assertEquals(cUp, bpCTime(dataNodeDirs[1]));

    long c0 = documentedRollback(test);
    assertNoTargetThrow(test);
    ev(test, "after the documented rollback: " + sliceState(dataNodeDirs[0]));
    ev(test, "after the documented rollback: " + sliceState(dataNodeDirs[1]));
    assertEquals(c0, bpCTime(dataNodeDirs[0]));
    assertEquals(c0, bpCTime(dataNodeDirs[1]));
    assertTrue(cluster.getDataNodes().get(0).isBPServiceAlive(bpid));
    ev(test, "DataNode.isBPServiceAlive(" + bpid + ") = true");
    assertPreUpgradeFileReadable(test);
  }
}
