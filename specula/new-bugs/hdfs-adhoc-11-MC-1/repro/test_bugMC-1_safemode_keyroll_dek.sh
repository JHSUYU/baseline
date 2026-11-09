#!/usr/bin/env bash
# MC-1 reproduction: safe mode suppresses block-key pushes while the NameNode
# keeps rolling block keys and issuing DataEncryptionKeys (DEKs).
#
# Target check (hdfs-adhoc-11):
#   BlockTokenSecretManager.retrieveDataEncryptionKey(int, byte[])
#   BlockTokenSecretManager.java:559 throws InvalidEncryptionKeyException
#   when key == null (key = allKeys.get(keyId)) on the DataNode.
#
# The JUnit class written below is a variant of the workload test
# TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[1]
# (resolverClazz == null). Its setup code is copied from the workload; it adds
# only the counterexample's fault (manual safe mode on the active NN, through
# the public DistributedFileSystem.setSafeMode API) and time compression of the
# key-update interval. It never writes the guard's operands (no
# clearAllKeysForTesting, no addKeys on the DN, no setTokenLifetime) and never
# edits the target method. Internal state is only read, to print evidence.
#
#   testControlNoSafeModeKeysPushed          negative control (no safe mode)
#   testSafeModeTwoRollsFreshDekRejected     Level 1: setKeyUpdateIntervalForTesting(2 s),
#                                            the same hook TestEncryptedTransfer uses
#   testSafeModeTwoRollsLevel0ConfigOnly     Level 0: public config only,
#                                            dfs.block.access.key.update.interval = 1 (minute)
#
# Usage: test_bugMC-1_safemode_keyroll_dek.sh [pristine hadoop checkout at 734dd8a67cd]
set -euo pipefail

SRC=${1:-/users/ZhenyuLi/Specula/runs/20261029-002846-8337/hdfs-adhoc-11/.specula-output/confirmation/MC-1/worktree}
ENV_SH=${ENV_SH:-/bulk/specula-adhoc/v2/hdfs/cases/hdfs-adhoc-11/env.sh}
BASE_COMMIT=734dd8a67cd
OUT_DIR=$(cd "$(dirname "$0")" && pwd)
LOG=${OUT_DIR}/test_bugMC-1_safemode_keyroll_dek.log
CLASS=SpeculaAdhocMC1SafeModeKeyRollTest
MODULE=hadoop-hdfs-project/hadoop-hdfs

die() { echo "ERROR: $*" >&2; exit 2; }

# 1. The checkout must be the pinned commit with no edits to tracked sources.
head=$(git -C "$SRC" rev-parse HEAD)
[[ $head == ${BASE_COMMIT}* ]] || die "$SRC is at $head, not $BASE_COMMIT"
git -C "$SRC" diff --quiet HEAD -- hadoop-hdfs-project hadoop-common-project \
  || die "$SRC has modified tracked sources; reproduction needs pristine code"
for f in SpeculaTrace.java security/token/block/SpeculaKeys.java; do
  [[ ! -e $SRC/$MODULE/src/main/java/org/apache/hadoop/hdfs/$f ]] \
    || die "instrumentation file $f present in $SRC; remove it first"
done

# 2. Write the workload variant into the workload's module and package.
TEST_FILE=$SRC/$MODULE/src/test/java/org/apache/hadoop/hdfs/$CLASS.java
cat > "$TEST_FILE" <<'JAVA'
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

import java.io.IOException;
import java.io.OutputStream;
import java.util.concurrent.TimeUnit;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.FileSystem;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.fs.SafeModeAction;
import org.apache.hadoop.hdfs.client.HdfsClientConfigKeys;
import org.apache.hadoop.hdfs.security.token.block.BlockKey;
import org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager;
import org.apache.hadoop.hdfs.security.token.block.DataEncryptionKey;
import org.apache.hadoop.hdfs.server.blockmanagement.DatanodeDescriptor;
import org.apache.hadoop.hdfs.server.common.HdfsServerConstants.StartupOption;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.hdfs.server.datanode.DataNodeTestUtils;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * MC-1: variant of TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[1].
 * Counterexample G_S1_synced: DN synced -> EnterSafeMode -> RollKeys -> Sweep ->
 * RollKeys -> ClientGetDek -> ClientConnect (target fires).
 */
public class SpeculaAdhocMC1SafeModeKeyRollTest {
  private static final Logger LOG =
      LoggerFactory.getLogger(SpeculaAdhocMC1SafeModeKeyRollTest.class);

