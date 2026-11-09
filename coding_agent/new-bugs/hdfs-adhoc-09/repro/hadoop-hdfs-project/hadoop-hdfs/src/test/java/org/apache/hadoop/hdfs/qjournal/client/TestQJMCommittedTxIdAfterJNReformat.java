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
package org.apache.hadoop.hdfs.qjournal.client;

import static org.apache.hadoop.hdfs.qjournal.QJMTestUtil.FAKE_NSINFO;
import static org.apache.hadoop.hdfs.qjournal.QJMTestUtil.JID;
import static org.apache.hadoop.hdfs.qjournal.QJMTestUtil.writeSegment;
import static org.apache.hadoop.hdfs.qjournal.QJMTestUtil.writeTxns;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import java.io.Closeable;
import java.io.IOException;
import java.util.List;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.atomic.AtomicReference;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.CommonConfigurationKeysPublic;
import org.apache.hadoop.fs.FileUtil;
import org.apache.hadoop.hdfs.DFSConfigKeys;
import org.apache.hadoop.hdfs.qjournal.MiniJournalCluster;
import org.apache.hadoop.hdfs.server.namenode.EditLogInputStream;
import org.apache.hadoop.hdfs.server.namenode.EditLogOutputStream;
import org.apache.hadoop.hdfs.server.namenode.NameNodeLayoutVersion;
import org.apache.hadoop.io.IOUtils;
import org.apache.hadoop.ipc.RemoteException;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.thirdparty.com.google.common.util.concurrent.ListenableFuture;
import org.apache.hadoop.thirdparty.com.google.common.util.concurrent.SettableFuture;
import org.apache.hadoop.util.Lists;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.mockito.Mockito;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Reproduces a failure of the ad hoc check in Journal#checkRequest
 * ("Client trying to move committed txid backward") caused by a JournalNode
 * that lost its disk, was re-formatted by the JournalNodeSyncer
 * (dfs.journalnode.enable.sync.format) and immediately rejoined the quorum
 * although it no longer holds edits it had acknowledged.
 *
 * Setup is the same as TestQuorumJournalManager (3 JNs, QJM writers), with
 * the JN syncer + sync-format feature enabled.
 */
public class TestQJMCommittedTxIdAfterJNReformat {
  private static final Logger LOG = LoggerFactory.getLogger(
      TestQJMCommittedTxIdAfterJNReformat.class);

  private static final int JN_A = 0;
  private static final int JN_B = 1;
  private static final int JN_C = 2;

  private MiniJournalCluster cluster;
  private Configuration conf;
  private QuorumJournalManager qjm;
  private List<AsyncLogger> spies;
  private final List<QuorumJournalManager> toClose = Lists.newLinkedList();

  @BeforeEach
  public void setup() throws Exception {
    conf = new Configuration();
    conf.setInt(
        CommonConfigurationKeysPublic.IPC_CLIENT_CONNECT_MAX_RETRIES_KEY, 0);
    conf.setInt(
        CommonConfigurationKeysPublic.IPC_CLIENT_CONNECTION_MAXIDLETIME_KEY, 0);
    conf.setBoolean(DFSConfigKeys.DFS_HA_TAILEDITS_INPROGRESS_KEY, true);
    // JournalNode syncer with automatic formatting of a wiped JN.
    conf.setBoolean(DFSConfigKeys.DFS_JOURNALNODE_ENABLE_SYNC_KEY, true);
    conf.setBoolean(DFSConfigKeys.DFS_JOURNALNODE_ENABLE_SYNC_FORMAT_KEY, true);
    conf.setLong(DFSConfigKeys.DFS_JOURNALNODE_SYNC_INTERVAL_KEY, 1000L);

    cluster = new MiniJournalCluster.Builder(conf)
        .baseDir(GenericTestUtils.getRandomizedTestDir().getAbsolutePath())
        .build();
    cluster.waitActive();

    qjm = createSpyingQJM();
    spies = qjm.getLoggerSetForTests().getLoggersForTests();

    qjm.format(FAKE_NSINFO, false);
    qjm.recoverUnfinalizedSegments();
    assertEquals(1, qjm.getLoggerSetForTests().getEpoch());
  }

  @AfterEach
  public void shutdown() throws Exception {
    IOUtils.cleanupWithLogger(LOG, toClose.toArray(new Closeable[0]));
    if (cluster != null) {
      cluster.shutdown();
      cluster = null;
    }
  }

  private QuorumJournalManager createSpyingQJM() throws IOException {
    QuorumJournalManager q = SpyQJournalUtil.createSpyingQJM(
        conf, cluster.getQuorumJournalURI(JID), FAKE_NSINFO, null);
    toClose.add(q);
    return q;
  }

