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
import static org.apache.hadoop.hdfs.qjournal.QJMTestUtil.writeTxns;
import static org.junit.jupiter.api.Assertions.fail;

import java.io.Closeable;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URL;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.CommonConfigurationKeysPublic;
import org.apache.hadoop.hdfs.DFSConfigKeys;
import org.apache.hadoop.hdfs.qjournal.MiniJournalCluster;
import org.apache.hadoop.hdfs.qjournal.protocol.QJournalProtocol;
import org.apache.hadoop.hdfs.qjournal.protocol.QJournalProtocolProtos.SegmentStateProto;
import org.apache.hadoop.hdfs.qjournal.protocol.RequestInfo;
import org.apache.hadoop.hdfs.server.namenode.EditLogOutputStream;
import org.apache.hadoop.hdfs.server.namenode.NameNodeLayoutVersion;
import org.apache.hadoop.hdfs.server.protocol.NamespaceInfo;
import org.apache.hadoop.io.IOUtils;
import org.apache.hadoop.test.GenericTestUtils;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.mockito.AdditionalAnswers;
import org.mockito.Mockito;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * A slow JournalNode receives a delayed acceptRecovery() whose RequestInfo
 * carries a committed txid that belongs to the *next* segment written by the
 * new writer. The JN's paranoid check in Journal.acceptRecovery() wrongly
 * interprets that txid as a committed txn of the segment being recovered and
 * throws an AssertionError.
 */
public class TestQJMSlowJournalAcceptRecovery {
  private static final Logger LOG =
      LoggerFactory.getLogger(TestQJMSlowJournalAcceptRecovery.class);

  private MiniJournalCluster cluster;
  private Configuration conf;
  private final List<Closeable> toClose = new ArrayList<>();

  @BeforeEach
  public void setup() throws Exception {
    conf = new Configuration();
    conf.setInt(
        CommonConfigurationKeysPublic.IPC_CLIENT_CONNECT_MAX_RETRIES_KEY, 0);
    conf.setInt(
        CommonConfigurationKeysPublic.IPC_CLIENT_CONNECTION_MAXIDLETIME_KEY, 0);
    conf.setBoolean(DFSConfigKeys.DFS_HA_TAILEDITS_INPROGRESS_KEY, true);
    cluster = new MiniJournalCluster.Builder(conf)
        .baseDir(GenericTestUtils.getRandomizedTestDir().getAbsolutePath())
        .build();
    cluster.waitActive();
  }

  @AfterEach
  public void shutdown() throws Exception {
    IOUtils.cleanupWithLogger(LOG, toClose.toArray(new Closeable[0]));
    if (cluster != null) {
      cluster.shutdown();
      cluster = null;
    }
  }

