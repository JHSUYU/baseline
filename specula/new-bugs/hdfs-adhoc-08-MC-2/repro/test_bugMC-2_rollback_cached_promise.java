/*
 * Specula finding MC-2 (target hdfs-adhoc-08): reproduction test.
 *
 * Installed by repro/test_bugMC-2_rollback_cached_promise.sh as
 * hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/qjournal/client/
 *   TestBugMC2RollbackCachedPromise.java
 * in the pinned tree (734dd8a67cd), and run with surefire in module hadoop-hdfs.
 *
 * Claim: Journal.doRollback (Journal.java:1189-1196) puts previous/ back as current/ and re-reads
 * VERSION, but never calls refreshCachedData() (Journal.java:202-213; format() does, :259).
 * JournalNode.doRollback (JournalNode.java:487-491) runs on the live Journal object. A JournalNode
 * that stays up across "namenode -rollback" therefore keeps its post-upgrade lastPromisedEpoch in
 * the PersistentLongFile cache (PersistentLongFile.java:53-59), while its disk holds the
 * pre-upgrade value. The next writer can pick an epoch from JNs that report the rolled-back value
 * (QuorumJournalManager.java:232-242). The stale JN then rejects that writer at the target throw
 * of Journal.checkRequest (Journal.java:486-489).
 *
 * This is a variant of TestQuorumJournalManager#testSingleWriter (the target's workload). It uses
 * the same MiniJournalCluster configuration and the same writer setup: SpyQJournalUtil spying
 * QJM, format, recoverUnfinalizedSegments -> epoch 1.
 * Only public operations change state:
 *   - upgrade: QJM.doPreUpgrade/doUpgrade, the calls FSImage.doUpgrade makes (FSImage.java:490, :499);
 *   - writers: QJM.recoverUnfinalizedSegments (createNewUniqueEpoch), what an NN does when it
 *     becomes active;
 *   - writer stop: QJM.close();
 *   - JN restart: MiniJournalCluster.restartJournalNode;
 *   - rollback: QJM.canRollBack/doRollback, the calls FSImage.doRollback makes (FSImage.java:542,
 *     :565), with all JNs running.
 * The counterexample's message order uses the spy loggers of SpyQJournalUtil, the workload's own
 * test utility. A request is held "in flight" until its writer stops, or a reply is delivered
 * late. No Journal state is written directly; Whitebox is only read, for diagnostics.
 *
 * Environment: MC2_EXPECT=bug asserts that the target fires in the counterexample scenarios.
 * MC2_EXPECT=fixed asserts that it never fires. Unset, the test only reports.
 */
package org.apache.hadoop.hdfs.qjournal.client;

import static org.apache.hadoop.hdfs.qjournal.QJMTestUtil.FAKE_NSINFO;
import static org.apache.hadoop.hdfs.qjournal.QJMTestUtil.JID;
import static org.apache.hadoop.hdfs.qjournal.QJMTestUtil.writeTxns;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.File;
import java.io.IOException;
import java.net.URI;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.atomic.AtomicReference;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.CommonConfigurationKeysPublic;
import org.apache.hadoop.hdfs.DFSConfigKeys;
import org.apache.hadoop.hdfs.qjournal.MiniJournalCluster;
import org.apache.hadoop.hdfs.qjournal.protocol.QJournalProtocolProtos.GetJournalStateResponseProto;
import org.apache.hadoop.hdfs.qjournal.protocol.QJournalProtocolProtos.NewEpochResponseProto;
import org.apache.hadoop.hdfs.qjournal.server.Journal;
import org.apache.hadoop.hdfs.server.common.HdfsServerConstants;
import org.apache.hadoop.hdfs.server.namenode.EditLogInputStream;
import org.apache.hadoop.hdfs.server.namenode.EditLogOutputStream;
import org.apache.hadoop.hdfs.server.namenode.NNStorage;
import org.apache.hadoop.hdfs.server.namenode.NameNodeLayoutVersion;
import org.apache.hadoop.hdfs.util.PersistentLongFile;
import org.apache.hadoop.io.IOUtils;
import org.apache.hadoop.ipc.ProtobufRpcEngine2;
import org.apache.hadoop.ipc.RemoteException;
import org.apache.hadoop.ipc.Server;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.apache.hadoop.test.Whitebox;
import org.apache.hadoop.thirdparty.com.google.common.util.concurrent.ListenableFuture;
import org.apache.hadoop.thirdparty.com.google.common.util.concurrent.SettableFuture;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.mockito.Mockito;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.event.Level;

