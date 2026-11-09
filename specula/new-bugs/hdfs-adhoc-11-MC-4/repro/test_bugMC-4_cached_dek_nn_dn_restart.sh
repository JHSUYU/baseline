#!/usr/bin/env bash
# Specula MC-4 reproduction: an NN restart plus a DN restart invalidate a
# long-lived client's cached DEK; the restarted DN throws
# InvalidEncryptionKeyException at BlockTokenSecretManager.java:559-561.
#
# Escalation level: 0 (public client APIs + MiniDFSCluster's own restart
# utilities; no failpoints, no state injection, no product-code change).
#
# What it does:
#   1. checks that the worktree is the pinned base commit with NO source changes
#      (the harness instrumentation was reverted; backup in
#      confirmation/MC-4/instrumentation-backup/);
#   2. installs the embedded JUnit test TestSpeculaMC4CachedDekAfterRestart
#      (a variant of TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[1]
#      in the same module/package) and compiles the test sources offline;
#   3. runs it: 2 DNs, long-lived clients cache an incarnation-1 DEK, NN restart,
#      d1 restart, then each client path connects to d1 with its cached DEK;
#   4. runs the unmodified in-tree TestEncryptedTransfer#testLongLivedReadClientAfterRestart
#      and greps its log for the DN-side target frame;
#   5. prints the evidence lines.
# Usage: test_bugMC-4_cached_dek_nn_dn_restart.sh [worktree]
set -u
WT=${1:-/users/ZhenyuLi/Specula/runs/20261029-002846-8337/hdfs-adhoc-11/.specula-output/confirmation/MC-4/worktree}
ENV_SH=/bulk/specula-adhoc/hdfs/cases/hdfs-adhoc-11/env.sh
BASE=734dd8a67cd
MOD=hadoop-hdfs-project/hadoop-hdfs
TEST_SRC=$WT/$MOD/src/test/java/org/apache/hadoop/hdfs/TestSpeculaMC4CachedDekAfterRestart.java
REPORTS=$WT/$MOD/target/surefire-reports

source "$ENV_SH"
cd "$WT"
echo "== worktree: $WT"
echo "== HEAD: $(git rev-parse --short=11 HEAD) (expected $BASE)"
[ "$(git rev-parse --short=11 HEAD)" = "$BASE" ] || { echo "wrong commit"; exit 2; }
if ! git diff --quiet HEAD -- hadoop-hdfs-project hadoop-common-project; then
  echo "source tree is modified; refusing to run"; git status --short; exit 2
fi
echo "== tracked sources unmodified: yes"

mkdir -p "$(dirname "$TEST_SRC")"
cat > "$TEST_SRC" <<'JAVA_EOF'
/*
 * Specula MC-4 reproduction (not part of Apache Hadoop).
 *
 * A variant, in the workload's module and package, of
 * TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[1]
 * (resolverClazz = null, algorithm "", cipher suites ""). It realizes
 * counterexample spec/output/hunt/gated/G_S4a_backward.out
 * (MaxNNRestart = 1, MaxDNRestart = 1, NNs = {n1}, DNs = {d1, d2}):
 *   states 2-7  long-lived clients cache a DEK of NN incarnation 1 (MCClientGetDek)
 *   state 8     the NN restarts (MCNNRestart)
 *   states 10-12 d1 restarts and re-registers with incarnation 2 (MCDNRestart,
 *               MCNNRegisterDatanode, MCDNRegistrationSucceeded)
 *   state 13    a client connects to d1 with its cached DEK (MCClientConnect(d1))
 *               and d1 throws InvalidEncryptionKeyException at
 *               BlockTokenSecretManager.java:559-561.
 * Faults are injected only with MiniDFSCluster.restartNameNode/restartDataNode,
 * as TestEncryptedTransfer#testLongLivedReadClientAfterRestart does. No product
 * code is changed and no guard operand is written; hasKey, getCurrentKey and
 * getEncryptionKey are only read.
 */
package org.apache.hadoop.hdfs;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.FSDataInputStream;
import org.apache.hadoop.fs.FSDataOutputStream;
import org.apache.hadoop.fs.FileChecksum;
import org.apache.hadoop.fs.FileSystem;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.hdfs.client.HdfsClientConfigKeys;
import org.apache.hadoop.hdfs.protocol.DatanodeInfo;
import org.apache.hadoop.hdfs.protocol.LocatedBlock;
import org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager;
import org.apache.hadoop.hdfs.security.token.block.DataEncryptionKey;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.slf4j.LoggerFactory;
import org.slf4j.event.Level;

