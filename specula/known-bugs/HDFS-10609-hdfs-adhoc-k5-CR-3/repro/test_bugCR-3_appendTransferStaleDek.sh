#!/usr/bin/env bash
# CR-3 reproduction: DataStreamer.addDatanode2ExistingPipeline never refetches the
# data-encryption key (DEK) after InvalidEncryptionKeyException; it excludes the
# healthy newly-allocated target and retries with the same stale DEK.
#
# Escalation level: 0/1 (public APIs + MiniDFSCluster restart/shutdown of nodes,
# the same utilities TestEncryptedTransfer already uses; no state injection, no
# source change). Built from the workload
#   TestEncryptedTransfer#testEncryptedAppendRequiringBlockTransfer[0]
# combined with the existing TestEncryptedTransfer#testLongLivedWriteClientAfterRestart
# fault (NN + DN restart while a client stays alive).
#
# Usage: test_bugCR-3_appendTransferStaleDek.sh [WORKTREE]
set -euo pipefail
WT=${1:-/users/ZhenyuLi/Specula/runs/20261107-165520-05dd/hdfs-adhoc-k5/.specula-output/confirmation/CR-3/worktree}
OUT=$(cd "$(dirname "$0")" && pwd)
source /bulk/specula-adhoc/hdfs/cases/hdfs-adhoc-k5/env.sh
TDIR=$WT/hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs
CLS=SpeculaReproCR3StaleDekTransferTest
mkdir -p "$TDIR"
cat > "$TDIR/$CLS.java" <<'JAVA'
package org.apache.hadoop.hdfs;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import java.io.IOException;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.FSDataOutputStream;
import org.apache.hadoop.fs.FileSystem;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.hdfs.protocol.DatanodeInfo;
import org.apache.hadoop.hdfs.protocol.HdfsConstants.SafeModeAction;
import org.apache.hadoop.hdfs.protocol.datatransfer.sasl.DataTransferSaslUtil;
import org.apache.hadoop.hdfs.protocol.datatransfer.sasl.SaslDataTransferServer;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.log4j.Level;
import org.apache.log4j.LogManager;
import org.junit.Test;

/** CR-3 reproduction. Setup copied from TestEncryptedTransfer (resolver = null, i.e. param [0]). */
public class SpeculaReproCR3StaleDekTransferTest {
  {
    LogManager.getLogger(SaslDataTransferServer.class).setLevel(Level.DEBUG);
    LogManager.getLogger(DataTransferSaslUtil.class).setLevel(Level.DEBUG);
  }
  private static final String PLAIN_TEXT = "this is very secret plain text";
  private static final Path TEST_PATH = new Path("/non-encrypted-file");