public class TestBugMC2RollbackCachedPromise {
  private static final Logger LOG =
      LoggerFactory.getLogger(TestBugMC2RollbackCachedPromise.class);

  private static final String EXPECT = System.getenv("MC2_EXPECT");
  private static final String TARGET_MSG = " is less than the last promised epoch ";
  private static final String TARGET_FRAME =
      "org.apache.hadoop.hdfs.qjournal.server.Journal.checkRequest(Journal.java:";

  private enum Mode {
    /** CE steps, JNRestart(j0) (CE state 43) ordered after Rollback (CE state 44). */
    CE_STEPS_RESTART_AFTER_ROLLBACK,
    /** CE steps in their literal order: JNRestart(j0) before Rollback. */
    CE_ORDER,
    /** Control: CE_STEPS_RESTART_AFTER_ROLLBACK, but j1's getJournalState reply is in time. */
    CONTROL_REPLY_IN_TIME,
    /** Beyond the CE: no held requests; j0 and j2 both restart after the rollback. */
    TWO_RESTARTS_AFTER_ROLLBACK
  }

  private interface IORunnable {
    void run() throws IOException;
  }

  private static final class Result {
    private Mode mode;
    private long w4Epoch = -1;
    private final long[] reported = {-1, -1, -1};
    private String j1NewEpoch = "-";
    private String j1Start = "-";
    private String j1Journal = "-";
    private String j1StartAfterRoll = "-";
    private String writeWithJ2Down = "-";
    private String trace = null;
    private String frame = "-";
    private boolean targetFired;
  }

  private MiniJournalCluster cluster;
  private Configuration conf;
  private final List<QuorumJournalManager> toClose = new ArrayList<>();

  static {
    // As in TestQuorumJournalManager: per-call client RPC trace ("Call ->", "Response <-",
    // "Exception <-"), used here to show when each JN's getJournalState reply arrived.
    GenericTestUtils.setLogLevel(ProtobufRpcEngine2.LOG, Level.TRACE);
  }

  private static void say(String fmt, Object... args) {
    System.out.println("MC2: " + String.format(fmt, args));
  }

  /** Same configuration as TestQuorumJournalManager#setup. */
  private void startCluster() throws IOException {
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
    stopCluster();
  }

  private void stopCluster() throws IOException {
    for (QuorumJournalManager q : toClose) {
      IOUtils.cleanupWithLogger(LOG, q);
    }
    toClose.clear();
    if (cluster != null) {
      cluster.shutdown();
      cluster = null;
    }
  }

  /** A writer built like the workload's (SpyQJournalUtil.createSpyingQJM). */
  private QuorumJournalManager spyingQjm() throws IOException {
    QuorumJournalManager q = SpyQJournalUtil.createSpyingQJM(
        conf, cluster.getQuorumJournalURI(JID), FAKE_NSINFO, null);
    toClose.add(q);
    return q;
  }

  /** A production QJM: one IPC executor thread per JournalNode. */
  private QuorumJournalManager plainQjm() throws IOException {
    QuorumJournalManager q = new QuorumJournalManager(
        conf, cluster.getQuorumJournalURI(JID), FAKE_NSINFO);
    toClose.add(q);
    return q;
  }

  /** WriterStop: the NameNode holding this QJM goes away. */
  private void stop(QuorumJournalManager q) {
    toClose.remove(q);
    IOUtils.cleanupWithLogger(LOG, q);
  }

  private static List<AsyncLogger> spies(QuorumJournalManager q) {
    return q.getLoggerSetForTests().getLoggersForTests();
  }

