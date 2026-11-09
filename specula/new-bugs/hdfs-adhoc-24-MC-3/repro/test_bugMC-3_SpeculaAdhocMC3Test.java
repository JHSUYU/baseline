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
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.Properties;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.hdfs.MiniDFSCluster.DataNodeProperties;
import org.apache.hadoop.hdfs.protocol.RollingUpgradeInfo;
import org.apache.hadoop.hdfs.server.common.Storage;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.hdfs.server.datanode.DataNodeTestUtils;
import org.apache.hadoop.hdfs.server.namenode.NameNode;
import org.apache.hadoop.hdfs.tools.DFSAdmin;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.io.TempDir;

/**
 * Specula ad hoc variant of {@link TestDFSUpgrade#testUpgrade} for finding
 * MC-3 (counterexample spec/output/MC_hunt_ru_marker_bfs.out).
 *
 * Only operator commands and node restarts are used (Level 0): dfsadmin
 * -safemode enter / -rollingUpgrade prepare|finalize, a DataNode that is down
 * while the rolling upgrade is finalized, "namenode -upgrade",
 * "namenode -rollback" (NameNode.doRollback, without the Y/N prompt) and
 * "datanode -rollback". Nothing writes VERSION files, markers or
 * directories; the test only reads them.
 *
 * Three runs share the same steps and differ only around the RU finalize:
 * - DN_DOWN_FIRST (Level 0): the DN is stopped, then the RU is finalized.
 * - CE_ORDER (Level 1, ordering only): the RU is finalized and the DN is
 *   stopped before it sends another heartbeat (counterexample S27 then S28);
 *   heartbeats are paused with DataNodeTestUtils.setHeartbeatsDisabledForTests.
 * - CONTROL: the DN stays up across the RU finalize, so a heartbeat clears
 *   its markers before the regular upgrade.
 *
 * The target is the throw statement that starts at BlockPoolSliceStorage.java
 * line 421 and ends at line 424; javac maps its IOException constructor call
 * and athrow to line 424, so the stack frame of that throw reads ":424".
 */
public class SpeculaAdhocMC3Test {

  /** BlockPoolSliceStorage.ROLLING_UPGRADE_MARKER_FILE (package-private). */
  private static final String MARKER = "RollingUpgradeInProgress";
  private static final String TARGET_MSG = "is newer than the namespace state";
  private static final String TARGET_MSG_PREFIX =
      "java.io.IOException: Datanode state: LV = ";
  /** Frame of the throw statement spanning lines 421-424. */
  private static final Pattern TARGET_FRAME = Pattern.compile(
      "at (org\\.apache\\.hadoop\\.hdfs\\.server\\.datanode\\.BlockPoolSliceStorage"
      + "\\.doTransition\\(BlockPoolSliceStorage\\.java:42[1-4]\\))");

  private enum Mode { DN_DOWN_FIRST, CE_ORDER, CONTROL }

  @TempDir
  java.nio.file.Path baseDir;

  private String tag;

  private void say(String s) {
    System.out.println("[MC-3][" + tag + "] " + s);
  }

  private static File bpRoot(File vol, String bpid) {
    return new File(new File(vol, "current"), bpid);
  }

  private static long readCTime(File versionFile) throws IOException {
    Properties p = new Properties();
    try (InputStream in = new FileInputStream(versionFile)) {
      p.load(in);
    }
    return Long.parseLong(p.getProperty("cTime"));
  }

  private String describeVolumes(File[] vols, String bpid) throws IOException {
    StringBuilder sb = new StringBuilder();
    for (int i = 0; i < vols.length; i++) {
      File bp = bpRoot(vols[i], bpid);
      File prev = new File(bp, "previous");
      sb.append(String.format("%n    vol%d %s: marker=%s previous/=%s"
              + " finalized.tmp=%s current.cTime=%d%s", i + 1, bp,
          new File(bp, MARKER).exists(), prev.exists(),
          new File(bp, "finalized.tmp").exists(),
          readCTime(new File(bp, "current/VERSION")),
          prev.exists()
              ? " previous.cTime=" + readCTime(new File(prev, "VERSION"))
              : ""));
    }
    return sb.toString();
  }

  private static boolean allHaveMarker(File[] vols, String bpid, boolean want) {
    for (File v : vols) {
      if (new File(bpRoot(v, bpid), MARKER).exists() != want) {
        return false;
      }
    }
    return true;
  }

