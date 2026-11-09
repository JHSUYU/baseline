/*
 * Specula MC-1 reproduction (target hdfs-adhoc-08: Journal.checkRequest, Journal.java:487).
 *
 * Installed by repro/test_bugMC-1_orphan_promise.sh as
 *   hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/qjournal/client/
 *       TestSpeculaMC1OrphanPromise.java
 * and run against the pristine tree at base_commit 734dd8a67cd.
 *
 * Variant of the target workload TestQuorumJournalManager#testSingleWriter: the setup below is
 * copied from TestQuorumJournalManager#setup, and the workload body (writeSegment 1-3, checkRecovery,
 * writeSegment 4, checkRecovery) is run by the newest writer. Faults are injected only with the
 * utilities TestQuorumJournalManager already uses (Mockito spies from SpyQJournalUtil,
 * TestQuorumJournalManagerUnit.futureThrows, SettableFuture), and only the faults the counterexamples
 * use: a lost request (the RPC is never issued, the writer sees an error), a stopped writer (its
 * in-flight requests are never delivered), and a reply that arrives after the writer stopped waiting.
 * Nothing writes the guard's operands (RequestInfo epoch, lastPromisedEpoch) and the target method
 * is not modified; the JNs' promises are read from their last-promised-epoch files only.
 *
 * Epoch numbers are the counterexample's plus one, because the copied setup first establishes
 * epoch 1 on all three JNs for the workload's writer, which stops before the failed attempts.
 */
package org.apache.hadoop.hdfs.qjournal.client;

import static org.apache.hadoop.hdfs.qjournal.QJMTestUtil.FAKE_NSINFO;
import static org.apache.hadoop.hdfs.qjournal.QJMTestUtil.JID;
import static org.apache.hadoop.hdfs.qjournal.QJMTestUtil.writeSegment;
import static org.apache.hadoop.hdfs.qjournal.client.TestQuorumJournalManagerUnit.futureThrows;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import java.io.Closeable;
import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicReference;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.CommonConfigurationKeysPublic;
import org.apache.hadoop.hdfs.DFSConfigKeys;
import org.apache.hadoop.hdfs.qjournal.MiniJournalCluster;
import org.apache.hadoop.hdfs.qjournal.QJMTestUtil;
import org.apache.hadoop.hdfs.qjournal.protocol.QJournalProtocolProtos.GetJournalStateResponseProto;
import org.apache.hadoop.hdfs.qjournal.protocol.QJournalProtocolProtos.NewEpochResponseProto;
import org.apache.hadoop.hdfs.qjournal.protocol.QJournalProtocolProtos.PrepareRecoveryResponseProto;
import org.apache.hadoop.hdfs.qjournal.server.Journal;
import org.apache.hadoop.hdfs.server.namenode.FileJournalManager;
import org.apache.hadoop.hdfs.server.namenode.FileJournalManager.EditLogFile;
import org.apache.hadoop.hdfs.server.namenode.SpeculaMC1JournalSetHelper;
import org.apache.hadoop.hdfs.util.PersistentLongFile;
import org.apache.hadoop.io.IOUtils;
import org.apache.hadoop.ipc.ProtobufRpcEngine2;
import org.apache.hadoop.ipc.RemoteException;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.thirdparty.com.google.common.util.concurrent.FutureCallback;
import org.apache.hadoop.thirdparty.com.google.common.util.concurrent.Futures;
import org.apache.hadoop.thirdparty.com.google.common.util.concurrent.ListenableFuture;
import org.apache.hadoop.thirdparty.com.google.common.util.concurrent.MoreExecutors;
import org.apache.hadoop.thirdparty.com.google.common.util.concurrent.SettableFuture;
import org.apache.hadoop.util.ExitUtil;
import org.apache.hadoop.util.Lists;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInfo;
import org.mockito.Mockito;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.event.Level;

public class TestSpeculaMC1OrphanPromise {
  private static final Logger LOG = LoggerFactory.getLogger(
      TestSpeculaMC1OrphanPromise.class);

  /** The target frame: the throw at Journal.java:487-489 (javac attributes it to 489). */
  private static final Pattern TARGET_FRAME = Pattern.compile(
      "at (?:\\S*/)?org\\.apache\\.hadoop\\.hdfs\\.qjournal\\.server\\.Journal\\."
      + "checkRequest\\(Journal\\.java:(\\d+)\\)");