  /** Storage info of the upgraded NN state (same LV, new cTime), as FSImage.doUpgrade passes it. */
  private NNStorage upgradedStorage() throws IOException {
    NNStorage st = new NNStorage(conf, Collections.<URI>emptyList(),
        Collections.<URI>emptyList());
    st.layoutVersion = HdfsServerConstants.NAMENODE_LAYOUT_VERSION;
    st.namespaceID = FAKE_NSINFO.getNamespaceID();
    st.clusterID = FAKE_NSINFO.getClusterID();
    st.cTime = FAKE_NSINFO.getCTime() + 1;
    return st;
  }

  /** CE state 17, Upgrade: the shared-log calls of FSImage.doUpgrade (FSImage.java:490, :499). */
  private void upgrade(QuorumJournalManager w) throws IOException {
    w.doPreUpgrade();
    w.doUpgrade(upgradedStorage());
  }

  /**
   * CE state 44, Rollback: the shared-log calls of FSImage.doRollback (FSImage.java:542, :565).
   * All JNs are running; the NNs are down.
   */
  private void rollback(IORunnable betweenCanRollBackAndDoRollback) throws IOException {
    QuorumJournalManager admin = plainQjm();
    NNStorage prev = new NNStorage(conf, Collections.<URI>emptyList(),
        Collections.<URI>emptyList());
    prev.layoutVersion = HdfsServerConstants.NAMENODE_LAYOUT_VERSION; // FSImage.java:528
    assertTrue(admin.canRollBack(upgradedStorage(), prev,
        HdfsServerConstants.NAMENODE_LAYOUT_VERSION));
    if (betweenCanRollBackAndDoRollback != null) {
      betweenCanRollBackAndDoRollback.run();
    }
    admin.doRollback();
    stop(admin);
  }

  private long promiseFile(File dir) throws IOException {
    return PersistentLongFile.readFile(
        new File(dir, Journal.LAST_PROMISED_FILENAME), -1);
  }

  private long diskPromise(int jn) throws IOException {
    return promiseFile(cluster.getCurrentDir(jn, JID));
  }

  private String disk() throws IOException {
    return diskPromise(0) + "," + diskPromise(1) + "," + diskPromise(2);
  }

  private String previous() throws IOException {
    return promiseFile(cluster.getPreviousDir(0, JID)) + ","
        + promiseFile(cluster.getPreviousDir(1, JID)) + ","
        + promiseFile(cluster.getPreviousDir(2, JID));
  }

  /** Read-only look at a JN's in-memory promise: no RPC, creates and loads nothing. */
  private String cache(int jn) {
    Journal j = cluster.getJournalNode(jn).getJournal(JID);
    if (j == null) {
      return "no Journal object";
    }
    Object plf = Whitebox.getInternalState(j, "lastPromisedEpoch");
    return "loaded=" + Whitebox.getInternalState(plf, "loaded")
        + " value=" + Whitebox.getInternalState(plf, "value");
  }

  private String caches() {
    return "j0[" + cache(0) + "] j1[" + cache(1) + "] j2[" + cache(2) + "]";
  }

  /** The writer's getJournalState/newEpoch to this JN stay in flight; WriterStop drops them. */
  private static void holdInFlight(AsyncLogger spy) {
    Mockito.doReturn(SettableFuture.<GetJournalStateResponseProto>create())
        .when(spy).getJournalState();
    Mockito.doReturn(SettableFuture.<NewEpochResponseProto>create())
        .when(spy).newEpoch(Mockito.anyLong());
  }

  /** An NN that becomes active (createNewUniqueEpoch via recoverUnfinalizedSegments), then stops. */
  private void writerEstablishesAndStops(String name, long expectedEpoch,
      boolean j2InFlight) throws IOException {
    QuorumJournalManager w = spyingQjm();
    if (j2InFlight) {
      holdInFlight(spies(w).get(2));
    }
    w.recoverUnfinalizedSegments();
    assertEquals(expectedEpoch, w.getLoggerSetForTests().getEpoch());
    stop(w);
    say("%s established epoch %d%s; WriterStop(%s)", name, expectedEpoch,
        j2InFlight ? " (its requests to j2 still in flight)" : " on j0,j1,j2",
        name.substring(1));
  }