public class TestSpeculaMC4CachedDekAfterRestart {
  private static final String PLAIN_TEXT = "this is very secret plain text";
  private static final Path DIR = new Path("/mc4");
  private static final Path FILE = new Path(DIR, "file");
  private static final Path SNAP_FILE = new Path(DIR, ".snapshot/s1/file");
  private static final String TARGET_EXC =
      "org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException";
  /** Frame of the target throw (BlockTokenSecretManager.java:559-561). */
  private static final String TARGET_FRAME =
      "at org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager"
          + ".retrieveDataEncryptionKey(BlockTokenSecretManager.java:";
  private static final Pattern TARGET_MSG = Pattern.compile(
      "required block key \\(keyID=(-?\\d+)\\) doesn't exist\\. "
          + "Current key: (-?\\d+)");

  private interface Op {
    /** Runs one client operation; returns whether its result is correct. */
    boolean run() throws Exception;
  }

  private static final class PathResult {
    int dnThrows;
    boolean refetched;
    boolean correct;
    String detail = "";
  }

  private static void ev(String s) {
    System.out.println("MC4-EVIDENCE " + s);
    System.out.flush();
  }

  private static final AtomicInteger CLIENTS = new AtomicInteger();

  /**
   * TestEncryptedTransfer.getFileSystem (TestEncryptedTransfer.java:104-109),
   * but a new instance with its own client context, so that each long-lived
   * client behaves like a separate client process: its own DFSClient, its own
   * cached DEK (DFSClient.java:1855-1868) and its own peer cache (DFSClients
   * of one JVM otherwise share the "default" ClientContext and its sockets).
   */
  private static DistributedFileSystem newClient(Configuration conf)
      throws IOException {
    Configuration localConf = new Configuration(conf);
    localConf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, false);
    localConf.unset(DFSConfigKeys.DFS_DATA_ENCRYPTION_ALGORITHM_KEY);
    localConf.set(HdfsClientConfigKeys.DFS_CLIENT_CONTEXT,
        "mc4-client-" + CLIENTS.incrementAndGet());
    return (DistributedFileSystem) FileSystem.newInstance(localConf);
  }

  private static int keyIdOf(DistributedFileSystem fs) {
    DataEncryptionKey k = fs.getClient().getEncryptionKey();
    assertNotNull(k, "client has no cached DEK");
    return k.keyId;
  }

  private static int count(String text, String needle) {
    int n = 0;
    for (int i = text.indexOf(needle); i >= 0;
        i = text.indexOf(needle, i + 1)) {
      n++;
    }
    return n;
  }

  private static void excerpt(String label, String text, String... needles) {
    for (String line : text.split("\n")) {
      for (String needle : needles) {
        if (line.contains(needle)) {
          ev(label + " | " + line.trim());
          break;
        }
      }
    }
  }

  private static void waitSafeModeOff(MiniDFSCluster cluster)
      throws Exception {
    GenericTestUtils.waitFor(() -> !cluster.getNamesystem().isInSafeMode(),
        100, 120000);
  }

  /**
   * CE state 13 (MCClientConnect(d1)) through one client path that uses the
   * cached DEK. Records the DN-side target throw, the client's DEK before and
   * after, and whether the operation's result is correct.
   */
  private static PathResult clientPath(String name, DistributedFileSystem client,
      int staleKeyId, BlockTokenSecretManager d1Keys, LogCapturer dnLog,
      List<LogCapturer> clientLogs, Op op) throws Exception {
    PathResult r = new PathResult();
    final int throwsBefore = count(dnLog.getOutput(), TARGET_FRAME);
    final int dnStart = dnLog.getOutput().length();
    int[] clStart = new int[clientLogs.size()];
    for (int i = 0; i < clStart.length; i++) {
      clStart[i] = clientLogs.get(i).getOutput().length();
    }
    ev(name + ": client cached DEK keyId before = " + staleKeyId);
    r.correct = op.run();
    try {
      // DataXceiver logs after it has sent ERROR_UNKNOWN_KEY to the client.
      GenericTestUtils.waitFor(
          () -> count(dnLog.getOutput(), TARGET_FRAME) > throwsBefore,
          100, 10000);
    } catch (TimeoutException e) {
      // reported below as 0 throws
    }
    Thread.sleep(300);
    String dnText = dnLog.getOutput().substring(dnStart);
    r.dnThrows = count(dnText, TARGET_FRAME);
    ev(name + ": target throws at d1 during this operation = " + r.dnThrows);
    Matcher m = TARGET_MSG.matcher(dnText);
    if (m.find()) {
      ev(name + ": d1 message keyID=" + m.group(1)
          + " (= client's cached DEK keyId " + staleKeyId + "), "
          + "d1 currentKey=" + m.group(2));
    }
    excerpt(name + " DN", dnText, "DataXceiver error processing",
        "Caused by: " + TARGET_EXC, TARGET_FRAME,
        "BlockPoolTokenSecretManager.retrieveDataEncryptionKey",
        "SaslDataTransferServer.getEncryptionKeyFromUserName");
    for (int i = 0; i < clStart.length; i++) {
      excerpt(name + " CLIENT",
          clientLogs.get(i).getOutput().substring(clStart[i]),
          "Will fetch a new encryption key", "Got invalid encryption key",
          "Clearing encryption key", "Getting new encryption token from NN");
    }
    int newKeyId = keyIdOf(client);
    r.refetched = newKeyId != staleKeyId && d1Keys.hasKey(newKeyId);
    ev(name + ": client DEK keyId " + staleKeyId + " -> " + newKeyId
        + "; restarted d1 hasKey(" + newKeyId + ")="
        + d1Keys.hasKey(newKeyId));
    ev(name + ": result correct = " + r.correct + " " + r.detail);
    return r;
  }

  @Test
  @Timeout(600)
  public void testLongLivedClientsAfterNameNodeAndDataNodeRestart()
      throws Exception {
    GenericTestUtils.setLogLevel(
        LoggerFactory.getLogger(FileChecksumHelper.class), Level.DEBUG);
    GenericTestUtils.setLogLevel(
        LoggerFactory.getLogger(DFSClient.class), Level.DEBUG);

    Configuration conf = new Configuration();
    // testEncryptedReadDefaultAlgorithmCipherSuite[1]:
    // testEncryptedRead("", "", false, false) with resolverClazz == null.
    conf.set(DFSConfigKeys.DFS_DATA_ENCRYPTION_ALGORITHM_KEY, "");
    conf.set(HdfsClientConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_CIPHER_SUITES_KEY,
        "");
    // setEncryptionConfigKeys() (TestEncryptedTransfer.java:93-99).
    conf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, true);
    conf.setBoolean(DFSConfigKeys.DFS_BLOCK_ACCESS_TOKEN_ENABLE_KEY, true);

    // CE topology: NNs = {n1}, DNs = {d1, d2}.
    MiniDFSCluster cluster =
        new MiniDFSCluster.Builder(conf).numDataNodes(2).build();
    List<FileSystem> opened = new ArrayList<>();
    LogCapturer dnLog = null;
    List<LogCapturer> clientLogs = new ArrayList<>();
    try {
      cluster.waitActive();
      final String bpid = cluster.getNamesystem().getBlockPoolId();
      dnLog = LogCapturer.captureLogs(LoggerFactory.getLogger(DataNode.class));
      clientLogs.add(LogCapturer.captureLogs(
          LoggerFactory.getLogger(DFSClient.class)));
      clientLogs.add(LogCapturer.captureLogs(
          LoggerFactory.getLogger(DataStreamer.class)));
      clientLogs.add(LogCapturer.captureLogs(
          LoggerFactory.getLogger(FileChecksumHelper.class)));

      // The workload's file, with its only replica on d1; the directory is
      // snapshottable and snapshot s1 holds the same bytes.
      DistributedFileSystem admin = newClient(conf);
      opened.add(admin);
      admin.mkdirs(DIR);
      try (FSDataOutputStream out = admin.create(FILE, (short) 1)) {
        out.write(PLAIN_TEXT.getBytes(StandardCharsets.UTF_8));
      }
      admin.allowSnapshot(DIR);
      admin.createSnapshot(DIR, "s1");
      LocatedBlock lb = DFSTestUtil.getAllBlocks(admin, FILE).get(0);
      final DatanodeInfo holder = lb.getLocations()[0];
      int idx = -1;
      for (int i = 0; i < cluster.getDataNodes().size(); i++) {
        if (cluster.getDataNodes().get(i).getDatanodeUuid()
            .equals(holder.getDatanodeUuid())) {
          idx = i;
        }
      }
      assertTrue(idx >= 0);
      final int d1Index = idx;
      final DataNode d2 = cluster.getDataNodes().get(1 - d1Index);
      ev("setup: 2 DNs, encrypted transfer (algorithm '', cipher suites '', "
          + "no trusted-channel resolver); block " + lb.getBlock()
          + " has its only replica on d1=" + holder.getXferAddr()
          + "; d2=" + d2.getDatanodeId().getXferAddr());

      // CE states 2-7: every long-lived client caches a DEK issued by NN
      // incarnation 1 through the workload's own operation (encrypted read).
      final String[] names = {"stateful-read", "pread", "checksum-whole-file",
          "checksum-snapshot-path", "checksum-explicit-length", "append",
          "control-nn-restart-only"};
      final DistributedFileSystem[] c = new DistributedFileSystem[names.length];
      final int[] stale = new int[names.length];
      for (int i = 0; i < names.length; i++) {
        c[i] = newClient(conf);
        opened.add(c[i]);
        assertEquals(PLAIN_TEXT, DFSTestUtil.readFile(c[i], FILE));
        stale[i] = keyIdOf(c[i]);
        ev("pre-restart: client '" + names[i] + "' read OK; cached DEK keyId="
            + stale[i] + ", expires in "
            + (c[i].getClient().getEncryptionKey().expiryDate
                - org.apache.hadoop.util.Time.now()) / 1000 + " s");
      }
      // Correct checksums, computed before any restart by the same clients.
      final long len = PLAIN_TEXT.length();
      final FileChecksum whole = c[2].getFileChecksum(FILE);
      final FileChecksum snap = c[3].getFileChecksum(SNAP_FILE);
      final FileChecksum prefix = c[4].getFileChecksum(FILE, len);
      ev("pre-restart checksums: whole=" + whole + " snapshot=" + snap
          + " length(" + len + ")=" + prefix);
      final int nn1Cur = cluster.getNamesystem().getBlockManager()
          .getBlockTokenSecretManager().getCurrentKey().getKeyId();
      ev("NN incarnation 1 currentKey=" + nn1Cur);
      assertEquals(0, count(dnLog.getOutput(), TARGET_FRAME));
      ev("control-0 (no restart): target throws at the DNs = 0");

      // CE state 8: the NN restarts. New master BlockTokenSecretManager with a
      // fresh random serial number (BlockTokenSecretManager.java:140-158).
      cluster.restartNameNode();
      cluster.waitActive();
      waitSafeModeOff(cluster);
      final BlockTokenSecretManager nn2 = cluster.getNamesystem()
          .getBlockManager().getBlockTokenSecretManager();
      final int nn2Cur = nn2.getCurrentKey().getKeyId();
      ev("NN incarnation 2 currentKey=" + nn2Cur + "; incarnation 2 hasKey("
          + stale[0] + ")=" + nn2.hasKey(stale[0]));

      // Control 1: the NN restart alone. d1 re-registers with incarnation 2
      // and merges its keys into the old worker (BPOfferService.java:436-440,
      // BlockTokenSecretManager.java:228-244), so a stale DEK still works.
      final DataNode d1Old = cluster.getDataNodes().get(d1Index);
      GenericTestUtils.waitFor(() -> d1Old.getBlockPoolTokenSecretManager()
          .get(bpid).hasKey(nn2Cur), 100, 60000);
      ev("after the NN restart, before the DN restart: d1 hasKey(" + stale[6]
          + ")=" + d1Old.getBlockPoolTokenSecretManager().get(bpid)
              .hasKey(stale[6]) + ", hasKey(" + nn2Cur + ")=true");
      int before = count(dnLog.getOutput(), TARGET_FRAME);
      assertEquals(PLAIN_TEXT, DFSTestUtil.readFile(c[6], FILE));
      Thread.sleep(1000);
      assertEquals(before, count(dnLog.getOutput(), TARGET_FRAME));
      assertEquals(stale[6], keyIdOf(c[6]));
      ev("control-1 (NN restart only): stale-DEK client read from d1 OK; "
          + "target throws = 0; client kept DEK keyId " + stale[6]);

      // CE states 10-12: d1 restarts. The new DataNode has a new
      // BlockPoolTokenSecretManager (DataNode.java:1942) and worker
      // (DataNode.java:2130-2145) that learns only incarnation-2 keys when it
      // registers (BPOfferService.java:436-440).
      assertTrue(cluster.restartDataNode(d1Index, true));
      cluster.waitActive();
      final DataNode d1 =
          cluster.getDataNodes().get(cluster.getDataNodes().size() - 1);
      assertEquals(holder.getDatanodeUuid(), d1.getDatanodeUuid());
      GenericTestUtils.waitFor(() -> d1.getBlockPoolTokenSecretManager()
          .isBlockPoolRegistered(bpid)
          && d1.getBlockPoolTokenSecretManager().get(bpid).hasKey(nn2Cur),
          100, 60000);
      cluster.waitFirstBRCompleted(0, 60000);
      DFSTestUtil.waitReplication(admin, FILE, (short) 1);
      waitSafeModeOff(cluster);
      final BlockTokenSecretManager d1Keys =
          d1.getBlockPoolTokenSecretManager().get(bpid);
      final BlockTokenSecretManager d2Keys =
          d2.getBlockPoolTokenSecretManager().get(bpid);
      StringBuilder held = new StringBuilder();
      for (int i = 0; i < 6; i++) {
        assertEquals(stale[i], keyIdOf(c[i]));
        assertFalse(d1Keys.hasKey(stale[i]));
        held.append(i == 0 ? "" : ",").append(stale[i]);
      }
      ev("CE state 12 realized: restarted d1 currentKey="
          + d1Keys.getCurrentKey().getKeyId() + ", d1 hasKey(" + stale[0]
          + ")=false; non-restarted d2 hasKey(" + stale[0] + ")="
          + d2Keys.hasKey(stale[0]) + "; clients still cache DEK keyIds "
          + held);

      // CE state 13 through every client path that uses the cached DEK.
      Map<String, PathResult> results = new LinkedHashMap<>();
      final LogCapturer dn = dnLog;
      results.put(names[0], clientPath(names[0], c[0], stale[0], d1Keys, dn,
          clientLogs,
          () -> PLAIN_TEXT.equals(DFSTestUtil.readFile(c[0], FILE))));
      results.put(names[1], clientPath(names[1], c[1], stale[1], d1Keys, dn,
          clientLogs, () -> {
            byte[] buf = new byte[PLAIN_TEXT.length()];
            try (FSDataInputStream in = c[1].open(FILE)) {
              in.readFully(0, buf);
            }
            return PLAIN_TEXT.equals(new String(buf, StandardCharsets.UTF_8));
          }));
      final FileChecksum[] got = new FileChecksum[3];
      results.put(names[2], clientPath(names[2], c[2], stale[2], d1Keys, dn,
          clientLogs, () -> {
            got[0] = c[2].getFileChecksum(FILE);
            ev(names[2] + ": expected " + whole + ", got " + got[0]);
            return whole.equals(got[0]);
          }));
      results.put(names[3], clientPath(names[3], c[3], stale[3], d1Keys, dn,
          clientLogs, () -> {
            got[1] = c[3].getFileChecksum(SNAP_FILE);
            ev(names[3] + ": expected " + snap + ", got " + got[1]);
            return snap.equals(got[1]);
          }));
      results.put(names[4], clientPath(names[4], c[4], stale[4], d1Keys, dn,
          clientLogs, () -> {
            got[2] = c[4].getFileChecksum(FILE, len);
            ev(names[4] + ": expected " + prefix + ", got " + got[2]);
            return prefix.equals(got[2]);
          }));

      // Controls for the checksum results: the same calls with no stale DEK
      // (no target throw, so no retry) return the pre-restart values.
      int t0 = count(dnLog.getOutput(), TARGET_FRAME);
      DistributedFileSystem fresh = newClient(conf);
      opened.add(fresh);
      boolean freshOk = snap.equals(fresh.getFileChecksum(SNAP_FILE))
          && prefix.equals(fresh.getFileChecksum(FILE, len))
          && whole.equals(fresh.getFileChecksum(FILE));
      boolean againOk = snap.equals(c[3].getFileChecksum(SNAP_FILE))
          && prefix.equals(c[4].getFileChecksum(FILE, len));
      Thread.sleep(1000);
      int t1 = count(dnLog.getOutput(), TARGET_FRAME);
      ev("control-2: fresh client (DEK of incarnation 2) snapshot/length/whole"
          + " checksums correct = " + freshOk + "; the same long-lived clients"
          + " repeating snapshot/length checksums with their refetched DEK"
          + " correct = " + againOk + "; target throws during control-2 = "
          + (t1 - t0));

      results.put(names[5], clientPath(names[5], c[5], stale[5], d1Keys, dn,
          clientLogs, () -> {
            try (FSDataOutputStream out = c[5].append(FILE)) {
              out.write(PLAIN_TEXT.getBytes(StandardCharsets.UTF_8));
            }
            return true;
          }));
      DistributedFileSystem verifier = newClient(conf);
      opened.add(verifier);
      boolean appended = (PLAIN_TEXT + PLAIN_TEXT)
          .equals(DFSTestUtil.readFile(verifier, FILE));
      results.get(names[5]).correct = appended;
      ev("append: a fresh client reads back both copies = " + appended);

      ev("SUMMARY path | target throws at d1 | DEK cleared+refetched | "
          + "caller's result correct");
      boolean allFired = true;
      boolean allRefetched = true;
      List<String> wrong = new ArrayList<>();
      for (Map.Entry<String, PathResult> e : results.entrySet()) {
        PathResult r = e.getValue();
        ev("SUMMARY " + e.getKey() + " | " + r.dnThrows + " | " + r.refetched
            + " | " + r.correct);
        allFired &= r.dnThrows >= 1;
        allRefetched &= r.refetched;
        if (!r.correct) {
          wrong.add(e.getKey());
        }
      }
      ev("RESULT target fired on every stale-DEK path = " + allFired
          + "; DEK refetched on every path = " + allRefetched
          + "; paths whose caller got a wrong result = " + wrong
          + "; controls: fresh/repeat checksums correct = "
          + (freshOk && againOk));
      assertTrue(allFired, "the target did not fire on every path");
      assertTrue(allRefetched, "the DEK was not refetched on every path");
      assertTrue(freshOk && againOk, "control checksums are wrong");
    } finally {
      if (dnLog != null) {
        dnLog.stopCapturing();
      }
      for (LogCapturer l : clientLogs) {
        l.stopCapturing();
      }
      for (FileSystem fs : opened) {
        try {
          fs.close();
        } catch (IOException ignored) {
          // best effort
        }
      }
      cluster.shutdown();
    }
  }
}
JAVA_EOF
echo "== installed $TEST_SRC"