  private MiniJournalCluster cluster;
  private Configuration conf;
  private QuorumJournalManager qjm;
  private List<AsyncLogger> spies;

  private final List<QuorumJournalManager> toClose = Lists.newLinkedList();

  /** What JN0 answered to each RPC of the newest writer (observation only). */
  private static final class Jn0Outcome {
    private final String rpc;
    private final Throwable failure;

    Jn0Outcome(String rpc, Throwable failure) {
      this.rpc = rpc;
      this.failure = failure;
    }
  }

  private final List<Jn0Outcome> jn0Outcomes =
      Collections.synchronizedList(new ArrayList<>());

  static {
    GenericTestUtils.setLogLevel(ProtobufRpcEngine2.LOG, Level.TRACE);
  }

  // ---- copied from TestQuorumJournalManager#setup / #shutdown ----

  @BeforeEach
  public void setup(TestInfo testInfo) throws Exception {
    LOG.info("[MC-1] ===== {} =====", testInfo.getDisplayName());
    conf = new Configuration();
    // Don't retry connections - it just slows down the tests.
    conf.setInt(
        CommonConfigurationKeysPublic.IPC_CLIENT_CONNECT_MAX_RETRIES_KEY, 0);
    // Turn off IPC client caching to handle daemon restarts.
    conf.setInt(
        CommonConfigurationKeysPublic.IPC_CLIENT_CONNECTION_MAXIDLETIME_KEY, 0);
    conf.setBoolean(DFSConfigKeys.DFS_HA_TAILEDITS_INPROGRESS_KEY, true);

    cluster = new MiniJournalCluster.Builder(conf)
        .baseDir(GenericTestUtils.getRandomizedTestDir().getAbsolutePath())
        .build();
    cluster.waitActive();

    qjm = createSpyingQJM();
    spies = qjm.getLoggerSetForTests().getLoggersForTests();

    qjm.format(QJMTestUtil.FAKE_NSINFO, false);
    qjm.recoverUnfinalizedSegments();
    assertEquals(1, qjm.getLoggerSetForTests().getEpoch());
  }

  @AfterEach
  public void shutdown() throws IOException, InterruptedException,
      TimeoutException {
    ExitUtil.resetFirstExitException();
    IOUtils.cleanupWithLogger(LOG, toClose.toArray(new Closeable[0]));

    // Should not leak clients between tests -- this can cause flaky tests.
    // (See HDFS-4643)
    GenericTestUtils.waitForThreadTermination(".*IPC Client.*", 100, 1000);

    if (cluster != null) {
      cluster.shutdown();
      cluster = null;
    }
  }

  private QuorumJournalManager closeLater(QuorumJournalManager q) {
    toClose.add(q);
    return q;
  }

  private QuorumJournalManager createSpyingQJM() throws IOException {
    return closeLater(SpyQJournalUtil.createSpyingQJM(
        conf, cluster.getQuorumJournalURI(JID), FAKE_NSINFO, null));
  }

  /** TestQuorumJournalManager#checkRecovery, copied. */
  private void checkRecovery(MiniJournalCluster cluster,
      long segmentTxId, long expectedEndTxId)
      throws IOException {
    int numFinalized = 0;
    for (int i = 0; i < cluster.getNumNodes(); i++) {
      File logDir = cluster.getCurrentDir(i, JID);
      EditLogFile elf = FileJournalManager.getLogFile(logDir, segmentTxId);
      if (elf == null) {
        continue;
      }
      if (!elf.isInProgress()) {
        numFinalized++;
        if (elf.getLastTxId() != expectedEndTxId) {
          fail("File " + elf + " finalized to wrong txid, expected " +
              expectedEndTxId);
        }
      }
    }

    if (numFinalized < cluster.getQuorumSize()) {
      fail("Did not find a quorum of finalized logs starting at " +
          segmentTxId);
    }
  }

  /** Body of TestQuorumJournalManager#testSingleWriter, run by the given writer. */
  private void singleWriterWorkload(QuorumJournalManager w) throws Exception {
    writeSegment(cluster, w, 1, 3, true);
    // Should be finalized
    checkRecovery(cluster, 1, 3);
    // Start a new segment
    writeSegment(cluster, w, 4, 1, true);
    // Should be finalized
    checkRecovery(cluster, 4, 4);
  }

  // ---- read-only views and observation ----

  private static List<AsyncLogger> loggersOf(QuorumJournalManager q) {
    return q.getLoggerSetForTests().getLoggersForTests();
  }