  private static String firstLine(String s) {
    if (s == null) {
      return "null";
    }
    int i = s.indexOf('\n');
    return i < 0 ? s : s.substring(0, i);
  }

  private static String describe(Throwable c) {
    if (c instanceof RemoteException) {
      return "RemoteException(" + ((RemoteException) c).getClassName() + "): "
          + firstLine(c.getMessage());
    }
    return c.getClass().getName() + ": " + firstLine(c.getMessage());
  }

  private static String outcome(ListenableFuture<?> f) {
    if (!f.isDone()) {
      return "PENDING";
    }
    try {
      f.get();
      return "OK";
    } catch (ExecutionException e) {
      return describe(e.getCause());
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      return "INTERRUPTED";
    }
  }

  private static <T> void deliver(SettableFuture<T> late, ListenableFuture<T> handled) {
    try {
      late.set(handled.get());
    } catch (ExecutionException e) {
      late.setException(e.getCause());
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      late.setException(e);
    }
  }

  private static long promised(ListenableFuture<GetJournalStateResponseProto> f) {
    try {
      return f.isDone() ? f.get().getLastPromisedEpoch() : -1;
    } catch (Exception e) {
      return -1;
    }
  }

  /** The JN-side stack trace of the target throw, as the IPC server logs it (Server.java:3360). */
  private static String targetTrace(String log, long epoch) {
    int i = log.indexOf("java.io.IOException: IPC's epoch " + epoch + TARGET_MSG);
    if (i < 0) {
      return null;
    }
    String[] lines = log.substring(i).split("\n");
    StringBuilder sb = new StringBuilder(lines[0].trim());
    for (int k = 1; k < lines.length && k <= 3; k++) {
      sb.append("\n\t").append(lines[k].trim());
    }
    return sb.toString();
  }

  /** getJournalState/newEpoch lines of the client RPC trace, JN addresses replaced by j0..j2. */
  private String rpcOrder(String log) {
    StringBuilder sb = new StringBuilder();
    for (String line : log.split("\n")) {
      if (!(line.contains("getJournalState") || line.contains("newEpoch"))
          || !(line.contains(": Call -> ") || line.contains(": Response <- ")
              || line.contains(": Exception <- "))) {
        continue;
      }
      int m = line.indexOf(" - ");
      String msg = m < 0 ? line : line.substring(m + 3);
      for (int i = 0; i < 3; i++) {
        String addr = cluster.getJournalNodeIpcAddress(i);
        String port = addr.substring(addr.lastIndexOf(':'));
        msg = msg.replaceAll("\\S*" + java.util.regex.Pattern.quote(port), "j" + i);
      }
      msg = msg.replaceAll("\\{jid \\{ identifier: \"test-journal\" \\}", "{")
          .replaceAll(" httpPort: \\d+| fromURL: \"[^\"]*\"", "");
      sb.append("    ").append(line, 0, Math.min(23, line.length())).append(' ')
          .append(msg.length() > 150 ? msg.substring(0, 150) : msg).append('\n');
    }
    return sb.toString().replaceAll("\n$", "");
  }