  private static final String PLAIN_TEXT = "this is very secret plain text";
  private static final Path TEST_PATH = new Path("/non-encrypted-file");
  private static final String TARGET_EXCEPTION =
      "org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException";
  // The target throw statement spans BlockTokenSecretManager.java:559-561. In the
  // compiled class (javap LineNumberTable, printed by the driver) the
  // "new InvalidEncryptionKeyException" maps to line 559 and the constructor call
  // (where the stack trace is filled in) and athrow map to line 561, so the JVM
  // reports this single throw statement as line 561.
  private static final String TARGET_FRAME =
      "org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager"
      + ".retrieveDataEncryptionKey(BlockTokenSecretManager.java:561)";
  private static final String TARGET_MESSAGE =
      "Can't re-compute encryption key for nonce, since the required block key (keyID=";

  private MiniDFSCluster cluster = null;
  private Configuration conf = null;
  private FileSystem fs = null;

  private static void ev(String msg) {
    System.out.println("MC1-EVIDENCE " + msg);
    LOG.info("MC1-EVIDENCE " + msg);
  }

  // ---- setup copied from TestEncryptedTransfer (resolverClazz == null) ----

  private void setEncryptionConfigKeys() {
    conf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, true);
    conf.setBoolean(DFSConfigKeys.DFS_BLOCK_ACCESS_TOKEN_ENABLE_KEY, true);
  }

  private static FileSystem getFileSystem(Configuration conf) throws IOException {
    Configuration localConf = new Configuration(conf);
    localConf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, false);
    localConf.unset(DFSConfigKeys.DFS_DATA_ENCRYPTION_ALGORITHM_KEY);
    return FileSystem.get(localConf);
  }

  /** Same client configuration as getFileSystem, but a new DFSClient with no cached DEK. */
  private static FileSystem newFreshClient(Configuration conf) throws IOException {
    Configuration localConf = new Configuration(conf);
    localConf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, false);
    localConf.unset(DFSConfigKeys.DFS_DATA_ENCRYPTION_ALGORITHM_KEY);
    return FileSystem.newInstance(localConf);
  }

  private static void writeTestDataToFile(FileSystem fs) throws IOException {
    OutputStream out = null;
    if (!fs.exists(TEST_PATH)) {
      out = fs.create(TEST_PATH);
    } else {
      out = fs.append(TEST_PATH);
    }
    out.write(PLAIN_TEXT.getBytes());
    out.close();
  }

  /** writeUnencryptedAndThenRestartEncryptedCluster from the workload. */
  private void writeUnencryptedAndThenRestartEncryptedCluster(long keyUpdateMinutes)
      throws IOException {
    conf = new Configuration();
    // testEncryptedRead("", "", false, false): default algorithm and cipher suite
    conf.set(DFSConfigKeys.DFS_DATA_ENCRYPTION_ALGORITHM_KEY, "");
    conf.set(HdfsClientConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_CIPHER_SUITES_KEY, "");

    cluster = new MiniDFSCluster.Builder(conf).build();
    fs = getFileSystem(conf);
    writeTestDataToFile(fs);
    assertEquals(PLAIN_TEXT, DFSTestUtil.readFile(fs, TEST_PATH));
    fs.close();
    cluster.shutdown();

    setEncryptionConfigKeys();
    if (keyUpdateMinutes > 0) {
      // Level 0 only: public configuration key, in minutes (default 600).
      conf.setLong(DFSConfigKeys.DFS_BLOCK_ACCESS_KEY_UPDATE_INTERVAL_KEY, keyUpdateMinutes);
    }
    cluster = new MiniDFSCluster.Builder(conf)
        .manageDataDfsDirs(false)
        .manageNameDfsDirs(false)
        .format(false)
        .startupOption(StartupOption.REGULAR)
        .build();
    fs = getFileSystem(conf);
  }

  @AfterEach
  public void teardown() throws IOException {
    if (fs != null) {
      fs.close();
    }
    if (cluster != null) {
      cluster.shutdown();
    }
  }

  // ---- read-only observation helpers ----

  private BlockTokenSecretManager nnBtsm() {
    return cluster.getNamesystem().getBlockManager().getBlockTokenSecretManager();
  }

  private BlockTokenSecretManager dnBtsm(DataNode dn) throws IOException {
    return dn.getBlockPoolTokenSecretManager().get(cluster.getNamesystem().getBlockPoolId());
  }

  private DatanodeDescriptor descriptor(DataNode dn) throws IOException {
    return cluster.getNamesystem().getBlockManager().getDatanodeManager()
        .getDatanode(dn.getDatanodeId());
  }

  private boolean dnHasAllNnKeys(DataNode dn) throws IOException {
    for (BlockKey k : nnBtsm().exportKeys().getAllKeys()) {
      if (!dnBtsm(dn).hasKey(k.getKeyId())) {
        return false;
      }
    }
    return true;
  }

  private String keyState(String label, DataNode dn) throws IOException {
    int nnCur = nnBtsm().getCurrentKey().getKeyId();
    StringBuilder nnAll = new StringBuilder();
    for (BlockKey k : nnBtsm().exportKeys().getAllKeys()) {
      nnAll.append(k.getKeyId()).append(dnBtsm(dn).hasKey(k.getKeyId()) ? "(DN:yes) " : "(DN:NO) ");
    }
    return label + ": nnSafeMode=" + cluster.getNamesystem().isInSafeMode()
        + " nnSerialNo=" + nnBtsm().getSerialNoForTesting()
        + " nnCurrentKey=" + nnCur
        + " dnCurrentKey=" + dnBtsm(dn).getCurrentKey().getKeyId()
        + " dnHasNnCurrentKey=" + dnBtsm(dn).hasKey(nnCur)
        + " nnNeedKeyUpdate[dn]=" + descriptor(dn).needKeyUpdate()
        + " nnKeys=[" + nnAll.toString().trim() + "]";
  }

  /** CE states 1-5: encrypted cluster up, startup safe mode off, DN holds every NN key. */
  private DataNode bringUpSyncedCluster(long keyUpdateMinutes) throws Exception {
    writeUnencryptedAndThenRestartEncryptedCluster(keyUpdateMinutes);
    // The workload's own step: an encrypted read succeeds.
    assertEquals(PLAIN_TEXT, DFSTestUtil.readFile(fs, TEST_PATH));
    final DataNode dn = cluster.getDataNodes().get(0);
    GenericTestUtils.waitFor(() -> {
      try {
        return !cluster.getNamesystem().isInSafeMode() && !descriptor(dn).needKeyUpdate()
            && dnHasAllNnKeys(dn);
      } catch (IOException e) {
        return false;
      }
    }, 100, 60 * 1000);
    ev(keyState("synced (CE state 5)", dn));
    return dn;
  }

  /** CE state 6: manual safe mode on the active NN, via the public admin API. */
  private void enterManualSafeMode(DataNode dn) throws IOException {
    DistributedFileSystem dfs = (DistributedFileSystem) fs;
    assertTrue(dfs.setSafeMode(SafeModeAction.ENTER));
    assertTrue(cluster.getNamesystem().isInSafeMode());
    ev(keyState("entered manual safe mode (CE state 6)", dn));
  }

  private void waitForRolls(final int serialBase, final int rolls, int timeoutMs)
      throws Exception {
    GenericTestUtils.waitFor(() -> nnBtsm().getSerialNoForTesting() >= serialBase + rolls,
        50, timeoutMs);
  }

  /** Outcome of one fresh-client read. */
  private static final class ReadResult {
    private IOException err;
    private DataEncryptionKey dek;
  }

  /** CE states 10-11: fresh client fetches a DEK and connects to the DN. */
  private ReadResult freshClientRead(String label, DataNode dn) throws Exception {
    // Let pooled connections expire (client socket cache 3 s, DN keepalive 4 s), so the
    // read opens a new connection and runs the SASL handshake with a fresh DEK.
    Thread.sleep(5000);
    int nnCurAtRead = nnBtsm().getCurrentKey().getKeyId();
    FileSystem fresh = newFreshClient(conf);
    ReadResult r = new ReadResult();
    long t0 = System.currentTimeMillis();
    try {
      String data = DFSTestUtil.readFile(fresh, TEST_PATH);
      ev(label + ": fresh-client read RETURNED " + data.length() + " chars, equal="
          + PLAIN_TEXT.equals(data));
    } catch (IOException e) {
      r.err = e;
      ev(label + ": fresh-client read FAILED after " + (System.currentTimeMillis() - t0)
          + " ms with " + e.getClass().getName() + ": " + e.getMessage());
    }
    r.dek = DFSClientAdapter.getDFSClient((DistributedFileSystem) fresh).getEncryptionKey();
    ev(label + ": fresh client's DEK keyId=" + (r.dek == null ? "null" : r.dek.keyId)
        + " (NN currentKey when read started=" + nnCurAtRead + ") dnHasDekKey="
        + (r.dek == null ? "n/a" : dnBtsm(dn).hasKey(r.dek.keyId)));
    fresh.close();
    return r;
  }

  /** A successful read that really used a fresh DEK the DN knows. */
  private void assertFreshDekReadOk(ReadResult r, DataNode dn, String what) throws IOException {
    assertEquals(null, r.err, what + ": read must succeed");
    assertNotNull(r.dek, what + ": read must have used a fresh DEK (SASL handshake)");
    assertTrue(dnBtsm(dn).hasKey(r.dek.keyId), what + ": DN must hold the DEK's key");
  }

  /** A failed read whose DN-side failure is the target throw, for this client's DEK. */
  private void assertTargetFired(ReadResult r, String dnOut, String what) {
    assertNotNull(r.err, what + ": fresh-DEK read must fail");
    assertNotNull(r.dek, what + ": client must hold a DEK from the NN");
    assertTrue(count(dnOut, TARGET_FRAME) > 0,
        what + ": target must throw at BlockTokenSecretManager.retrieveDataEncryptionKey");
    assertTrue(dnOut.contains("Caused by: " + TARGET_EXCEPTION + ": " + TARGET_MESSAGE
        + r.dek.keyId + ") doesn't exist"), what + ": target message names the DEK's key");
  }

  private static void printTargetEvidence(String label, String dnLog) {
    String[] lines = dnLog.split("\n");
    int shown = 0;
    for (int i = 0; i < lines.length && shown < 3; i++) {
      if (lines[i].contains("DataXceiver error processing")) {
        ev(label + " DN LOG: " + lines[i].trim());
        for (int j = i + 1; j < lines.length && j < i + 60; j++) {
          String l = lines[j].trim();
          if (l.startsWith("javax.security.sasl.SaslException")
              || l.startsWith("Caused by: " + TARGET_EXCEPTION)
              || l.contains("BlockTokenSecretManager.retrieveDataEncryptionKey")
              || l.contains("BlockPoolTokenSecretManager.retrieveDataEncryptionKey")
              || l.contains("SaslDataTransferServer.getEncryptionKeyFromUserName")
              || l.contains("SaslDataTransferServer.doSaslHandshake")
              || l.contains("SaslDataTransferServer.receive")
              || l.contains("DataXceiver.run")) {
            ev(label + " DN LOG:     " + l);
          }
          if (lines[j].contains("DataXceiver error processing")) {
            break;
          }
        }
        shown++;
      }
    }
  }

  private static int count(String haystack, String needle) {
    int n = 0;
    for (int i = haystack.indexOf(needle); i >= 0; i = haystack.indexOf(needle, i + 1)) {
      n++;
    }
    return n;
  }

  // ---------------------------------------------------------------------------

  private boolean dnHasNnCurrentKey(DataNode dn) {
    try {
      return dnBtsm(dn).hasKey(nnBtsm().getCurrentKey().getKeyId());
    } catch (IOException e) {
      return false;
    }
  }

  /** Negative control: same key rolls, no safe mode. Heartbeats push the keys; reads work. */
  @Test
  @Timeout(value = 300, unit = TimeUnit.SECONDS)
  public void testControlNoSafeModeKeysPushed() throws Exception {
    DataNode dn = bringUpSyncedCluster(0);
    int s0 = nnBtsm().getSerialNoForTesting();
    nnBtsm().setKeyUpdateIntervalForTesting(2 * 1000);
    waitForRolls(s0, 2, 60 * 1000);
    ev(keyState("control: two rolls done, no safe mode", dn));
    GenericTestUtils.waitFor(() -> dnHasNnCurrentKey(dn), 50, 30 * 1000);
    ev(keyState("control: DN holds the NN current key (pushed by heartbeat)", dn));
    LogCapturer dnLogs = LogCapturer.captureLogs(DataNode.LOG);
    ReadResult r;
    try {
      r = freshClientRead("control", dn);
    } finally {
      dnLogs.stopCapturing();
    }
    int hits = count(dnLogs.getOutput(), TARGET_FRAME);
    ev("control: target frame occurrences in DN log = " + hits);
    assertFreshDekReadOk(r, dn, "control");
    assertEquals(0, hits);
    ev("control RESULT: no safe mode -> keys pushed by heartbeat -> fresh-DEK read OK");
  }

  /** Counterexample G_S1_synced, Level 1 (time compression with the test hook). */
  @Test
  @Timeout(value = 300, unit = TimeUnit.SECONDS)
  public void testSafeModeTwoRollsFreshDekRejected() throws Exception {
    DataNode dn = bringUpSyncedCluster(0);
    enterManualSafeMode(dn);

    // In safe mode, before any roll: a fresh client still reads (safe mode allows reads).
    ReadResult pre = freshClientRead("L1 safe mode, 0 rolls", dn);
    assertFreshDekReadOk(pre, dn, "safe mode, 0 rolls");

    // CE states 7-9: HeartbeatManager.Monitor rolls keys twice; the 600-minute
    // interval is compressed with the hook TestEncryptedTransfer#testLongLivedClient uses.
    int s0 = nnBtsm().getSerialNoForTesting();
    nnBtsm().setKeyUpdateIntervalForTesting(2 * 1000);
    waitForRolls(s0, 1, 60 * 1000);
    ev(keyState("L1 after roll 1 (CE state 7/8)", dn));
    waitForRolls(s0, 2, 60 * 1000);
    ev(keyState("L1 after roll 2 (CE state 9)", dn));

    // The DN keeps heartbeating; safe mode returns no commands, so no KeyUpdateCommand.
    DatanodeDescriptor dd = descriptor(dn);
    long hb0 = dd.getLastUpdateMonotonic();
    DataNodeTestUtils.triggerHeartbeat(dn);
    DataNodeTestUtils.triggerHeartbeat(dn);
    ev("L1 heartbeats processed by NN during safe mode: lastUpdateMonotonic advanced by "
        + (dd.getLastUpdateMonotonic() - hb0) + " ms");
    ev(keyState("L1 after 2 more heartbeats", dn));
    assertTrue(dd.getLastUpdateMonotonic() > hb0, "NN must have processed a heartbeat");
    assertFalse(dnHasNnCurrentKey(dn));
    assertTrue(dd.needKeyUpdate(), "key push still pending");

    // CE states 10-11: fresh client -> getDataEncryptionKey -> connect to DN.
    LogCapturer dnLogs = LogCapturer.captureLogs(DataNode.LOG);
    LogCapturer clientLogs = LogCapturer.captureLogs(DFSClient.LOG);
    ReadResult r;
    try {
      r = freshClientRead("L1 safe mode, 2 rolls", dn);
    } finally {
      dnLogs.stopCapturing();
      clientLogs.stopCapturing();
    }
    String dnOut = dnLogs.getOutput();
    printTargetEvidence("L1", dnOut);
    int refetch = count(clientLogs.getOutput(), "Will fetch a new encryption key and retry");
    ev("L1 target frame occurrences in DN log = " + count(dnOut, TARGET_FRAME)
        + "; client DEK refetches logged = " + refetch);
    assertTargetFired(r, dnOut, "L1");
    assertTrue(refetch > 0, "client must have tried its single DEK refetch");

    // Persistence: still in safe mode, more heartbeats, another fresh client fails too.
    DataNodeTestUtils.triggerHeartbeat(dn);
    ev(keyState("L1 persistence check", dn));
    LogCapturer dnLogs2 = LogCapturer.captureLogs(DataNode.LOG);
    ReadResult r2;
    try {
      r2 = freshClientRead("L1 safe mode, later fresh client", dn);
    } finally {
      dnLogs2.stopCapturing();
    }
    ev("L1 persistence: target frame occurrences = "
        + count(dnLogs2.getOutput(), TARGET_FRAME));
    assertTargetFired(r2, dnLogs2.getOutput(), "L1 persistence");

    // Leaving safe mode: the next heartbeat carries the KeyUpdateCommand.
    assertFalse(((DistributedFileSystem) fs).setSafeMode(SafeModeAction.LEAVE));
    DataNodeTestUtils.triggerHeartbeat(dn);
    GenericTestUtils.waitFor(() -> dnHasNnCurrentKey(dn), 50, 30 * 1000);
    ev(keyState("L1 after leaving safe mode + heartbeat", dn));
    ReadResult r3 = freshClientRead("L1 after safe mode exit", dn);
    assertFreshDekReadOk(r3, dn, "after safe mode exit");
    ev("L1 RESULT: target fired in safe mode after two rolls; fresh-DEK reads failed until "
        + "safe mode was left");
  }

  /** Counterexample G_S1_synced, Level 0: public config only (1-minute key interval). */
  @Test
  @Timeout(value = 600, unit = TimeUnit.SECONDS)
  public void testSafeModeTwoRollsLevel0ConfigOnly() throws Exception {
    DataNode dn = bringUpSyncedCluster(1);
    enterManualSafeMode(dn);
    int s0 = nnBtsm().getSerialNoForTesting();
    long t0 = System.currentTimeMillis();
    // No hook: HeartbeatManager.Monitor rolls every ~65 s with a 1-minute interval.
    GenericTestUtils.waitFor(() -> !dnHasNnCurrentKey(dn), 200, 300 * 1000);
    ev(keyState("L0 NN current key unknown to DN after "
        + (System.currentTimeMillis() - t0) / 1000 + " s in safe mode, rolls="
        + (nnBtsm().getSerialNoForTesting() - s0), dn));

    LogCapturer dnLogs = LogCapturer.captureLogs(DataNode.LOG);
    ReadResult r;
    try {
      r = freshClientRead("L0 safe mode", dn);
    } finally {
      dnLogs.stopCapturing();
    }
    printTargetEvidence("L0", dnLogs.getOutput());
    ev("L0 target frame occurrences in DN log = " + count(dnLogs.getOutput(), TARGET_FRAME));
    assertTargetFired(r, dnLogs.getOutput(), "L0");
    ev("L0 RESULT: target fired with public APIs and configuration only");
  }
}
JAVA
echo "wrote $TEST_FILE"