  /** JN i's persisted promise, read from its last-promised-epoch file. */
  private long promise(int i) throws IOException {
    return PersistentLongFile.readFile(new File(cluster.getCurrentDir(i, JID),
        Journal.LAST_PROMISED_FILENAME), -1);
  }

  private String promises() throws IOException {
    return "JN0=" + promise(0) + " JN1=" + promise(1) + " JN2=" + promise(2);
  }

  private void assertPromises(long jn0, long jn1, long jn2) throws IOException {
    assertEquals("JN0=" + jn0 + " JN1=" + jn1 + " JN2=" + jn2, promises());
  }

  private <T> ListenableFuture<T> observed(final String rpc,
      ListenableFuture<T> f) {
    Futures.addCallback(f, new FutureCallback<T>() {
      @Override
      public void onSuccess(T result) {
        jn0Outcomes.add(new Jn0Outcome(rpc, null));
        LOG.info("[MC-1] newest writer -> JN0 {}: OK", rpc);
      }

      @Override
      public void onFailure(Throwable t) {
        jn0Outcomes.add(new Jn0Outcome(rpc, t));
        LOG.info("[MC-1] newest writer -> JN0 {}: FAILED {}", rpc,
            firstLine(t.toString()));
      }
    }, MoreExecutors.directExecutor());
    return f;
  }

  /** Records JN0's answer to every RPC of the writer; the real call is made unchanged. */
  @SuppressWarnings("unchecked")
  private void observeJn0(AsyncLogger jn0, boolean newEpochToo) {
    Mockito.doAnswer(inv -> observed(
        "startLogSegment(" + inv.getArgument(0) + ")",
        (ListenableFuture<Void>) inv.callRealMethod()))
        .when(jn0).startLogSegment(Mockito.anyLong(), Mockito.anyInt());
    Mockito.doAnswer(inv -> observed(
        "journal(firstTxId=" + inv.getArgument(1) + ")",
        (ListenableFuture<Void>) inv.callRealMethod()))
        .when(jn0).sendEdits(Mockito.anyLong(), Mockito.anyLong(),
            Mockito.anyInt(), Mockito.any());
    Mockito.doAnswer(inv -> observed(
        "finalizeLogSegment(" + inv.getArgument(0) + "-" + inv.getArgument(1)
            + ")",
        (ListenableFuture<Void>) inv.callRealMethod()))
        .when(jn0).finalizeLogSegment(Mockito.anyLong(), Mockito.anyLong());
    Mockito.doAnswer(inv -> observed(
        "prepareRecovery(" + inv.getArgument(0) + ")",
        (ListenableFuture<PrepareRecoveryResponseProto>) inv.callRealMethod()))
        .when(jn0).prepareRecovery(Mockito.anyLong());
    Mockito.doAnswer(inv -> observed("acceptRecovery",
        (ListenableFuture<Void>) inv.callRealMethod()))
        .when(jn0).acceptRecovery(Mockito.any(), Mockito.any());
    if (newEpochToo) {
      Mockito.doAnswer(inv -> observed("newEpoch(" + inv.getArgument(0) + ")",
          (ListenableFuture<NewEpochResponseProto>) inv.callRealMethod()))
          .when(jn0).newEpoch(Mockito.anyLong());
    }
  }

  /** The two JN-side frames under Journal.checkRequest: the RPC handler that ran the check. */
  private static String callerFrames(String serverTrace) {
    String[] lines = serverTrace.split("\n");
    for (int i = 0; i < lines.length; i++) {
      if (TARGET_FRAME.matcher(lines[i]).find()) {
        StringBuilder b = new StringBuilder();
        for (int j = i + 1; j < Math.min(i + 3, lines.length); j++) {
          b.append(j > i + 1 ? " <- " : "").append(lines[j].trim());
        }
        return b.toString();
      }
    }
    return "?";
  }

  private static String firstLine(String s) {
    int nl = s.indexOf('\n');
    return nl < 0 ? s : s.substring(0, nl);
  }

  private static String firstLines(String s, int n) {
    String[] lines = s.split("\n");
    StringBuilder b = new StringBuilder();
    for (int i = 0; i < Math.min(n, lines.length); i++) {
      b.append("    ").append(lines[i].trim()).append('\n');
    }
    return b.toString();
  }

  // ---- fault realizations ----