  private Result runScenario(Mode mode) throws Exception {
    startCluster();
    final Result r = new Result();
    r.mode = mode;
    say("=== scenario %s === (MC2_EXPECT=%s)", mode, EXPECT);
    for (int i = 0; i < 3; i++) {
      say("j%d = JournalNode %s", i, cluster.getJournalNodeIpcAddress(i));
    }

    // CE states 2-16: W1 (the workload's writer, TestQuorumJournalManager#setup).
    QuorumJournalManager w1 = spyingQjm();
    w1.format(FAKE_NSINFO, false);
    w1.recoverUnfinalizedSegments();
    assertEquals(1, w1.getLoggerSetForTests().getEpoch());
    upgrade(w1);                                                   // CE 17
    say("CE 17 Upgrade(1) done; previous/ promise on disk = %s", previous());
    stop(w1);                                                      // CE 18

    boolean holdJ2 = mode != Mode.TWO_RESTARTS_AFTER_ROLLBACK;
    writerEstablishesAndStops("W2", 2, holdJ2);                    // CE 19-30
    writerEstablishesAndStops("W3", 3, holdJ2);                    // CE 31-42
    say("after W3: current/ promise on disk = %s; caches %s", disk(), caches());

    if (mode == Mode.CE_ORDER) {
      cluster.restartJournalNode(0);                               // CE 43
      say("CE 43 JNRestart(j0); j0: %s", cache(0));
      rollback(() -> say("between canRollBack and doRollback: j0 cache: %s;"
          + " on-disk current/ promise = %s", cache(0), disk()));  // CE 44
      say("CE 44 Rollback done; current/ promise on disk = %s; caches %s",
          disk(), caches());
    } else {
      rollback(null);                                              // CE 44
      say("CE 44 Rollback done; current/ promise on disk = %s, previous/ exists = %s,%s,%s;"
          + " caches %s", disk(), cluster.getPreviousDir(0, JID).exists(),
          cluster.getPreviousDir(1, JID).exists(), cluster.getPreviousDir(2, JID).exists(),
          caches());
      cluster.restartJournalNode(0);                               // CE 43, after the rollback
      say("CE 43 JNRestart(j0) (after the rollback); j0: %s", cache(0));
      if (mode == Mode.TWO_RESTARTS_AFTER_ROLLBACK) {
        cluster.restartJournalNode(2);
        say("JNRestart(j2) (after the rollback); j2: %s", cache(2));
      }
    }

    // CE states 45-59: W4 becomes active.
    QuorumJournalManager w4 = spyingQjm();
    List<AsyncLogger> s4 = spies(w4);
    final boolean delayJ1 = mode != Mode.CONTROL_REPLY_IN_TIME;
    final AtomicReference<ListenableFuture<GetJournalStateResponseProto>> j1Handled =
        new AtomicReference<>();
    final SettableFuture<GetJournalStateResponseProto> j1Late = SettableFuture.create();
    for (int i = 0; i < 3; i++) {
      final int jn = i;
      Mockito.doAnswer(inv -> {
        // The JN handles getJournalState now (CE 46, 48, 49).
        @SuppressWarnings("unchecked")
        ListenableFuture<GetJournalStateResponseProto> f =
            (ListenableFuture<GetJournalStateResponseProto>) inv.callRealMethod();
        r.reported[jn] = promised(f);
        if (jn == 1 && delayJ1) {
          j1Handled.set(f);
          return j1Late;            // j1's reply is still in flight at ChooseEpoch (CE 51)
        }
        return f;
      }).when(s4.get(i)).getJournalState();
    }
    Mockito.doAnswer(inv -> {
      if (delayJ1) {
        deliver(j1Late, j1Handled.get());                          // CE 54: RecvReply(4,j1)
      }
      @SuppressWarnings("unchecked")
      ListenableFuture<NewEpochResponseProto> f =
          (ListenableFuture<NewEpochResponseProto>) inv.callRealMethod();   // CE 55
      r.j1NewEpoch = outcome(f);
      return f;
    }).when(s4.get(1)).newEpoch(Mockito.anyLong());

    w4.recoverUnfinalizedSegments();
    r.w4Epoch = w4.getLoggerSetForTests().getEpoch();
    say("W4 getJournalState lastPromisedEpoch reported by j0,j1,j2 = %d,%d,%d%s;"
        + " on-disk current/ promise = %s", r.reported[0], r.reported[1], r.reported[2],
        delayJ1 ? " (j1's reply arrived after the choice)" : "", disk());
    say("W4 established epoch %d; j1 newEpoch -> %s", r.w4Epoch, r.j1NewEpoch);

    // CE states 60-61: W4 starts its first log segment; every JN runs Journal.checkRequest.
    final AtomicReference<String> j1StartRef = new AtomicReference<>("-");
    final AtomicReference<String> j1JournalRef = new AtomicReference<>("-");
    Mockito.doAnswer(inv -> {
      ListenableFuture<?> f = (ListenableFuture<?>) inv.callRealMethod();
      j1StartRef.set(outcome(f));
      return f;
    }).when(s4.get(1)).startLogSegment(Mockito.anyLong(), Mockito.anyInt());
    Mockito.doAnswer(inv -> {
      ListenableFuture<?> f = (ListenableFuture<?>) inv.callRealMethod();
      j1JournalRef.set(outcome(f));
      return f;
    }).when(s4.get(1)).sendEdits(Mockito.anyLong(), Mockito.anyLong(),
        Mockito.anyInt(), Mockito.any(byte[].class));

    LogCapturer ipcLog = LogCapturer.captureLogs(Server.LOG);
    try {
      EditLogOutputStream stm = w4.startLogSegment(1,
          NameNodeLayoutVersion.CURRENT_LAYOUT_VERSION);           // CE 60 -> TargetCheck CE 61
      r.j1Start = j1StartRef.get();
      say("W4 startLogSegment(1) returned (quorum reached); j1 -> %s", r.j1Start);
      writeTxns(stm, 1, 3);
      r.j1Journal = j1JournalRef.get();
      say("W4 wrote txns 1-3 (quorum); j1 journal() -> %s", r.j1Journal);
      stm.close();
      w4.finalizeLogSegment(1, 3);
      j1StartRef.set("-");
      EditLogOutputStream stm2 = w4.startLogSegment(4,
          NameNodeLayoutVersion.CURRENT_LAYOUT_VERSION);           // the next log roll
      r.j1StartAfterRoll = j1StartRef.get();
      say("after a log roll, W4 startLogSegment(4); j1 -> %s", r.j1StartAfterRoll);
      say("j1 on-disk promise = %d, j1 cache: %s", diskPromise(1), cache(1));
      // One more JN outage, which a quorum of 3 JNs is meant to tolerate.
      cluster.getJournalNode(2).stopAndJoin(0);
      try {
        writeTxns(stm2, 4, 1);
        r.writeWithJ2Down = "OK";
      } catch (IOException e) {
        r.writeWithJ2Down = "FAILED: " + describe(e);
      }
      say("with j2 down, W4 write of txn 4 -> %s", r.writeWithJ2Down);
    } finally {
      ipcLog.stopCapturing();
    }
    r.trace = targetTrace(ipcLog.getOutput(), r.w4Epoch);
    if (r.trace != null) {
      say("JN-side stack trace of the IOException j1 returned to W4's startLogSegment"
          + " (IPC server log):%n%s", r.trace);
      for (String line : r.trace.split("\n")) {
        if (line.contains(TARGET_FRAME)) {
          r.frame = line.trim().replaceFirst("^at ", "");
          break;
        }
      }
    }
    r.targetFired = r.j1Start.contains(TARGET_MSG) && r.j1Start.contains("java.io.IOException")
        && r.frame.startsWith(TARGET_FRAME);
    say("MC2-RESULT scenario=%s w4Epoch=%d reported(j0,j1,j2)=%d,%d,%d targetFiredOnJ1=%s"
        + " frame=%s j1FencedAfterRoll=%s writeWithJ2Down=%s", mode, r.w4Epoch,
        r.reported[0], r.reported[1], r.reported[2], r.targetFired, r.frame,
        r.j1StartAfterRoll.contains(TARGET_MSG),
        r.writeWithJ2Down.startsWith("OK") ? "OK" : "FAILED");
    return r;
  }