  private static boolean noFinalizeInFlight(File[] vols, String bpid) {
    for (File v : vols) {
      if (new File(bpRoot(v, bpid), "finalized.tmp").exists()) {
        return false;
      }
    }
    return true;
  }

  private static long nnCTime(MiniDFSCluster cluster) {
    return cluster.getNamesystem().getFSImage().getStorage().getCTime();
  }

  private void printMatchingLines(String log, String... needles) {
    for (String line : log.split("\n")) {
      for (String n : needles) {
        if (line.contains(n)) {
          say("  log| " + line.trim());
          break;
        }
      }
    }
  }

  /** Result of one run of the scenario. */
  private static final class Outcome {
    private boolean targetThrown;
    private String targetTrace = "";
    private String targetFrame = null;
    private boolean previousSurvivedOnAllVolumes;
    private boolean dnServesBlockPool;
    private boolean fileReadable;
  }

  private Outcome runScenario(Mode mode) throws Exception {
    tag = mode.name();
    final boolean dnDownAcrossRuFinalize = mode != Mode.CONTROL;
    final Configuration conf = new HdfsConfiguration();
    // Same DataNode setting as TestDFSUpgrade#testUpgrade.
    conf.setBoolean(DFSConfigKeys.DFS_DATANODE_DUPLICATE_REPLICA_DELETION,
        false);
    // Fail fast on unreadable blocks instead of the default 3 s backoff.
    conf.setInt("dfs.client.retry.window.base", 10);
    final Outcome out = new Outcome();
    final LogCapturer storageLog = LogCapturer.captureLogs(Storage.LOG);
    final LogCapturer dnLog = LogCapturer.captureLogs(DataNode.LOG);
    MiniDFSCluster cluster = new MiniDFSCluster.Builder(conf,
        new File(baseDir.toFile(), tag)).numDataNodes(1).build();
    try {
      cluster.waitActive();
      final String bpid = cluster.getNamesystem().getBlockPoolId();
      final File[] vols = {cluster.getInstanceStorageDir(0, 0),
          cluster.getInstanceStorageDir(0, 1)};
      final Path file = new Path("/mc3/written-before-upgrade.dat");
      DFSTestUtil.createFile(cluster.getFileSystem(), file, 64 * 1024,
          (short) 1, 0x1BADF00DL);
      final String contents = DFSTestUtil.readFile(cluster.getFileSystem(),
          file);
      final long c0 = nnCTime(cluster);
      say("cluster up: 1 NN (non-HA), 1 DN with 2 volumes; bpid=" + bpid
          + " NN cTime c0=" + c0);

      // CE S3: hdfs dfsadmin -safemode enter; -rollingUpgrade prepare
      final DFSAdmin dfsadmin = new DFSAdmin(conf);
      TestRollingUpgrade.runCmd(dfsadmin, true, "-safemode", "enter");
      TestRollingUpgrade.runCmd(dfsadmin, true, "-rollingUpgrade", "prepare");
      // CE S26: the DN learns "RU in progress" from a heartbeat and
      // creates the marker files (BPOfferService.signalRollingUpgrade).
      cluster.triggerHeartbeats();
      GenericTestUtils.waitFor(() -> allHaveMarker(vols, bpid, true), 100,
          30000);
      say("after RU prepare + heartbeat:" + describeVolumes(vols, bpid));

      DataNodeProperties dnprop;
      if (mode == Mode.DN_DOWN_FIRST) {
        // CE S28 + S27: the DN is down while the RU is finalized.
        dnprop = cluster.stopDataNode(0);
        TestRollingUpgrade.runCmd(dfsadmin, true, "-rollingUpgrade",
            "finalize");
        say("DN stopped, then dfsadmin -rollingUpgrade finalize; NN"
            + " rollingUpgradeInfo=" + oneLine(
                cluster.getNamesystem().getRollingUpgradeInfo()));
      } else if (mode == Mode.CE_ORDER) {
        // CE S27 then S28: finalize, then the DN goes down before its next
        // heartbeat. Pausing heartbeats (and letting any in-flight one
        // return) only fixes this order; no state is written.
        DataNodeTestUtils.setHeartbeatsDisabledForTests(
            cluster.getDataNodes().get(0), true);
        Thread.sleep(4000);
        TestRollingUpgrade.runCmd(dfsadmin, true, "-rollingUpgrade",
            "finalize");
        say("dfsadmin -rollingUpgrade finalize; NN rollingUpgradeInfo="
            + oneLine(cluster.getNamesystem().getRollingUpgradeInfo()));
        dnprop = cluster.stopDataNode(0);
        say("DN stopped before its next heartbeat");
      } else {
        TestRollingUpgrade.runCmd(dfsadmin, true, "-rollingUpgrade",
            "finalize");
        cluster.triggerHeartbeats();
        GenericTestUtils.waitFor(() -> allHaveMarker(vols, bpid, false), 100,
            30000);
        dnprop = cluster.stopDataNode(0);
        say("dfsadmin -rollingUpgrade finalize with DN up (markers cleared"
            + " by heartbeat), then DN stopped");
      }
      say("on disk while DN is down:" + describeVolumes(vols, bpid));

      // CE S29: regular upgrade, NameNode restarted with -upgrade.
      cluster.restartNameNode("-upgrade");
      final RollingUpgradeInfo rui =
          cluster.getNamesystem().getRollingUpgradeInfo();
      final long c1 = nnCTime(cluster);
      say("NN restarted with -upgrade: cTime c1=" + c1
          + " isUpgradeFinalized=" + cluster.getNamesystem()
              .isUpgradeFinalized()
          + " rollingUpgradeInfo(replayed)=" + oneLine(rui));
      assertTrue(c1 > c0, "-upgrade must produce a newer NN cTime");

      // CE S30-S68: DN restarted (regular); every volume is upgraded and
      // gets the regular upgrade's previous/ snapshot.
      storageLog.clearOutput();
      cluster.restartDataNode(dnprop, true);
      cluster.waitActive();
      // CE S69: heartbeats carry the (finalized) RU status.
      cluster.triggerHeartbeats();
      if (dnDownAcrossRuFinalize) {
        GenericTestUtils.waitFor(() -> allHaveMarker(vols, bpid, false)
            && noFinalizeInFlight(vols, bpid), 100, 30000);
      } else {
        Thread.sleep(4000);
        cluster.triggerHeartbeats();
        Thread.sleep(1000);
      }
      say("DataNode storage log after the DN restart (in order):");
      printMatchingLines(storageLog.getOutput(), "Upgrade of block pool",
          "Deleting", "Finalizing upgrade for storage directory",
          "Finalize upgrade for");
      say("NN regular upgrade finalized? " + cluster.getNamesystem()
          .isUpgradeFinalized() + "; on disk:" + describeVolumes(vols, bpid));
      boolean allPrev = true;
      for (File v : vols) {
        allPrev &= new File(bpRoot(v, bpid), "previous").exists();
      }
      out.previousSurvivedOnAllVolumes = allPrev;

      // CE S70-S71: documented rollback. Stop the cluster, run
      // "hdfs namenode -rollback", start the NameNode again.
      dnprop = cluster.stopDataNode(0);
      final Configuration nnConf =
          new Configuration(cluster.getConfiguration(0));
      cluster.shutdownNameNode(0);
      NameNode.doRollback(nnConf, false);
      cluster.restartNameNode(0, true);
      final long c2 = nnCTime(cluster);
      say("namenode -rollback done; NN cTime=" + c2 + " (c0=" + c0 + ")");
      assertEquals(c0, c2, "NN rollback must restore the pre-upgrade cTime");

      // CE S72-S83: "datanode -rollback".
      storageLog.clearOutput();
      dnLog.clearOutput();
      dnprop.setDnArgs("-rollback");
      cluster.restartDataNode(dnprop, true);
      final DataNode dn = cluster.getDataNodes().get(0);
      GenericTestUtils.waitFor(() ->
              storageLog.getOutput().contains(TARGET_MSG)
              || (dn.isDatanodeFullyStarted()
                  && cluster.getNamesystem().getNumLiveDataNodes() == 1),
          100, 60000);
      final String slog = storageLog.getOutput();
      out.targetThrown = slog.contains(TARGET_MSG);
      if (out.targetThrown) {
        String[] lines = slog.split("\n");
        int at = -1;
        for (int i = 0; i < lines.length; i++) {
          if (lines[i].contains(TARGET_MSG)) {
            at = i;
            break;
          }
        }
        StringBuilder sb = new StringBuilder();
        for (int i = Math.max(0, at - 1);
             i < Math.min(lines.length, at + 9); i++) {
          sb.append("  | ").append(lines[i].replace("\t", "    "))
              .append('\n');
        }
        out.targetTrace = sb.toString();
        Matcher fm = TARGET_FRAME.matcher(out.targetTrace);
        out.targetFrame = fm.find() ? fm.group(1) : null;
        say("datanode -rollback: target check failed. Captured log:\n"
            + out.targetTrace);
        // Give the BP actor time for its 5 s init retries.
        Thread.sleep(12000);
      } else {
        cluster.waitActive();
      }
      final int live = cluster.getNamesystem().getNumLiveDataNodes();
      final int initFailures = countOccurrences(dnLog.getOutput(),
          "Initialization failed for");
      final int targetHits = countOccurrences(storageLog.getOutput(),
          TARGET_MSG);
      say("after datanode -rollback: live DNs at NN=" + live
          + ", DN fully started=" + dn.isDatanodeFullyStarted()
          + ", BP service alive=" + dn.isBPServiceAlive(bpid)
          + ", 'Initialization failed' log lines=" + initFailures
          + ", L421 hits=" + targetHits + ", NN safemode="
          + cluster.getNamesystem().isInSafeMode());
      printMatchingLines(dnLog.getOutput(), "Initialization failed for");
      say("on disk:" + describeVolumes(vols, bpid));
      out.dnServesBlockPool = live == 1 && dn.isDatanodeFullyStarted();
      try {
        String again = DFSTestUtil.readFile(cluster.getFileSystem(), file);
        out.fileReadable = contents.equals(again);
        say("read " + file + " written before the upgrade: OK, contents "
            + (out.fileReadable ? "identical" : "DIFFERENT"));
      } catch (IOException e) {
        out.fileReadable = false;
        say("read " + file + " written before the upgrade FAILED: "
            + e.getClass().getName() + ": " + oneLine(e.getMessage()));
      }
      return out;
    } finally {
      storageLog.stopCapturing();
      dnLog.stopCapturing();
      cluster.shutdown();
    }
  }