  /**
   * A NameNode starts a writer epoch attempt: getJournalState on all JNs, then newEpoch(e). JN0
   * handles newEpoch and persists the promise (Journal.java:347-352); the newEpoch requests to JN1
   * and JN2 are lost, so the quorum call fails and the NameNode terminates
   * (FSEditLog.recoverUnclosedStreams(true) -> terminate(1)).
   * Loss-only counterexample (MC_s1_lossonly_bfs_w1.out) States 2-14 / 15-27.
   */
  private void failedAttemptNewEpochLost(String who) throws Exception {
    QuorumJournalManager w = createSpyingQJM();
    List<AsyncLogger> s = loggersOf(w);
    futureThrows(new IOException("injected: newEpoch request to JN1 lost"))
        .when(s.get(1)).newEpoch(Mockito.anyLong());
    futureThrows(new IOException("injected: newEpoch request to JN2 lost"))
        .when(s.get(2)).newEpoch(Mockito.anyLong());
    QuorumException qe =
        assertThrows(QuorumException.class, w::recoverUnfinalizedSegments);
    LOG.info("[MC-1] {}: epoch attempt failed: {}", who,
        firstLine(qe.getMessage()));
    w.close();
    LOG.info("[MC-1] {}: writer stopped; promises {}", who, promises());
  }

  /**
   * A NameNode starts a writer epoch attempt and stops (crashes) after JN0 handled newEpoch(e) and
   * persisted the promise, while its newEpoch requests to JN1 and JN2 are still undelivered; those
   * requests are never delivered.
   * Primary counterexample (MC_hunt_orphan_promise_bfs_w1.out) States 2-9 / 10-17, and the
   * stop-only counterexample (MC_hunt_rollback_cache_bfs_w8.out) States 2-9 / 10-17.
   */
  private void failedAttemptWriterStops(String who) throws Exception {
    QuorumJournalManager w = createSpyingQJM();
    List<AsyncLogger> s = loggersOf(w);
    // Not yet delivered when the NameNode stops; never delivered afterwards.
    Mockito.doReturn(SettableFuture.create())
        .when(s.get(1)).newEpoch(Mockito.anyLong());
    Mockito.doReturn(SettableFuture.create())
        .when(s.get(2)).newEpoch(Mockito.anyLong());
    final long before = promise(0);
    ExecutorService nnThread = Executors.newSingleThreadExecutor();
    Future<?> recovery = nnThread.submit(() -> {
      w.recoverUnfinalizedSegments();
      return null;
    });
    // CE: HandleNewEpoch(j0, w) -- JN0 persisted the new promise.
    GenericTestUtils.waitFor(() -> {
      try {
        return promise(0) > before;
      } catch (IOException e) {
        return false;
      }
    }, 10, 30000);
    // CE: WriterStop(w) -- the NameNode stops; its in-flight requests are dropped.
    recovery.cancel(true);
    nnThread.shutdownNow();
    assertTrue(nnThread.awaitTermination(30, TimeUnit.SECONDS));
    w.close();
    LOG.info("[MC-1] {}: writer stopped after JN0 handled newEpoch; promises {}",
        who, promises());
  }

  /**
   * JN0 handles getJournalState (the real RPC is made), but its reply reaches the writer only
   * after the writer chose its epoch (CE: RecvReply(w, j0) after ChooseEpoch(w)).
   */
  @SuppressWarnings("unchecked")
  private SettableFuture<GetJournalStateResponseProto> lateGetJournalStateReply(
      AsyncLogger jn0,
      AtomicReference<ListenableFuture<GetJournalStateResponseProto>> real) {
    SettableFuture<GetJournalStateResponseProto> late = SettableFuture.create();
    Mockito.doAnswer(inv -> {
      real.set((ListenableFuture<GetJournalStateResponseProto>)
          inv.callRealMethod());
      return late;
    }).when(jn0).getJournalState();
    return late;
  }

  // ---- checks ----

