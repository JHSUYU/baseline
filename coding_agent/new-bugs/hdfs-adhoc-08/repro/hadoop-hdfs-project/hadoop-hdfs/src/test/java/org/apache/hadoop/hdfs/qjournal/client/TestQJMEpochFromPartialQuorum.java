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
import static org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManagerUnit.futureThrows;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.fail;

import java.io.Closeable;
import java.io.IOException;
import java.util.List;
import java.util.concurrent.CountDownLatch;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.CommonConfigurationKeysPublic;
import org.apache.hadoop.hdfs.qjournal.MiniJournalCluster;
import org.apache.hadoop.hdfs.qjournal.QJMTestUtil;
import org.apache.hadoop.hdfs.qjournal.protocol.QJournalProtocolProtos.GetJournalStateResponseProto;
import org.apache.hadoop.hdfs.server.namenode.EditLogOutputStream;
import org.apache.hadoop.hdfs.server.namenode.NameNodeLayoutVersion;
import org.apache.hadoop.io.IOUtils;
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
 * A writer chooses its epoch as 1 + the max lastPromisedEpoch reported by
 * the first majority of JNs that answer getJournalState(). If a JN that holds
 * a higher promise (left over from earlier failed newEpoch attempts) is
 * merely slow, the new - and only - writer gets an epoch lower than that
 * JN's promise. The JN then rejects every request of the legitimate writer
 * in Journal.checkRequest() ("IPC's epoch X is less than the last promised
 * epoch Y"), for the whole lifetime of that writer, silently reducing the
 * fault tolerance of the journal quorum from 1 failure to 0.
 */
public class TestQJMEpochFromPartialQuorum {
  private static final Logger LOG =
      LoggerFactory.getLogger(TestQJMEpochFromPartialQuorum.class);

  private MiniJournalCluster cluster;
  private Configuration conf;
  private final List<Closeable> toClose = Lists.newLinkedList();

  @BeforeEach
  public void setup() throws Exception {
    conf = new Configuration();
    conf.setInt(
        CommonConfigurationKeysPublic.IPC_CLIENT_CONNECT_MAX_RETRIES_KEY, 0);
    conf.setInt(
        CommonConfigurationKeysPublic.IPC_CLIENT_CONNECTION_MAXIDLETIME_KEY, 0);
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

  private QuorumJournalManager newQJM() throws IOException {
    QuorumJournalManager q = SpyQJournalUtil.createSpyingQJM(
        conf, cluster.getQuorumJournalURI(JID), FAKE_NSINFO, null);
    toClose.add(q);
    return q;
  }

  private static List<AsyncLogger> spies(QuorumJournalManager q) {
    return q.getLoggerSetForTests().getLoggersForTests();
  }

  @Test
  @Timeout(value = 120)
  public void testSlowJNWithHigherPromiseRejectsOnlyWriter() throws Exception {
    // Writer W1 (epoch 1 on all three JNs) writes a finalized segment and
    // then goes away (NN crash / failover).
    QuorumJournalManager w1 = newQJM();
    w1.format(QJMTestUtil.FAKE_NSINFO, false);
    w1.recoverUnfinalizedSegments();
    assertEquals(1, w1.getLoggerSetForTests().getEpoch());
    writeSegment(cluster, w1, 1, 3, true);
    w1.close();
    toClose.remove(w1);

    // Attempt A1 to become writer: getJournalState from all -> epoch 2.
    // The newEpoch(2) requests to JN0 and JN1 are lost / time out; only
    // JN2 receives it. The attempt fails for lack of a quorum.
    QuorumJournalManager a1 = newQJM();
    futureThrows(new IOException("injected: newEpoch request to JN0 lost"))
        .when(spies(a1).get(0)).newEpoch(Mockito.anyLong());
    futureThrows(new IOException("injected: newEpoch request to JN1 lost"))
        .when(spies(a1).get(1)).newEpoch(Mockito.anyLong());
    try {
      a1.recoverUnfinalizedSegments();
      fail("attempt A1 should not get a quorum");
    } catch (IOException e) {
      LOG.info("Attempt A1 failed as expected", e);
    }
    a1.close();
    toClose.remove(a1);

    // Attempt A2 (retry): getJournalState answered by JN1 (promise 1) and
    // JN2 (promise 2) -> epoch 3. Again only JN2 receives newEpoch(3).
    QuorumJournalManager a2 = newQJM();
    futureThrows(new IOException("injected: getJournalState to JN0 lost"))
        .when(spies(a2).get(0)).getJournalState();
    futureThrows(new IOException("injected: newEpoch request to JN0 lost"))
        .when(spies(a2).get(0)).newEpoch(Mockito.anyLong());
    futureThrows(new IOException("injected: newEpoch request to JN1 lost"))
        .when(spies(a2).get(1)).newEpoch(Mockito.anyLong());
    try {
      a2.recoverUnfinalizedSegments();
      fail("attempt A2 should not get a quorum");
    } catch (IOException e) {
      LOG.info("Attempt A2 failed as expected", e);
    }
    a2.close();
    toClose.remove(a2);

    // Now: JN0 promise=1, JN1 promise=1, JN2 promise=3. All JNs are up and
    // healthy; nobody is writing.
    //
    // Writer W2 (the only writer in the system) starts. JN2 is merely slow to
    // answer getJournalState: the QJM returns as soon as a majority (JN0,
    // JN1) answered and picks epoch max(1,1)+1 = 2 < 3.
    QuorumJournalManager w2 = newQJM();
    final CountDownLatch releaseSlowJN = new CountDownLatch(1);
    final AsyncLogger slow = spies(w2).get(2);
    Mockito.doAnswer(inv -> {
      final SettableFuture<GetJournalStateResponseProto> f =
          SettableFuture.create();
      Thread t = new Thread(() -> {
        try {
          releaseSlowJN.await();
          @SuppressWarnings("unchecked")
          ListenableFuture<GetJournalStateResponseProto> real =
              (ListenableFuture<GetJournalStateResponseProto>)
                  inv.callRealMethod();
          f.setFuture(real);
        } catch (Throwable th) {
          f.setException(th);
        }
      }, "slow-JN2-getJournalState");
      t.setDaemon(true);
      t.start();
      return f;
    }).when(slow).getJournalState();

    w2.recoverUnfinalizedSegments();
    releaseSlowJN.countDown();
    LOG.info("W2 established epoch {}", w2.getLoggerSetForTests().getEpoch());

    // W2 starts writing: JN2 rejects in Journal.checkRequest because 2 < 3.
    EditLogOutputStream stm = w2.startLogSegment(4,
        NameNodeLayoutVersion.CURRENT_LAYOUT_VERSION);
    writeTxns(stm, 4, 3);
    stm.flush();

    // Consequence: JN2 is alive and healthy but unusable for the only
    // writer. Losing a single other JN (JN0) now makes the writer fail even
    // though 2 of 3 JNs (JN1, JN2) are up - a majority.
    cluster.getJournalNode(0).stopAndJoin(0);
    try {
      writeTxns(stm, 7, 3);
      stm.flush();
    } catch (IOException e) {
      LOG.error("Only writer W2 cannot write with JN1+JN2 alive", e);
      throw new AssertionError("The only writer (epoch "
          + w2.getLoggerSetForTests().getEpoch() + ") failed to write although"
          + " a majority of JNs (JN1, JN2) is alive: JN2 rejects it because"
          + " its epoch is below JN2's promise", e);
    }
  }
}