  private static int countOccurrences(String s, String needle) {
    int n = 0;
    for (int i = s.indexOf(needle); i >= 0; i = s.indexOf(needle, i + 1)) {
      n++;
    }
    return n;
  }

  private static String oneLine(Object o) {
    return String.valueOf(o).replaceAll("\\s+", " ").trim();
  }

  private void assertBugTriggered(Outcome o) {
    assertFalse(o.previousSurvivedOnAllVolumes,
        "expected the stale marker to delete the regular upgrade's previous/");
    assertTrue(o.targetThrown, "expected the target check to fail");
    assertTrue(o.targetTrace.contains(TARGET_MSG_PREFIX), o.targetTrace);
    assertNotNull(o.targetFrame,
        "expected a BlockPoolSliceStorage.doTransition frame at lines 421-424"
        + " in:\n" + o.targetTrace);
    assertFalse(o.dnServesBlockPool);
    assertFalse(o.fileReadable);
    say("RESULT: BUG TRIGGERED -- TargetSafe violated, thrown at "
        + o.targetFrame);
  }

  /**
   * A DN that was down across the RU finalize comes back after the regular
   * upgrade, the replayed finalized RU status makes it delete previous/,
   * and the documented rollback fails at the L421 throw. Level 0.
   */
  @Test
  @Timeout(value = 300)
  public void testStaleRuMarkerBreaksRegularUpgradeRollback()
      throws Exception {
    assertBugTriggered(runScenario(Mode.DN_DOWN_FIRST));
  }

  /** Same, with the counterexample's exact S27-then-S28 order. Level 1. */
  @Test
  @Timeout(value = 300)
  public void testCounterexampleOrderFinalizeThenDnStop() throws Exception {
    assertBugTriggered(runScenario(Mode.CE_ORDER));
  }

  /** Same steps, but the DN is up when the RU is finalized. */
  @Test
  @Timeout(value = 300)
  public void testControlDnUpAcrossRuFinalize() throws Exception {
    Outcome o = runScenario(Mode.CONTROL);
    assertTrue(o.previousSurvivedOnAllVolumes);
    assertFalse(o.targetThrown, "control must not reach the target throw");
    assertTrue(o.dnServesBlockPool);
    assertTrue(o.fileReadable);
    say("RESULT: rollback succeeded, no L421");
  }
}