  /**
   * Every RequestInfo RPC the newest writer sent to JN0 failed in Journal.checkRequest with the
   * target IOException. Returns how many times the target fired.
   */
  private int assertTargetFiredOnJn0(long writerEpoch, long jn0Promise) {
    String expected = "IPC's epoch " + writerEpoch
        + " is less than the last promised epoch " + jn0Promise;
    int fired = 0;
    synchronized (jn0Outcomes) {
      for (Jn0Outcome o : jn0Outcomes) {
        if (o.failure == null) {
          fail("JN0 accepted " + o.rpc + " from the newest writer (epoch "
              + writerEpoch + ")");
        }
        if (!(o.failure instanceof RemoteException)) {
          // IPCLoggerChannel stops sending to a JN whose journal() failed until the next
          // startLogSegment (outOfSync); these calls never reach JN0.
          LOG.info("[MC-1]   JN0 {}: not sent by the writer ({})", o.rpc,
              firstLine(o.failure.toString()));
          continue;
        }
        RemoteException re = (RemoteException) o.failure;
        String serverTrace = re.getMessage();
        if (o.rpc.startsWith("newEpoch")) {
          // Journal.newEpoch (J:347-349) rejects the writer's epoch; QJM goes on (QJM:243-247).
          assertTrue(serverTrace.startsWith("Proposed epoch " + writerEpoch
              + " <= last promise " + jn0Promise), serverTrace);
          LOG.info("[MC-1]   JN0 {}: rejected ({}), yet the writer set epoch {} "
              + "on JN0's channel too", o.rpc, firstLine(serverTrace),
              writerEpoch);
          continue;
        }
        assertEquals(IOException.class.getName(), re.getClassName());
        assertTrue(serverTrace.startsWith(expected), serverTrace);
        Matcher m = TARGET_FRAME.matcher(serverTrace);
        assertTrue(m.find(), "no Journal.checkRequest frame in " + serverTrace);
        int line = Integer.parseInt(m.group(1));
        assertTrue(line >= 487 && line <= 489, "frame line " + line);
        fired++;
        LOG.info("[MC-1]   JN0 {}: TARGET FIRED: {} | frame: {} <- {}", o.rpc,
            firstLine(serverTrace), m.group(), callerFrames(serverTrace));
        if (fired == 1) {
          LOG.info("[MC-1] first target throw, JN0 server-side stack "
              + "(RemoteException {}):\n{}", re.getClassName(),
              firstLines(serverTrace, 6));
        }
      }
    }
    assertTrue(fired > 0, "the target never fired on JN0");
    return fired;
  }

  private void assertJn0ServedEverything() {
    synchronized (jn0Outcomes) {
      assertTrue(!jn0Outcomes.isEmpty());
      for (Jn0Outcome o : jn0Outcomes) {
        assertNull(o.failure, "JN0 rejected " + o.rpc + ": " + o.failure);
      }
    }
  }

  /** No edit segment of the newest writer exists on JN0. */
  private void assertNoSegmentOnJn0(long... txIds) throws IOException {
    for (long txId : txIds) {
      assertNull(FileJournalManager.getLogFile(cluster.getCurrentDir(0, JID), txId),
          "JN0 has segment " + txId);
    }
  }

  /**
   * Persistence and consequence. JN0's promise is persistent, so restarting JN0 does not lift the
   * fence. With JN0 fenced, losing ONE more JournalNode leaves the writer without a quorum, and the
   * NameNode's own JournalSet (the shared QJM edits dir is a required journal) terminates the
   * NameNode (JournalSet.java:394-408). A three-JN quorum is meant to tolerate that one failure.
   */
  private boolean restartJn0ThenLoseJn1(QuorumJournalManager w, long nextTxId)
      throws Exception {
    cluster.restartJournalNode(0);
    LOG.info("[MC-1] JN0 restarted; promises {}", promises());
    writeSegment(cluster, w, nextTxId, 1, true);
    checkRecovery(cluster, nextTxId, nextTxId);

    cluster.getJournalNode(1).stopAndJoin(0);
    LOG.info("[MC-1] JN1 stopped (one JournalNode failure)");
    ExitUtil.disableSystemExit();
    try {
      SpeculaMC1JournalSetHelper.startLogSegmentAsNameNode(w, nextTxId + 1);
      LOG.info("[MC-1] NameNode's JournalSet started segment {} with JN1 down",
          nextTxId + 1);
      return false;
    } catch (ExitUtil.ExitException ee) {
      LOG.info("[MC-1] CONSEQUENCE: NameNode terminated (ExitUtil status {}): {}",
          ee.getExitCode(), ee.getMessage());
      LOG.info("[MC-1] cause logged by JournalSet: {}",
          SpeculaMC1JournalSetHelper.lastLoggedCause());
      return true;
    }
  }

  // ---- reproductions, one per counterexample ----