echo "== compiling test sources (offline)"
timeout 30m mvn -B -o -q test-compile -pl $MOD -Dmaven.javadoc.skip=true \
  > /tmp/mc4-test-compile.log 2>&1 || { tail -40 /tmp/mc4-test-compile.log; exit 3; }

run_test() {
  local spec=$1
  timeout 20m mvn -B -o surefire:test -pl $MOD -Dtest="$spec" \
    -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false 2>&1 \
    | grep -E "Tests run:|BUILD|ERROR\]|FAIL" | grep -v "^\[INFO\] *$" | head -20
}

echo
echo "================ RUN 1: TestSpeculaMC4CachedDekAfterRestart ================"
run_test 'TestSpeculaMC4CachedDekAfterRestart'
OUT1=$REPORTS/org.apache.hadoop.hdfs.TestSpeculaMC4CachedDekAfterRestart-output.txt
echo "-- evidence (from $OUT1):"
grep -a "MC4-EVIDENCE" "$OUT1" | sed 's/^MC4-EVIDENCE /  /'
echo "-- one complete DN-side stack trace of the target throw:"
awk '/DataXceiver error processing/ && !done {p=1} p {print "  " $0; n++} p && /BlockTokenSecretManager.retrieveDataEncryptionKey/ {p=0; done=1}' "$OUT1" | head -40

echo
echo "================ RUN 2: in-tree TestEncryptedTransfer#testLongLivedReadClientAfterRestart (unmodified) ================"
run_test 'TestEncryptedTransfer#testLongLivedReadClientAfterRestart'
OUT2=$REPORTS/org.apache.hadoop.hdfs.TestEncryptedTransfer-output.txt
echo "-- target frames at the DN: $(grep -ac 'at org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager.retrieveDataEncryptionKey(BlockTokenSecretManager.java:' "$OUT2")"
grep -a -m2 "Caused by: org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException" "$OUT2" | sed 's/^/  /'
grep -a -m2 "at org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager.retrieveDataEncryptionKey" "$OUT2" | sed 's/^/  /'
grep -a -m4 "Will fetch a new encryption key" "$OUT2" | sed 's/^/  /'
echo "-- surefire summary:"
cat "$REPORTS/org.apache.hadoop.hdfs.TestEncryptedTransfer.txt" 2>/dev/null | sed 's/^/  /'
cat "$REPORTS/org.apache.hadoop.hdfs.TestSpeculaMC4CachedDekAfterRestart.txt" 2>/dev/null | sed 's/^/  /'