  @Test
  @Timeout(value = 120)
  public void testSlowJNAcceptRecoveryAfterNewSegmentCommitted()
      throws Exception {
    // ---- Writer 1 (epoch 1): JN0: 1-3, JN1: 1-4, JN2: 1-5 (in progress).
    QuorumJournalManager qjm1 = SpyQJournalUtil.createSpyingQJM(
        conf, cluster.getQuorumJournalURI(JID), FAKE_NSINFO, null);
    toClose.add(qjm1);
    List<AsyncLogger> spies1 = qjm1.getLoggerSetForTests().getLoggersForTests();
    qjm1.format(FAKE_NSINFO, false);
    qjm1.recoverUnfinalizedSegments();

    EditLogOutputStream stm = qjm1.startLogSegment(1,
        NameNodeLayoutVersion.CURRENT_LAYOUT_VERSION);
    failLoggerAtTxn(spies1.get(0), 4);
    failLoggerAtTxn(spies1.get(1), 5);
    writeTxns(stm, 1, 3);
    writeTxns(stm, 4, 1);   // committed on JN1, JN2
    try {
      writeTxns(stm, 5, 1); // only on JN2: not committed
      fail("expected quorum failure");
    } catch (QuorumException qe) {
      GenericTestUtils.assertExceptionContains("too many exceptions", qe);
    }
    // Writer 1 crashes.

    // ---- Writer 2 (epoch 2, e.g. the NN that fails over). JN2 is slow:
    // its prepareRecovery() RPC is delayed (GC pause / slow network).
    final int slowPort = cluster.getJournalNode(2).getBoundIpcAddress()
        .getPort();
    final CountDownLatch releaseSlowJN = new CountDownLatch(1);
    final AtomicReference<Throwable> slowAcceptFailure =
        new AtomicReference<>();
    final CountDownLatch slowAcceptDone = new CountDownLatch(1);

    AsyncLogger.Factory factory = new AsyncLogger.Factory() {
      @Override
      public AsyncLogger createLogger(Configuration c, NamespaceInfo nsInfo,
          String journalId, String nameServiceId, InetSocketAddress addr) {
        final boolean slow = addr.getPort() == slowPort;
        return new IPCLoggerChannel(c, nsInfo, journalId, nameServiceId,
            addr) {
          @Override
          protected QJournalProtocol createProxy() throws IOException {
            QJournalProtocol real = super.createProxy();
            if (!slow) {
              return real;
            }
            QJournalProtocol p = Mockito.mock(QJournalProtocol.class,
                AdditionalAnswers.delegatesTo(real));
            Mockito.doAnswer(inv -> {
              LOG.info("Delaying prepareRecovery to slow JN");
              releaseSlowJN.await(60, TimeUnit.SECONDS);
              return real.prepareRecovery(inv.getArgument(0),
                  inv.getArgument(1));
            }).when(p).prepareRecovery(Mockito.any(RequestInfo.class),
                Mockito.anyLong());
            Mockito.doAnswer(inv -> {
              try {
                real.acceptRecovery(inv.getArgument(0), inv.getArgument(1),
                    inv.getArgument(2));
                return null;
              } catch (Throwable t) {
                slowAcceptFailure.set(t);
                throw t;
              } finally {
                slowAcceptDone.countDown();
              }
            }).when(p).acceptRecovery(Mockito.any(RequestInfo.class),
                Mockito.any(SegmentStateProto.class), Mockito.any(URL.class));
            return p;
          }
        };
      }
    };
    QuorumJournalManager qjm2 = new QuorumJournalManager(conf,
        cluster.getQuorumJournalURI(JID), FAKE_NSINFO, null, factory);
    toClose.add(qjm2);

    // Recovery completes with JN0+JN1: segment 1 is recovered/finalized to
    // 1-4 (txn 5 was never committed, so dropping it is correct).
    qjm2.recoverUnfinalizedSegments();

    // The new writer starts the next segment at txid 5 and commits txn 5
    // (the START_LOG_SEGMENT op is synced alone) on JN0+JN1.
    EditLogOutputStream stm2 = qjm2.startLogSegment(5,
        NameNodeLayoutVersion.CURRENT_LAYOUT_VERSION);
    writeTxns(stm2, 5, 1);

    // The slow JN wakes up and processes its queued prepareRecovery and
    // acceptRecovery(1-4). The requests are stamped with committedTxId=5
    // (of segment 5) at execution time.
    releaseSlowJN.countDown();
    if (!slowAcceptDone.await(60, TimeUnit.SECONDS)) {
      fail("acceptRecovery to slow JN never ran");
    }
    Throwable t = slowAcceptFailure.get();
    if (t != null) {
      LOG.error("acceptRecovery on slow JN failed", t);
      throw new AssertionError(
          "acceptRecovery(1-4) on JN2 failed: " + t.getMessage(), t);
    }
    stm2.close();
  }

  private static void failLoggerAtTxn(AsyncLogger spy, long txid) {
    TestQuorumJournalManagerUnit.futureThrows(new IOException("mock failure"))
        .when(spy).sendEdits(Mockito.anyLong(),
        Mockito.eq(txid), Mockito.eq(1), Mockito.<byte[]>any());
  }
}