  /**
   * Primary counterexample spec/output/MC_hunt_orphan_promise_bfs_w1.out:
   * WriterStop x2 (attempts A, B), LoseRequest x2 (getJournalState and newEpoch to JN0 for C).
   */
  @Test
  public void testPrimaryCounterexample() throws Exception {
    // The workload's writer (epoch 1 on JN0-JN2) stops; writers never overlap.
    qjm.close();
    assertPromises(1, 1, 1);
    failedAttemptWriterStops("attempt A");              // CE States 2-9
    assertPromises(2, 1, 1);
    failedAttemptWriterStops("attempt B");              // CE States 10-17
    assertPromises(3, 1, 1);

    QuorumJournalManager c = createSpyingQJM();          // CE State 18
    AsyncLogger jn0 = loggersOf(c).get(0);
    observeJn0(jn0, false);
    futureThrows(new IOException("injected: getJournalState request to JN0 lost"))
        .when(jn0).getJournalState();                    // CE State 19
    futureThrows(new IOException("injected: newEpoch request to JN0 lost"))
        .when(jn0).newEpoch(Mockito.anyLong());          // CE State 25
    c.recoverUnfinalizedSegments();                      // CE States 20-30
    long epoch = c.getLoggerSetForTests().getEpoch();
    LOG.info("[MC-1] newest writer established epoch {} = 1 + max(JN1, JN2); "
        + "promises {}", epoch, promises());
    assertEquals(2, epoch);
    assertPromises(3, 2, 2);

    singleWriterWorkload(c);                             // CE States 31-32
    int fired = assertTargetFiredOnJn0(epoch, 3);
    assertNoSegmentOnJn0(1, 4);
    assertTrue(restartJn0ThenLoseJn1(c, 5));
    fired = assertTargetFiredOnJn0(epoch, 3);
    LOG.info("[MC-1] RESULT primary CE: target fired {} times for the newest "
        + "writer (epoch {}, JN0 promise 3)", fired, epoch);
  }

  /**
   * Loss-only counterexample spec/output/MC_s1_lossonly_bfs_w1.out: newEpoch to JN1 and JN2 lost
   * for attempts A and B (QuorumFail); for C, JN0's getJournalState reply arrives after C chose its
   * epoch and C's newEpoch to JN0 is lost.
   */
  @Test
  public void testLossOnlyCounterexample() throws Exception {
    qjm.close();
    assertPromises(1, 1, 1);
    failedAttemptNewEpochLost("attempt A");             // CE States 2-14
    assertPromises(2, 1, 1);
    failedAttemptNewEpochLost("attempt B");             // CE States 15-27
    assertPromises(3, 1, 1);

    QuorumJournalManager c = createSpyingQJM();          // CE State 28
    AsyncLogger jn0 = loggersOf(c).get(0);
    observeJn0(jn0, false);
    AtomicReference<ListenableFuture<GetJournalStateResponseProto>> real =
        new AtomicReference<>();
    SettableFuture<GetJournalStateResponseProto> late =
        lateGetJournalStateReply(jn0, real);             // CE State 29
    futureThrows(new IOException("injected: newEpoch request to JN0 lost"))
        .when(jn0).newEpoch(Mockito.anyLong());          // CE State 36
    c.recoverUnfinalizedSegments();                      // CE States 30-41
    late.set(real.get().get());                          // CE State 35 (late)
    LOG.info("[MC-1] JN0's getJournalState reply arrived late: "
        + "lastPromisedEpoch={}", late.get().getLastPromisedEpoch());
    long epoch = c.getLoggerSetForTests().getEpoch();
    LOG.info("[MC-1] newest writer established epoch {}; promises {}", epoch,
        promises());
    assertEquals(2, epoch);
    assertPromises(3, 2, 2);

    singleWriterWorkload(c);                             // CE States 42-43
    assertTargetFiredOnJn0(epoch, 3);
    assertNoSegmentOnJn0(1, 4);
    assertTrue(restartJn0ThenLoseJn1(c, 5));
    int fired = assertTargetFiredOnJn0(epoch, 3);
    LOG.info("[MC-1] RESULT loss-only CE: target fired {} times for the newest "
        + "writer (epoch {}, JN0 promise 3)", fired, epoch);
  }