  @Test
  @Timeout(value = 120)
  public void testCommittedTxIdMovesBackwardAfterJNReformat()
      throws Exception {
    // ---- Writer 1 (active NN, epoch 1) ----
    // Segment 1-3 reaches all three JNs and is finalized.
    writeSegment(cluster, qjm, 1, 3, true);

    // JN A becomes slow: from now on writer 1's edit batches to A are
    // queued but never delivered (they are lost when writer 1 crashes).
    Mockito.doReturn(SettableFuture.create()).when(spies.get(JN_A))
        .sendEdits(Mockito.anyLong(), Mockito.anyLong(), Mockito.anyInt(),
            Mockito.any());

    // Writer 1 writes txns 4..10. Each batch is acked by the quorum {B, C}
    // and therefore committed; the next batch carries the committed txid,
    // so B and C persist committedTxId = 9.
    EditLogOutputStream stm1 = qjm.startLogSegment(4,
        NameNodeLayoutVersion.CURRENT_LAYOUT_VERSION);
    writeTxns(stm1, 4, 3);
    writeTxns(stm1, 7, 3);
    writeTxns(stm1, 10, 1);

    // Writer 1 (active NN) crashes.
    qjm.close();

    // JN C loses its disk: it is stopped, its storage is wiped and it is
    // restarted on a fresh disk. Its JournalNodeSyncer re-formats it
    // automatically with the namespace info of another JN.
    cluster.getJournalNode(JN_C).stopAndJoin(0);
    assertTrue(FileUtil.fullyDelete(cluster.getJournalDir(JN_C, JID)));
    cluster.setNamenodeSharedEditsConf(JID);
    cluster.restartJournalNode(JN_C);

    // ---- Writer 2 (new active NN) ----
    QuorumJournalManager qjm2 = createSpyingQJM();
    List<AsyncLogger> spies2 = qjm2.getLoggerSetForTests().getLoggersForTests();
    // Any RPC to C (e.g. the standby tailing edits) instantiates the
    // journal on C, which starts its syncer.
    try {
      qjm2.hasSomeData();
    } catch (IOException e) {
      LOG.info("hasSomeData while C is unformatted", e);
    }
    GenericTestUtils.waitFor(() -> {
      try {
        return cluster.getJournalNode(JN_C).getOrCreateJournal(JID)
            .isFormatted();
      } catch (IOException e) {
        return false;
      }
    }, 100, 30000);
    LOG.info("JN C has been re-formatted by its syncer");

    // JN B is restarting while writer 2 takes over, so writer 2's quorum is
    // {A, C}.
    cluster.getJournalNode(JN_B).stopAndJoin(0);

    qjm2.recoverUnfinalizedSegments();
    assertEquals(2, qjm2.getLoggerSetForTests().getEpoch());

    // Writer 2 reads the log (like a NN catching up before becoming
    // active): the quorum {A, C} only has txns 1-3.
    List<EditLogInputStream> streams = Lists.newArrayList();
    qjm2.selectInputStreams(streams, 1, false);
    long lastTxId = -1;
    for (EditLogInputStream s : streams) {
      lastTxId = Math.max(lastTxId, s.getLastTxId());
      IOUtils.closeStream(s);
    }
    LOG.info("Writer 2 sees last txid {}", lastTxId);
    assertEquals(3, lastTxId);

    // Writer 2 continues at txid 4 and commits 4..6 on {A, C}.
    EditLogOutputStream stm2 = qjm2.startLogSegment(lastTxId + 1,
        NameNodeLayoutVersion.CURRENT_LAYOUT_VERSION);
    writeTxns(stm2, 4, 2);
    writeTxns(stm2, 6, 1);

    // JN B comes back.
    cluster.restartJournalNode(JN_B);

    // Writer 2 rolls its log as usual: finalize 4-6 (B is still marked
    // out of sync by the client, so it is skipped) and start segment 7,
    // which is sent to every JN, including B.
    stm2.close();
    qjm2.finalizeLogSegment(4, 6);   // succeeds on the quorum {A, C}

    // Capture the per-JN result of B's startLogSegment RPC issued by the
    // normal QJM path.
    final AtomicReference<ListenableFuture<Void>> bStartSegment =
        new AtomicReference<>();
    Mockito.doAnswer(inv -> {
      @SuppressWarnings("unchecked")
      ListenableFuture<Void> f = (ListenableFuture<Void>) inv.callRealMethod();
      bStartSegment.set(f);
      return f;
    }).when(spies2.get(JN_B)).startLogSegment(
        Mockito.anyLong(), Mockito.anyInt());

    EditLogOutputStream stm3 = qjm2.startLogSegment(7,
        NameNodeLayoutVersion.CURRENT_LAYOUT_VERSION);  // quorum {A, C}
    IOUtils.closeStream(stm3);

    try {
      bStartSegment.get().get();
      fail("Expected JN B to reject writer 2's request");
    } catch (ExecutionException ee) {
      Throwable cause = ee.getCause();
      LOG.error("JN B rejected writer 2's startLogSegment", cause);
      if (cause instanceof RemoteException) {
        assertEquals(IllegalArgumentException.class.getName(),
            ((RemoteException) cause).getClassName());
      }
      // Surface the server-side IllegalArgumentException (with the JN
      // stack trace) as the test failure.
      throw new AssertionError(
          "Journal.checkRequest rejected committed txid of the new writer "
              + "(edits 4-10 committed by writer 1 were lost)", cause);
    }
  }
}