  private static FileSystem getFileSystem(Configuration conf) throws IOException {
    Configuration localConf = new Configuration(conf);
    localConf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, false);
    localConf.unset(DFSConfigKeys.DFS_DATA_ENCRYPTION_ALGORITHM_KEY);
    return FileSystem.get(localConf);
  }

  /**
   * @param numDns cluster size (4 = workload size)
   * @param refreshDekFirst control: read the file after the restart, so the read path's
   *        IEK-refetch logic (DFSInputStream) refreshes the client's DEK before the append
   * @return null if the append succeeded, otherwise the IOException the application saw
   */
  private IOException run(int numDns, boolean refreshDekFirst) throws Exception {
    String tag = "[CR3 numDns=" + numDns + " refreshDekFirst=" + refreshDekFirst + "] ";
    MiniDFSCluster cluster = null;
    try {
      Configuration conf = new Configuration();
      conf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, true);
      conf.setBoolean(DFSConfigKeys.DFS_BLOCK_ACCESS_TOKEN_ENABLE_KEY, true);
      cluster = new MiniDFSCluster.Builder(conf).numDataNodes(numDns).build();
      FileSystem fs = getFileSystem(conf);

      // 1. Long-lived client writes a file (replication 3) -> caches a DEK from NN key set K1.
      FSDataOutputStream o = fs.create(TEST_PATH);
      o.write(PLAIN_TEXT.getBytes());
      o.close();
      assertEquals(PLAIN_TEXT, DFSTestUtil.readFile(fs, TEST_PATH));

      // 2. Restart NN and all DNs (as in testLongLivedWriteClientAfterRestart): the client's
      //    cached DEK is no longer valid at any DN.
      cluster.restartNameNode();
      assertTrue(cluster.restartDataNodes());
      cluster.waitActive();
      DistributedFileSystem dfs = (DistributedFileSystem) fs;
      while (dfs.setSafeMode(SafeModeAction.SAFEMODE_GET)) { Thread.sleep(200); }
      DFSTestUtil.waitReplication(fs, TEST_PATH, (short) 3);

      if (refreshDekFirst) {
        assertEquals(PLAIN_TEXT, DFSTestUtil.readFile(fs, TEST_PATH));
      }

      // 3. Workload: reopen for append; the streamer sets up the pipeline only when data
      //    arrives. The first DN of the append pipeline crashes before that (real DN fault).
      FSDataOutputStream out = fs.append(TEST_PATH);
      DatanodeInfo[] pipeline = ((DFSOutputStream) out.getWrappedStream()).getPipeline();
      assertNotNull(pipeline);
      System.out.println(tag + "append pipeline = " + java.util.Arrays.toString(pipeline));
      DataNode dn = cluster.getDataNode(pipeline[0].getIpcPort());
      System.out.println(tag + "shutting down pipeline[0] = " + pipeline[0]);
      dn.shutdown();

      // 4. Write; recovery removes the dead DN and must add a DN by block transfer.
      IOException seen = null;
      try {
        out.write(PLAIN_TEXT.getBytes());
        out.close();
      } catch (IOException e) {
        seen = e;
        System.out.println(tag + "APPLICATION SAW: " + e);
        e.printStackTrace(System.out);
      }
      if (seen == null) {
        assertEquals(PLAIN_TEXT + PLAIN_TEXT, DFSTestUtil.readFile(fs, TEST_PATH));
        System.out.println(tag + "append succeeded, content verified");
      }
      fs.close();
      return seen;
    } finally {
      if (cluster != null) {
        cluster.shutdown();
      }
    }
  }

  @Test(timeout = 300000)
  public void testStaleDekAppendTransfer4Dns() throws Exception {
    IOException e = run(4, false);
    System.out.println("[CR3 RESULT 4dn] " + (e == null ? "append OK (bug NOT triggered)"
        : "BUG TRIGGERED: append failed: " + e));
    assertNotNull("expected failure from stale DEK in transfer", e);
  }

  @Test(timeout = 300000)
  public void testStaleDekAppendTransfer6Dns() throws Exception {
    IOException e = run(6, false);
    System.out.println("[CR3 RESULT 6dn] " + (e == null ? "append OK (bug NOT triggered)"
        : "BUG TRIGGERED: append failed: " + e));
    assertNotNull("expected failure from stale DEK in transfer", e);
  }

  @Test(timeout = 300000)
  public void testControlFreshDek6Dns() throws Exception {
    IOException e = run(6, true);
    System.out.println("[CR3 RESULT control] " + (e == null ? "append OK with fresh DEK"
        : "control FAILED: " + e));
    assertEquals(null, e);
  }
}
JAVA

cd "$WT"
LOG=$OUT/CR-3.mvn.log
set +e
timeout 40m mvn -B -o test -Dmaven.javadoc.skip=true -Dmaven-surefire-plugin.version=2.20.1 \
  -pl hadoop-hdfs-project/hadoop-hdfs -Dtest="$CLS" -DfailIfNoTests=false \
  -Dsurefire.failIfNoSpecifiedTests=false > "$LOG" 2>&1
RC=$?
set -e
echo "mvn exit code: $RC (log: $LOG)"
REP=$WT/hadoop-hdfs-project/hadoop-hdfs/target/surefire-reports
cp "$REP/org.apache.hadoop.hdfs.$CLS-output.txt" "$OUT/CR-3.test-output.txt" 2>/dev/null || true
grep -E "Tests run:|FAIL|ERROR\]" "$LOG" | tail -8
F=$OUT/CR-3.test-output.txt
echo "---- key lines ----"
grep -E "\[CR3|Error transferring data|Will fetch a new encryption key|BlockTokenSecretManager.java:420|InvalidEncryptionKeyException: Can't re-compute" "$F" | cut -c1-400 | head -80
exit $RC