  /**
   * Stop-only counterexample spec/output/MC_hunt_rollback_cache_bfs_w8.out: attempts A and B stop
   * after JN0 handled newEpoch; for C no message is lost at all -- JN0's getJournalState reply
   * merely arrives after C chose its epoch, and C's newEpoch reaches JN0 and is rejected.
   */
  @Test
  public void testStopOnlyCounterexample() throws Exception {
    qjm.close();
    assertPromises(1, 1, 1);
    failedAttemptWriterStops("attempt A");              // CE States 2-9
    failedAttemptWriterStops("attempt B");              // CE States 10-17
    assertPromises(3, 1, 1);

    QuorumJournalManager c = createSpyingQJM();          // CE State 18
    AsyncLogger jn0 = loggersOf(c).get(0);
    observeJn0(jn0, true);
    AtomicReference<ListenableFuture<GetJournalStateResponseProto>> real =
        new AtomicReference<>();
    SettableFuture<GetJournalStateResponseProto> late =
        lateGetJournalStateReply(jn0, real);             // CE State 19
    c.recoverUnfinalizedSegments();                      // CE States 20-32
    late.set(real.get().get());                          // CE State 25 (late)
    LOG.info("[MC-1] JN0's getJournalState reply arrived late: "
        + "lastPromisedEpoch={}", late.get().getLastPromisedEpoch());
    long epoch = c.getLoggerSetForTests().getEpoch();
    LOG.info("[MC-1] newest writer established epoch {}; promises {}", epoch,
        promises());
    assertEquals(2, epoch);
    assertPromises(3, 2, 2);

    singleWriterWorkload(c);                             // CE States 33-34
    assertTargetFiredOnJn0(epoch, 3);
    assertNoSegmentOnJn0(1, 4);
    assertTrue(restartJn0ThenLoseJn1(c, 5));
    int fired = assertTargetFiredOnJn0(epoch, 3);
    LOG.info("[MC-1] RESULT stop-only CE: target fired {} times for the newest "
        + "writer (epoch {}, JN0 promise 3)", fired, epoch);
  }

  /**
   * The workload exactly as TestQuorumJournalManager#testSingleWriter runs it (by the setup's
   * writer), then a failover with the loss-only faults and a late JN0 reply: the newest writer's
   * recovery RPCs to JN0 already fail at the target, and so does everything after them.
   */
  @Test
  public void testWorkloadThenFailover() throws Exception {
    singleWriterWorkload(qjm);
    qjm.close();
    assertPromises(1, 1, 1);
    failedAttemptNewEpochLost("attempt A");
    failedAttemptNewEpochLost("attempt B");
    assertPromises(3, 1, 1);

    QuorumJournalManager c = createSpyingQJM();
    AsyncLogger jn0 = loggersOf(c).get(0);
    observeJn0(jn0, true);
    AtomicReference<ListenableFuture<GetJournalStateResponseProto>> real =
        new AtomicReference<>();
    SettableFuture<GetJournalStateResponseProto> late =
        lateGetJournalStateReply(jn0, real);
    c.recoverUnfinalizedSegments();
    late.set(real.get().get());
    long epoch = c.getLoggerSetForTests().getEpoch();
    LOG.info("[MC-1] newest writer established epoch {}; promises {}", epoch,
        promises());
    assertEquals(2, epoch);
    assertPromises(3, 2, 2);

    writeSegment(cluster, c, 5, 3, true);
    checkRecovery(cluster, 5, 7);
    int fired = assertTargetFiredOnJn0(epoch, 3);
    assertNoSegmentOnJn0(5);
    LOG.info("[MC-1] RESULT workload-then-failover: target fired {} times for "
        + "the newest writer (epoch {}, JN0 promise 3)", fired, epoch);
  }

