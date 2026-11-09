/*
 * Specula MC-1 reproduction -- escalation Level 0 (public startup options and
 * admin commands only: no fault-injection hooks, no state injection, no source patch).
 *
 * Canonical copy:  .specula-output/repro/test_bugMC-1_dn_missed_rollback_reupgrade.java
 * Installed by the driver test_bugMC-1_dn_missed_rollback_reupgrade.sh as
 *   hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/
 *       SpeculaAdhocMC1DnMissedRollbackTest.java
 * i.e. a variant of the workload test org.apache.hadoop.hdfs.TestDFSRollback#testRollback
 * (same module, same package, same configuration idiom: UpgradeUtilities
 * .initializeStorageStateConf(2, conf), unmanaged name/data dirs, NameNode.doRollback,
 * MiniDFSCluster start options).
 *
 * Target: BlockPoolSliceStorage.doRollback, BlockPoolSliceStorage.java:621,
 *   throws InconsistentFSStateException when
 *   !(prevInfo.LV >= softwareLV && prevInfo.cTime <= nsInfo.cTime).
 *
 * Every step is a real operator/daemon action, numbered by the counterexample
 * state it realizes (spec/output/MC_hunt_S1_bfs.out):
 *   CE 1      Init               cluster formatted at cTime c0, dn0 has 2 volumes
 *   CE 2      MCNNUpgrade        NameNode started with -upgrade  (cTime c1 = now())
 *   CE 3-9    MCDNStart..InitDone dn0 started REGULAR -> its BP storage is upgraded c0 -> c1
 *   CE 10-11  MCDNStop, MCNNStop cluster stopped
 *   CE 12     MCNNRollback       `hdfs namenode -rollback`  (NameNode.doRollback)
 *   CE 13     MCDNOutage         dn0 out of service: it is NOT started with -rollback
 *   CE 14     MCCloseRollback    the rollback window closes without dn0
 *   CE 15     MCNNUpgrade        NameNode started with -upgrade again (cTime c2 = now())
 *   CE 16-23  MCDNRepair..       dn0 repaired, started REGULAR (normal start during an upgrade)
 *   CE 24-25  MCDNStop, MCNNStop cluster stopped
 *   CE 26     MCNNRollback       `hdfs namenode -rollback`
 *   CE 27     MCNNStart          NameNode started
 *   CE 28-30  MCDNStart(-rollback), MCDNHandshake, MCTargetCheck
 *
 * The test never writes a VERSION file or any other guard operand; it only reads
 * VERSION files to log/assert what the real upgrade/rollback code produced.
 * The control test runs the identical sequence except that at CE 13 dn0 takes
 * part in the rollback (it is started with -rollback, as the procedure requires).
 */