  private static void expect(Result r, boolean firesWithBug) {
    if ("bug".equals(EXPECT)) {
      assertEquals(firesWithBug, r.targetFired, "target fired in " + r.mode);
      if (firesWithBug) {
        assertEquals(2, r.w4Epoch);
        assertNotNull(r.trace);
        assertTrue(r.j1StartAfterRoll.contains(TARGET_MSG), "fenced again after a roll");
      }
    } else if ("fixed".equals(EXPECT)) {
      assertFalse(r.targetFired, "target fired in " + r.mode);
    }
  }

  /** Level 1, the counterexample's steps (JNRestart(j0) after the rollback). */
  @Test
  @Timeout(180)
  public void testCeStepsRestartAfterRollback() throws Exception {
    expect(runScenario(Mode.CE_STEPS_RESTART_AFTER_ROLLBACK), true);
  }

  /** Level 1, beyond the CE: two JN restarts after the rollback, nothing held in flight. */
  @Test
  @Timeout(180)
  public void testTwoRestartsAfterRollback() throws Exception {
    expect(runScenario(Mode.TWO_RESTARTS_AFTER_ROLLBACK), true);
  }

  /** The counterexample's literal order: JNRestart(j0) before the rollback. */
  @Test
  @Timeout(180)
  public void testCeLiteralOrder() throws Exception {
    expect(runScenario(Mode.CE_ORDER), false);
  }