  /**
   * The primary counterexample realized with real JournalNode outages only. The spy is used only
   * to time the outages: JN1 and JN2 go down after answering getJournalState and before newEpoch
   * reaches them (attempts A and B fail and the NameNode terminates; JN1 and JN2 come back), and
   * JN0 is down while the newest writer establishes its epoch, then comes back. No request is
   * failed by a mock.
   */
  @Test
  public void testPrimaryCounterexampleRealOutages() throws Exception {
    qjm.close();
    assertPromises(1, 1, 1);
    for (String who : new String[] {"attempt A", "attempt B"}) {
      QuorumJournalManager w = createSpyingQJM();
      List<AsyncLogger> s = loggersOf(w);
      for (final int jn : new int[] {1, 2}) {
        Mockito.doAnswer(inv -> {
          cluster.getJournalNode(jn).stopAndJoin(0);   // JN goes down now
          return inv.callRealMethod();
        }).when(s.get(jn)).newEpoch(Mockito.anyLong());
      }
      QuorumException qe =
          assertThrows(QuorumException.class, w::recoverUnfinalizedSegments);
      LOG.info("[MC-1] {}: epoch attempt failed: {}", who,
          firstLine(qe.getMessage()));
      w.close();                                   // the NameNode terminates
      cluster.restartJournalNode(1);
      cluster.restartJournalNode(2);
      LOG.info("[MC-1] {}: JN1, JN2 back up; promises {}", who, promises());
    }
    assertPromises(3, 1, 1);

    cluster.getJournalNode(0).stopAndJoin(0);
    LOG.info("[MC-1] JN0 down while the newest writer establishes its epoch");
    QuorumJournalManager c = createSpyingQJM();
    observeJn0(loggersOf(c).get(0), false);
    c.recoverUnfinalizedSegments();
    long epoch = c.getLoggerSetForTests().getEpoch();
    cluster.restartJournalNode(0);
    LOG.info("[MC-1] JN0 back up; newest writer epoch {}; promises {}", epoch,
        promises());
    assertEquals(2, epoch);
    assertPromises(3, 2, 2);

    singleWriterWorkload(c);
    assertTargetFiredOnJn0(epoch, 3);
    assertNoSegmentOnJn0(1, 4);
    cluster.getJournalNode(1).stopAndJoin(0);
    LOG.info("[MC-1] JN1 stopped (one JournalNode failure)");
    ExitUtil.disableSystemExit();
    ExitUtil.ExitException ee = assertThrows(ExitUtil.ExitException.class,
        () -> SpeculaMC1JournalSetHelper.startLogSegmentAsNameNode(c, 5));
    LOG.info("[MC-1] CONSEQUENCE: NameNode terminated (ExitUtil status {}): {}",
        ee.getExitCode(), ee.getMessage());
    int fired = assertTargetFiredOnJn0(epoch, 3);
    LOG.info("[MC-1] RESULT primary CE, real outages: target fired {} times for "
        + "the newest writer (epoch {}, JN0 promise 3)", fired, epoch);
  }

  // ---- controls ----

  /**
   * Control 1: the same faults on the newest writer (late JN0 reply, lost newEpoch to JN0) but no
   * orphan promise. JN0 serves the writer; one JN failure is tolerated.
   */
  @Test
  public void testControlNoOrphanPromise() throws Exception {
    qjm.close();
    QuorumJournalManager c = createSpyingQJM();
    AsyncLogger jn0 = loggersOf(c).get(0);
    observeJn0(jn0, false);
    AtomicReference<ListenableFuture<GetJournalStateResponseProto>> real =
        new AtomicReference<>();
    SettableFuture<GetJournalStateResponseProto> late =
        lateGetJournalStateReply(jn0, real);
    futureThrows(new IOException("injected: newEpoch request to JN0 lost"))
        .when(jn0).newEpoch(Mockito.anyLong());
    c.recoverUnfinalizedSegments();
    late.set(real.get().get());
    long epoch = c.getLoggerSetForTests().getEpoch();
    assertEquals(2, epoch);

    singleWriterWorkload(c);
    assertJn0ServedEverything();
    assertPromises(2, 2, 2);
    assertTrue(!restartJn0ThenLoseJn1(c, 5),
        "NameNode terminated although only one JN failed");
    assertJn0ServedEverything();
    LOG.info("[MC-1] CONTROL no-orphan: JN0 served every RPC of epoch {}; "
        + "JN1 loss tolerated", epoch);
  }

  /**
   * Control 2: the same orphan promises, but the newest writer hears JN0's getJournalState in
   * time. It picks an epoch above JN0's promise; JN0 serves it; one JN failure is tolerated.
   */
  @Test
  public void testControlTimelyJn0Reply() throws Exception {
    qjm.close();
    failedAttemptNewEpochLost("attempt A");
    failedAttemptNewEpochLost("attempt B");
    assertPromises(3, 1, 1);

    QuorumJournalManager c = createSpyingQJM();
    observeJn0(loggersOf(c).get(0), true);
    c.recoverUnfinalizedSegments();
    long epoch = c.getLoggerSetForTests().getEpoch();
    assertEquals(4, epoch);

    singleWriterWorkload(c);
    assertJn0ServedEverything();
    assertPromises(4, 4, 4);
    assertTrue(!restartJn0ThenLoseJn1(c, 5),
        "NameNode terminated although only one JN failed");
    assertJn0ServedEverything();
    LOG.info("[MC-1] CONTROL timely-reply: JN0 served every RPC of epoch {}; "
        + "JN1 loss tolerated", epoch);
  }
}