package org.apache.hadoop.hdfs;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
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
import org.apache.hadoop.hdfs.server.common.HdfsServerConstants.StartupOption;
import org.apache.hadoop.hdfs.server.common.Storage;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.hdfs.server.namenode.NameNode;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class SpeculaAdhocMC1DnMissedRollbackTest {
  private static final Logger LOG =
      LoggerFactory.getLogger(SpeculaAdhocMC1DnMissedRollbackTest.class);

  private static final Path F0 = new Path("/mc1/written-at-c0");
  private static final Path F1 = new Path("/mc1/written-at-c1");
  private static final String TARGET_EXC =
      "org.apache.hadoop.hdfs.server.common.InconsistentFSStateException";
  /** First stack frame of the thrown exception = the target method. */
  private static final Pattern TARGET_TRACE = Pattern.compile(
      "(" + Pattern.quote(TARGET_EXC) + ": [^\\n]*(?:\\n[^\\t\\n][^\\n]*)*)\\n"
      + "\\s*at (org\\.apache\\.hadoop\\.hdfs\\.server\\.datanode\\."
      + "BlockPoolSliceStorage\\.doRollback\\(BlockPoolSliceStorage\\.java:(\\d+)\\))");

  private Configuration conf;
  private MiniDFSCluster cluster;
  private String[] nameNodeDirs;
  private String[] dataNodeDirs;
  private String bpid;
  private long c0, c1, c2;

  private static void say(String msg) {
    System.out.println("[MC-1] " + msg);
    LOG.info("[MC-1] " + msg);
  }

  @AfterEach
  public void tearDown() {
    if (cluster != null) {
      cluster.shutdown();
      cluster = null;
    }
  }

  // ---------------------------------------------------------------- helpers

  /** TestDFSRollback#testRollback configuration with numDirs = 2 (dn0 has two volumes). */
  private void initConf() throws IOException {
    conf = new HdfsConfiguration();
    conf.setInt(DFSConfigKeys.DFS_DATANODE_SCAN_PERIOD_HOURS_KEY, -1);
    conf = UpgradeUtilities.initializeStorageStateConf(2, conf);
    nameNodeDirs = conf.getStrings(DFSConfigKeys.DFS_NAMENODE_NAME_DIR_KEY);
    dataNodeDirs = conf.getStrings(DFSConfigKeys.DFS_DATANODE_DATA_DIR_KEY);
    UpgradeUtilities.createEmptyDirs(nameNodeDirs);
    UpgradeUtilities.createEmptyDirs(dataNodeDirs);
  }

  private MiniDFSCluster.Builder builder() {
    return new MiniDFSCluster.Builder(conf).format(false)
        .manageDataDfsDirs(false).manageNameDfsDirs(false);
  }

  private void stopCluster() {
    cluster.shutdown();
    cluster = null;
  }

  /** Read-only: cTime recorded in dir/VERSION, or "<absent>". */
  private static String cTimeOf(File dir) throws IOException {
    File f = new File(dir, "VERSION");
    if (!f.exists()) {
      return "<absent>";
    }
    Properties p = new Properties();
    try (InputStream in = new FileInputStream(f)) {
      p.load(in);
    }
    return p.getProperty("cTime");
  }

  private String bpState() throws IOException {
    StringBuilder sb = new StringBuilder();
    for (int i = 0; i < dataNodeDirs.length; i++) {
      File bpRoot = new File(dataNodeDirs[i], "current/" + bpid);
      sb.append(String.format(" vol%d{current=%s, previous=%s}", i + 1,
          cTimeOf(new File(bpRoot, "current")),
          cTimeOf(new File(bpRoot, "previous"))));
    }
    return sb.toString().trim();
  }

  private String nnState() throws IOException {
    StringBuilder sb = new StringBuilder();
    for (int i = 0; i < nameNodeDirs.length; i++) {
      sb.append(String.format(" name%d{current=%s, previous=%s}", i + 1,
          cTimeOf(new File(nameNodeDirs[i], "current")),
          cTimeOf(new File(nameNodeDirs[i], "previous"))));
    }
    return sb.toString().trim();
  }

  private void assertBp(long cur, Long prev) throws IOException {
    for (String d : dataNodeDirs) {
      File bpRoot = new File(d, "current/" + bpid);
      assertEquals(String.valueOf(cur), cTimeOf(new File(bpRoot, "current")),
          "current cTime of " + bpRoot);
      assertEquals(prev == null ? "<absent>" : String.valueOf(prev),
          cTimeOf(new File(bpRoot, "previous")), "previous cTime of " + bpRoot);
    }
  }

  /** Waits until dn0's block-pool actor has ended its initialization attempt. */
  private void waitBpInitFailed(LogCapturer dnLogs) throws Exception {
    GenericTestUtils.waitFor(
        () -> dnLogs.getOutput().contains("Initialization failed for"),
        100, 60000);
  }

  // --------------------------------------------------------------- scenario

  /**
   * CE states 1-27. If dnMissesFirstRollback, dn0 is out of service during the
   * first rollback window (CE 13 MCDNOutage); otherwise (control) it takes part.
   */
  private void scenarioUpToSecondRollback(boolean dnMissesFirstRollback)
      throws Exception {
    initConf();

    // CE 1 (Init): a cluster at cTime c0; dn0 holds the only replica of F0.
    DFSTestUtil.formatNameNode(conf);
    cluster = builder().numDataNodes(1).startupOption(StartupOption.REGULAR)
        .build();
    cluster.waitActive();
    bpid = cluster.getNamesystem().getBlockPoolId();
    c0 = UpgradeUtilities.getCurrentFsscTime(cluster);
    DFSTestUtil.createFile(cluster.getFileSystem(), F0, 8192L, (short) 1, 0xC0L);
    stopCluster();
    say("[CE 1 Init] formatted cluster, nsInfo.cTime c0=" + c0 + ", bpid=" + bpid
        + "; client wrote " + F0 + " (1 replica, on dn0). NN " + nnState()
        + "; dn0 BP " + bpState());

    // CE 2 MCNNUpgrade: NN -upgrade.  CE 3-9: dn0 REGULAR start -> BP upgrade.
    cluster = builder().numDataNodes(1).startupOption(StartupOption.UPGRADE)
        .build();
    cluster.waitActive();
    c1 = UpgradeUtilities.getCurrentFsscTime(cluster);
    assertTrue(c1 > c0, "c1 > c0");
    assertTrue(cluster.getDataNodes().get(0).isBPServiceAlive(bpid));
    DFSTestUtil.createFile(cluster.getFileSystem(), F1, 8192L, (short) 1, 0xC1L);
    say("[CE 2-9 MCNNUpgrade, MCDNStart..MCDNInitDone] NN started with -upgrade:"
        + " nsInfo.cTime c1=" + c1 + "; dn0 started REGULAR and registered; dn0 BP "
        + bpState() + "; client wrote " + F1);
    assertBp(c1, c0);

    // CE 10-11 MCDNStop, MCNNStop.  CE 12 MCNNRollback: `hdfs namenode -rollback`.
    stopCluster();
    NameNode.doRollback(conf, false);
    say("[CE 10-12 MCDNStop, MCNNStop, MCNNRollback] `hdfs namenode -rollback`"
        + " done: NN " + nnState());

    if (dnMissesFirstRollback) {
      // CE 13 MCDNOutage, CE 14 MCCloseRollback: dn0 is never started with
      // -rollback; its volumes keep the abandoned c1 epoch.
      say("[CE 13-14 MCDNOutage, MCCloseRollback] dn0 out of service for the"
          + " whole rollback window (never started with -rollback); dn0 BP "
          + bpState());
      assertBp(c1, c0);
    } else {
      // CONTROL: dn0 takes part in the rollback (start-dfs.sh -rollback).
      cluster = builder().numDataNodes(1)
          .dnStartupOption(StartupOption.ROLLBACK).build();
      cluster.waitActive();
      assertTrue(cluster.getDataNodes().get(0).isBPServiceAlive(bpid));
      stopCluster();
      say("[CONTROL CE 13'] dn0 took part in the rollback (started with"
          + " -rollback); dn0 BP " + bpState());
      assertBp(c0, null);
    }

    // CE 15 MCNNUpgrade: re-upgrade (FSImage.checkUpgrade passes: no NN previous).
    // CE 16 MCDNRepair, CE 17-23: dn0 started REGULAR, as during any upgrade.
    cluster = builder().numDataNodes(1).startupOption(StartupOption.UPGRADE)
        .build();
    cluster.waitActive();
    c2 = UpgradeUtilities.getCurrentFsscTime(cluster);
    assertTrue(c2 > c1, "c2 > c1");
    assertTrue(cluster.getDataNodes().get(0).isBPServiceAlive(bpid),
        "dn0 is accepted by the re-upgraded NameNode");
    say("[CE 15-23 MCNNUpgrade, MCDNRepair, MCDNStart..MCDNInitDone] NN started"
        + " with -upgrade again: nsInfo.cTime c2=" + c2 + "; NN " + nnState()
        + "; dn0 started REGULAR, block pool alive=true, NN live DNs="
        + cluster.getNamesystem().getNumLiveDataNodes() + "; dn0 BP " + bpState());
    if (dnMissesFirstRollback) {
      assertBp(c2, c1);   // the c0 snapshot is gone; previous = abandoned c1 epoch
    } else {
      assertBp(c2, c0);
    }

    // CE 24-25 MCDNStop, MCNNStop.  CE 26 MCNNRollback.  CE 27 MCNNStart.
    stopCluster();
    NameNode.doRollback(conf, false);
    say("[CE 24-26 MCDNStop, MCNNStop, MCNNRollback] `hdfs namenode -rollback`"
        + " done: NN " + nnState());
    cluster = builder().numDataNodes(0).dnStartupOption(StartupOption.ROLLBACK)
        .build();
    long ns = UpgradeUtilities.getCurrentFsscTime(cluster);
    say("[CE 27 MCNNStart] NN started: nsInfo.cTime=" + ns + " (c0=" + c0 + ")");
    assertEquals(c0, ns);
  }

  // ------------------------------------------------------------------ tests

  @Test
  @Timeout(600)
  public void testDnMissesRollbackThenReupgradeThenRollback() throws Exception {
    scenarioUpToSecondRollback(true);

    // CE 28 MCDNStart(dn0) with -rollback, CE 29 MCDNHandshake, CE 30 MCTargetCheck.
    LogCapturer storageLogs = LogCapturer.captureLogs(Storage.LOG);
    LogCapturer dnLogs = LogCapturer.captureLogs(DataNode.LOG);
    try {
      cluster.startDataNodes(conf, 1, false, StartupOption.ROLLBACK, null);
      waitBpInitFailed(dnLogs);
    } finally {
      storageLogs.stopCapturing();
      dnLogs.stopCapturing();
    }
    final String slog = storageLogs.getOutput();
    final String dlog = dnLogs.getOutput();

    // Same-bug test: the target exception type, thrown from the target method.
    // Each throw is logged twice (BlockPoolSliceStorage.java:230 and
    // DataStorage.java:474), so count distinct block-pool directories.
    Matcher m = TARGET_TRACE.matcher(slog);
    Pattern dirOf = Pattern.compile("Directory (\\S+) is in an inconsistent state");
    java.util.Set<String> staleDirs = new java.util.TreeSet<>();
    int logged = 0;
    String firstHeader = null;
    String firstFrame = null;
    int frameLine = -1;
    while (m.find()) {
      logged++;
      Matcher d = dirOf.matcher(m.group(1));
      if (d.find()) {
        staleDirs.add(d.group(1));
      }
      if (firstHeader == null) {
        firstHeader = m.group(1);
        firstFrame = m.group(2);
        frameLine = Integer.parseInt(m.group(3));
      }
    }
    final int thrown = staleDirs.size();
    say("[CE 28-30 MCDNStart(-rollback), MCDNHandshake, MCTargetCheck] "
        + TARGET_EXC + " thrown for " + thrown + " block-pool directories (one per"
        + " dn0 volume; " + logged + " log records): " + staleDirs);
    if (firstHeader == null) {
      say("captured Storage log:\n" + slog);
      fail("target exception with a BlockPoolSliceStorage.doRollback top frame"
          + " was not thrown");
    }
    say("TARGET exception: " + firstHeader);
    say("TARGET top frame: " + firstFrame);
    int idx = slog.indexOf(firstHeader);
    String[] traceLines = slog.substring(idx).split("\n");
    StringBuilder trace = new StringBuilder();
    for (int i = 0; i < Math.min(traceLines.length, 26); i++) {
      trace.append(traceLines[i]).append('\n');
    }
    say("TARGET stack trace (first log record):\n" + trace);
    assertEquals(dataNodeDirs.length, thrown, "one throw per stale volume");
    assertTrue(frameLine >= 621 && frameLine <= 626,
        "frame line " + frameLine + " is inside the throw statement BPSS:621-626");
    assertTrue(firstHeader.contains("Cannot rollback to a newer state"));
    assertTrue(firstHeader.contains("CTime = " + c1)
        && firstHeader.contains("CTime = " + c0),
        "previous cTime c1 vs namespace cTime c0 in the message");

    // Consequence for the real consumers.
    final DataNode dn0 = cluster.getDataNodes().get(0);
    assertTrue(dlog.contains("All specified directories have failed to load"));
    assertFalse(dn0.isBPServiceAlive(bpid));
    for (String l : dlog.split("\n")) {
      if (l.contains("Initialization failed for")
          || l.contains("All specified directories have failed to load")
          || l.contains("Ending block pool service")) {
        say("DataNode log: " + l.trim());
      }
    }
    final FileSystem fs = cluster.getFileSystem();
    say("NN view: live DataNodes=" + cluster.getNamesystem().getNumLiveDataNodes()
        + ", inSafeMode=" + cluster.getNameNode().isInSafeMode()
        + ", " + F0 + " exists=" + fs.exists(F0) + ", " + F1 + " exists="
        + fs.exists(F1));
    say("NN safe mode: " + cluster.getNamesystem().getSafemode());
    assertEquals(0, cluster.getNamesystem().getNumLiveDataNodes());
    assertTrue(fs.exists(F0), "rolled-back namespace still lists F0");
    assertFalse(fs.exists(F1), "F1 belonged to the rolled-back epoch");
    try {
      DFSTestUtil.readFile(fs, F0);
      fail("reading " + F0 + " should fail: its only replica is on dn0");
    } catch (IOException e) {
      say("client read of " + F0 + " FAILED: " + e.getClass().getName() + ": "
          + e.getMessage().split("\n")[0]);
    }
    // (Safe mode is informational only: with a single block the 0.999 threshold
    // truncates to 0 blocks, so the NameNode leaves safe mode immediately.)

    // Permanence: no start option brings dn0 back; on-disk state is unchanged.
    cluster.shutdownDataNodes();
    LogCapturer s2 = LogCapturer.captureLogs(Storage.LOG);
    LogCapturer d2 = LogCapturer.captureLogs(DataNode.LOG);
    try {
      cluster.startDataNodes(conf, 1, false, StartupOption.REGULAR, null);
      waitBpInitFailed(d2);
    } finally {
      s2.stopCapturing();
      d2.stopCapturing();
    }
    assertFalse(cluster.getDataNodes().get(0).isBPServiceAlive(bpid));
    final String s2out = s2.getOutput();
    assertTrue(s2out.contains("java.io.IOException: Datanode state: LV = ")
        && s2out.contains("CTime = " + c2 + " is newer than the namespace state")
        && s2out.contains(
            "BlockPoolSliceStorage.doTransition(BlockPoolSliceStorage.java:424)"),
        "REGULAR restart is refused by the BPSS:421-424 check");
    assertFalse(TARGET_TRACE.matcher(s2out).find(),
        "a REGULAR start does not reach doRollback");
    say("[PERMANENCE] dn0 restarted REGULAR: block pool init failed again at"
        + " BPSS:421-424 (frame doTransition(BlockPoolSliceStorage.java:424):"
        + " 'Datanode state: ... CTime = " + c2
        + " is newer than the namespace state')");
    cluster.shutdownDataNodes();
    LogCapturer s3 = LogCapturer.captureLogs(Storage.LOG);
    LogCapturer d3 = LogCapturer.captureLogs(DataNode.LOG);
    try {
      cluster.startDataNodes(conf, 1, false, StartupOption.ROLLBACK, null);
      waitBpInitFailed(d3);
    } finally {
      s3.stopCapturing();
      d3.stopCapturing();
    }
    assertFalse(cluster.getDataNodes().get(0).isBPServiceAlive(bpid));
    Matcher m3 = TARGET_TRACE.matcher(s3.getOutput());
    assertTrue(m3.find());
    say("[PERMANENCE] dn0 restarted with -rollback again: thrown again, top frame "
        + m3.group(2));
    say("[PERMANENCE] dn0 BP on disk: " + bpState() + "; the c0 snapshot (cTime="
        + c0 + ") no longer exists on dn0; NN live DataNodes="
        + cluster.getNamesystem().getNumLiveDataNodes() + ", inSafeMode="
        + cluster.getNameNode().isInSafeMode());
    assertBp(c2, c1);
    assertEquals(0, cluster.getNamesystem().getNumLiveDataNodes());
    say("RESULT: REPRODUCED -- " + TARGET_EXC + " at " + firstFrame);
  }

  @Test
  @Timeout(600)
  public void testControlDnTakesPartInFirstRollback() throws Exception {
    scenarioUpToSecondRollback(false);

    LogCapturer storageLogs = LogCapturer.captureLogs(Storage.LOG);
    try {
      cluster.startDataNodes(conf, 1, false, StartupOption.ROLLBACK, null);
      cluster.waitActive();
      cluster.waitFirstBRCompleted(0, 30000);
    } finally {
      storageLogs.stopCapturing();
    }
    final DataNode dn0 = cluster.getDataNodes().get(0);
    assertTrue(dn0.isBPServiceAlive(bpid));
    assertFalse(storageLogs.getOutput().contains(TARGET_EXC));
    byte[] data = DFSTestUtil.readFileBuffer(cluster.getFileSystem(), F0);
    assertEquals(8192, data.length);
    say("[CONTROL CE 28-30] dn0 started with -rollback: block pool alive=true,"
        + " no " + TARGET_EXC + "; dn0 BP " + bpState() + "; NN live DataNodes="
        + cluster.getNamesystem().getNumLiveDataNodes() + "; client read of " + F0
        + " OK (" + data.length + " bytes)");
    assertBp(c0, null);
    say("CONTROL RESULT: rollback succeeds when dn0 did not miss the first rollback");
  }
}