  /** Control: j1 answers getJournalState in time. */
  @Test
  @Timeout(180)
  public void testControlReplyInTime() throws Exception {
    expect(runScenario(Mode.CONTROL_REPLY_IN_TIME), false);
  }

  /**
   * Level 0: production QJMs (one IPC thread per JN), no spies, no failpoints. W2 and W3 reach all
   * JNs. After the rollback j0 and j2 restart. A standby tails the shared log, then becomes
   * active as W4. Whether W4's getJournalState quorum excludes the stale j1 is left to the
   * natural race. Report only.
   */
  @Test
  @Timeout(900)
  public void testLevel0NaturalRace() throws Exception {
    int iters = Integer.parseInt(System.getenv().getOrDefault("MC2_L0_ITERS", "20"));
    int fired = 0;
    int epoch2 = 0;
    for (int it = 1; it <= iters; it++) {
      startCluster();
      LogCapturer ipcLog = LogCapturer.captureLogs(Server.LOG);
      try {
        QuorumJournalManager w1 = plainQjm();
        w1.format(FAKE_NSINFO, false);
        w1.recoverUnfinalizedSegments();
        upgrade(w1);
        stop(w1);
        for (long e = 2; e <= 3; e++) {
          QuorumJournalManager w = plainQjm();
          w.recoverUnfinalizedSegments();
          assertEquals(e, w.getLoggerSetForTests().getEpoch());
          stop(w);
        }
        rollback(null);
        cluster.restartJournalNode(0);
        cluster.restartJournalNode(2);
        QuorumJournalManager standby = plainQjm();
        try {
          standby.selectInputStreams(new ArrayList<EditLogInputStream>(), 1, true, false);
        } catch (IOException e) {
          say("L0 iteration %d: standby tailing: %s", it, describe(e));
        }
        stop(standby);
        QuorumJournalManager w4 = plainQjm();
        LogCapturer rpcLog = LogCapturer.captureLogs(ProtobufRpcEngine2.LOG);
        try {
          w4.recoverUnfinalizedSegments();
        } finally {
          rpcLog.stopCapturing();
        }
        long epoch = w4.getLoggerSetForTests().getEpoch();
        say("L0 iteration %d: W4's epoch RPCs as its IPC client saw them:%n%s", it,
            rpcOrder(rpcLog.getOutput()));
        EditLogOutputStream stm = w4.startLogSegment(1,
            NameNodeLayoutVersion.CURRENT_LAYOUT_VERSION);
        boolean f = false;
        if (epoch == 2) {
          epoch2++;
          final String needle = "IPC's epoch 2" + TARGET_MSG + "3";
          try {
            GenericTestUtils.waitFor(() -> ipcLog.getOutput().contains(needle), 50, 3000);
            f = true;
          } catch (java.util.concurrent.TimeoutException e) {
            f = false;
          }
        }
        if (f) {
          fired++;
          say("L0 iteration %d: JN-side trace:%n%s", it, targetTrace(ipcLog.getOutput(), 2));
        }
        say("L0 iteration %d: W4 epoch=%d targetFiredOnJ1=%s", it, epoch, f);
        IOUtils.cleanupWithLogger(LOG, stm);
      } finally {
        ipcLog.stopCapturing();
        stopCluster();
      }
    }
    say("MC2-L0-RESULT iterations=%d w4Epoch2=%d targetFired=%d", iters, epoch2, fired);
  }
}
