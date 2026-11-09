#!/usr/bin/env bash
# CR-5 reproduction: FileChecksumHelper never clears a stale DEK on
# InvalidEncryptionKeyException, so getFileChecksum() of a long-lived client
# fails on every DN after an NN+DN restart, while read() recovers.
#
# Level 0 (pure black-box): public FileSystem API + MiniDFSCluster restarts,
# exactly the restart sequence of TestEncryptedTransfer#testLongLivedReadClientAfterRestart
# (the workload test's class), with only the order of the two post-restart
# calls swapped (getFileChecksum before readFile). No source patch, no state
# injection, no mocks. DFSClient#getEncryptionKey() (@VisibleForTesting
# getter) is used only to OBSERVE the cached DEK id.
#
# Usage: test_bugCR-5_checksum_stale_dek.sh [WORKTREE]
set -euo pipefail
WT=${1:-/users/ZhenyuLi/Specula/runs/20261107-165556-fca6/hdfs-adhoc-k3/.specula-output/confirmation/CR-5/worktree}
source /bulk/specula-adhoc/hdfs/cases/hdfs-adhoc-k3/env.sh
TDIR=$WT/hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs
mkdir -p "$TDIR"
cat > "$TDIR/TestBugCR5ChecksumStaleDek.java" <<'EOF'
package org.apache.hadoop.hdfs;

import static org.junit.Assert.*;

import java.io.IOException;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.FileChecksum;
import org.apache.hadoop.fs.FileSystem;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.hdfs.security.token.block.DataEncryptionKey;
import org.junit.Test;

public class TestBugCR5ChecksumStaleDek {
  private static final String PLAIN_TEXT = "this is very secret plain text";
  private static final Path P = new Path("/cr5-file");

  private static void say(String s) { System.out.println("CR5> " + s); System.out.flush(); }

  private static String dek(DFSClient c) {
    DataEncryptionKey k = c.getEncryptionKey();
    return k == null ? "null" : ("keyId=" + k.keyId + " expiry=" + k.expiryDate);
  }

  @Test(timeout = 240000)
  public void checksumAfterRestartWithoutPriorRead() throws Exception {
    Configuration conf = new Configuration();
    // same keys as TestEncryptedTransfer#setEncryptionConfigKeys (resolver param [0] = null)
    conf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, true);
    conf.setBoolean(DFSConfigKeys.DFS_BLOCK_ACCESS_TOKEN_ENABLE_KEY, true);
    MiniDFSCluster cluster = new MiniDFSCluster.Builder(conf).numDataNodes(3).build();
    try {
      cluster.waitActive();
      // Same as TestEncryptedTransfer#getFileSystem: client learns encryption from NN.
      Configuration cconf = new Configuration(conf);
      cconf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, false);
      FileSystem fs = FileSystem.get(cconf);
      DFSClient client = ((DistributedFileSystem) fs).getClient();

      DFSTestUtil.writeFile(fs, P, PLAIN_TEXT);
      DFSTestUtil.waitReplication(fs, P, (short) 3);
      assertEquals(PLAIN_TEXT, DFSTestUtil.readFile(fs, P));
      FileChecksum expected = fs.getFileChecksum(P);
      say("baseline checksum=" + expected + " cachedDEK " + dek(client));

      // Same restart sequence as testLongLivedReadClientAfterRestart (all DNs).
      cluster.restartNameNode();
      assertTrue(cluster.restartDataNodes());
      cluster.waitActive();
      DFSTestUtil.waitReplication(fs, P, (short) 3);   // NN RPC only, no data transfer
      say("after NN+DN restart: NN currentKeyId=" + cluster.getNamesystem().getBlockManager()
          .getBlockTokenSecretManager().generateDataEncryptionKey().keyId
          + " client cachedDEK " + dek(client));

      // (A) long-lived client: getFileChecksum first, no read in between.
      int failures = 0;
      for (int attempt = 1; attempt <= 3; attempt++) {
        try {
          FileChecksum c = fs.getFileChecksum(P);
          say("attempt " + attempt + ": getFileChecksum OK " + c);
        } catch (IOException e) {
          failures++;
          say("attempt " + attempt + ": getFileChecksum FAILED: " + e
              + " | cachedDEK still " + dek(client));
        }
      }

      // (B) Control 1: a fresh client (no cached DEK) gets the checksum fine.
      FileSystem fresh = FileSystem.newInstance(cconf);
      FileChecksum freshSum = fresh.getFileChecksum(P);
      say("control fresh client getFileChecksum OK equal=" + expected.equals(freshSum));
      fresh.close();

      // (C) Control 2: same long-lived client: a read clears the DEK
      // (DFSInputStream.java:584-590) and retries; afterwards checksum works.
      String data = DFSTestUtil.readFile(fs, P);
      say("long-lived client readFile OK equal=" + PLAIN_TEXT.equals(data)
          + " cachedDEK now " + dek(client));
      FileChecksum after = fs.getFileChecksum(P);
      say("long-lived client getFileChecksum after read OK equal=" + expected.equals(after));

      say("RESULT: getFileChecksum failures before read = " + failures + "/3");
      if (failures == 3) {
        say("BUG CR-5 REPRODUCED: stale DEK never cleared by FileChecksumHelper; "
            + "getFileChecksum fails on every DN until an unrelated read clears it");
      }
      assertEquals("expected getFileChecksum to fail on every attempt (bug)", 3, failures);
      fs.close();
    } finally {
      cluster.shutdown();
    }
  }
}
EOF
cd "$WT"
timeout 40m mvn -B -o test -pl hadoop-hdfs-project/hadoop-hdfs \
  -Dtest=TestBugCR5ChecksumStaleDek -DfailIfNoTests=false \
  -Dsurefire.failIfNoSpecifiedTests=false -Dmaven.javadoc.skip=true \
  -Denforcer.skip=true 2>&1 | tail -40 || true
OUT=$WT/hadoop-hdfs-project/hadoop-hdfs/target/surefire-reports/org.apache.hadoop.hdfs.TestBugCR5ChecksumStaleDek-output.txt
echo "===== CR5 markers ====="
grep -h "CR5>" "$OUT" || true
echo "===== client-side: per-DN failures inside FileChecksumHelper ====="
grep -h "FileChecksumHelper" "$OUT" | grep -i "WARN" | head -6 || true
grep -h -m3 "InvalidEncryptionKeyException" "$OUT" | head -3 || true
# The throw statement spans BlockTokenSecretManager.java:490-492 (guard key==null at 489);
# javac attributes the exception's <init> frame to the statement's last line (492).
echo "===== DN-side: target frame BlockTokenSecretManager.java:490-492 ====="
grep -h -B1 -m1 -E "retrieveDataEncryptionKey\(BlockTokenSecretManager.java:49[0-2]\)" "$OUT" | head -4 || true
echo "count of target-frame hits: $(grep -cE 'retrieveDataEncryptionKey\(BlockTokenSecretManager.java:49[0-2]\)' "$OUT" || true)"