# 3. Compile the module's tests and run the variant (offline, pinned JDK and repo).
# shellcheck disable=SC1090
source "$ENV_SH"
cd "$SRC"
{
  echo "=== MC-1 repro: $(date -Is) source=$SRC commit=$head"
  echo "=== java: $(java -version 2>&1 | head -1)"
  echo "=== mvn test-compile"
  timeout 40m mvn -B -o test-compile -pl "$MODULE" -Dmaven.javadoc.skip=true 2>&1 \
    | grep -E "BUILD|ERROR|Compiling|Total time" || true
  echo "=== compiled main classes containing instrumentation: $(find "$SRC/$MODULE/target/classes" -name 'Specula*' | wc -l)"
  echo "=== target throw statement (source, pristine $BASE_COMMIT)"
  awk 'NR>=553 && NR<=565 {printf "%d: %s\n", NR, $0}' \
    "$SRC/$MODULE/src/main/java/org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager.java"
  echo "=== javap: bytecode + LineNumberTable of the target method (compiled class)"
  javap -c -l -p -cp "$SRC/$MODULE/target/classes" \
      org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager \
    | awk '/public byte\[\] retrieveDataEncryptionKey\(int, byte\[\]\)/,/LocalVariableTable/' \
    | grep -E "retrieveDataEncryptionKey|ifnonnull|InvalidEncryptionKeyException|athrow|line 55[5-9]|line 56[0-4]" || true
  echo "=== mvn surefire:test -Dtest=$CLASS"
  set +e
  timeout 30m mvn -B -o surefire:test -pl "$MODULE" -Dtest="$CLASS" \
    -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false > "$LOG.mvn" 2>&1
  rc=$?
  set -e
  grep -E "Tests run|BUILD|FAIL|ERROR\]|Running org" "$LOG.mvn" || true
  echo "=== surefire exit code: $rc"
  REPORT=$SRC/$MODULE/target/surefire-reports/org.apache.hadoop.hdfs.$CLASS-output.txt
  cp "$REPORT" "$OUT_DIR/test_bugMC-1_safemode_keyroll_dek.output.txt" 2>/dev/null || true
  echo "=== evidence lines (test stdout, $REPORT)"
  grep -h "^MC1-EVIDENCE" "$REPORT" || true
  echo "=== per-test results"
  grep -h -E "Tests run:|testControl|testSafeMode" \
    "$SRC/$MODULE/target/surefire-reports/org.apache.hadoop.hdfs.$CLASS.txt" || true
} 2>&1 | tee "$LOG"
echo "log: $LOG  (full test output: $OUT_DIR/test_bugMC-1_safemode_keyroll_dek.output.txt)"
