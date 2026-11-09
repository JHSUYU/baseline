/*
 * Specula MC-1 reproduction (hdfs-adhoc-07, target Journal.java:926).
 *
 * Installed by repro/test_bugMC-1_purge_restart.sh as
 *   hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/qjournal/client/TestBugMC1PurgeRestart.java
 *
 * Variant of the workload test TestQuorumJournalManager#testRecoverAfterIncompleteRecovery: same module, same
 * package, same MiniJournalCluster/QJM setup (copied, not modified). It replays the model-checking counterexample
 * spec/output/hunt/gated/purge_guided_b_bfs.out (CE step numbers in the comments):
 *   - faults used, as in the CE: one JournalNode crash + restart (j0), one checkpoint purge, a second writer;
 *   - order is controlled only by delaying when each IPCLoggerChannel starts its next queued RPC task, through
 *     the @VisibleForTesting hook IPCLoggerChannel#createSingleThreadExecutor (the hook SpyQJournalUtil overrides).
 *     A delayed task = a slow link / slow JN. The task body (createReqInfo() + the RPC) is the unmodified code;
 *   - Mockito spies (the SpyQJournalUtil pattern) are used only to observe the futures of purge/acceptRecovery;
 *   - nothing writes the guard's operands; the target method is not touched; no source file is patched.
 * Configuration difference from the workload: ipc.client.connect.max.retries is left at its production default
 * (10 retries, 1000 ms apart); TestQuorumJournalManager#setup sets it to 0 only "to speed up the tests".
 *
 * Tests: the counterexample's order; the same bug with the purge issued after j0's crash and j0's channel never
 * held; and a negative control where the purge reaches j0 before its crash (txn 2 survives).
 *
 * Run it in both JVM assertion modes. The target throw (Journal.java:926) is an explicit throw and fires in both.
 * With -ea (the surefire default) QuorumCall#checkAssertionErrors, which exists only for tests, makes the new
 * writer abort; with assertions off (how Hadoop daemons run) the writer finalizes the shortened segment and the
 * test asserts that the acknowledged txn 2 is gone from the recovered log.
 */
package org.apache.hadoop.hdfs.qjournal.client;

import static org.apache.hadoop.hdfs.qjournal.QJMTestUtil.FAKE_NSINFO;
import static org.apache.hadoop.hdfs.qjournal.QJMTestUtil.JID;
import static org.apache.hadoop.hdfs.qjournal.QJMTestUtil.writeTxns;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import java.io.Closeable;
import java.io.File;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Supplier;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.CommonConfigurationKeysPublic;
import org.apache.hadoop.hdfs.DFSConfigKeys;
import org.apache.hadoop.hdfs.qjournal.MiniJournalCluster;
import org.apache.hadoop.hdfs.server.namenode.EditLogInputStream;
import org.apache.hadoop.hdfs.server.namenode.EditLogOutputStream;
import org.apache.hadoop.hdfs.server.namenode.FSEditLogOp;
import org.apache.hadoop.hdfs.server.namenode.FileJournalManager;
import org.apache.hadoop.hdfs.server.namenode.FileJournalManager.EditLogFile;
import org.apache.hadoop.hdfs.server.namenode.NNStorage;
import org.apache.hadoop.hdfs.server.namenode.NameNodeLayoutVersion;
import org.apache.hadoop.io.IOUtils;
import org.apache.hadoop.ipc.Client;
import org.apache.hadoop.ipc.RemoteException;
import org.apache.hadoop.ipc.Server;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.apache.hadoop.thirdparty.com.google.common.util.concurrent.ListenableFuture;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.mockito.Mockito;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class TestBugMC1PurgeRestart {
  private static final Logger LOG =
      LoggerFactory.getLogger(TestBugMC1PurgeRestart.class);

  /** Hands the gate to the IPCLoggerChannel constructor (createSingleThreadExecutor runs inside it). */
  private static final ThreadLocal<GatedExecutor> NEXT_EXECUTOR = new ThreadLocal<>();

  private MiniJournalCluster cluster;
  private Configuration conf;
  private final List<QuorumJournalManager> toClose = new ArrayList<>();
  private final Map<String, GatedExecutor> gates = new ConcurrentHashMap<>();
  private final ExecutorService bg = Executors.newCachedThreadPool(r -> {
    Thread t = new Thread(r, "mc1-driver");
    t.setDaemon(true);
    return t;
  });

  /**
   * Single-thread FIFO executor, used as an IPCLoggerChannel's "single-thread executor". Each task can be held
   * before it starts (hold/allow/release), which models a slow link or a slow JournalNode. It does not touch
   * what the task does.
   */
  static final class GatedExecutor extends ThreadPoolExecutor {
    private boolean open = true;
    private int permits;
    private int waiting;
    private int completed;

    GatedExecutor(String name) {
      super(1, 1, 0L, TimeUnit.MILLISECONDS, new LinkedBlockingQueue<>(), r -> {
        Thread t = new Thread(r, "Logger channel (gated) " + name);
        t.setDaemon(true);
        return t;
      });
    }

    synchronized void hold() {
      open = false;
      permits = 0;
    }

    synchronized void allow(int n) {
      permits += n;
      notifyAll();
    }

    synchronized void release() {
      open = true;
      notifyAll();
    }

    synchronized int waiting() {
      return waiting;
    }

    synchronized int completed() {
      return completed;
    }

    int queued() {
      return getQueue().size();
    }

    @Override
    protected void beforeExecute(Thread t, Runnable r) {
      synchronized (this) {
        waiting++;
        try {
          while (!open && permits == 0) {
            wait();
          }
          if (!open) {
            permits--;
          }
        } catch (InterruptedException e) {
          Thread.currentThread().interrupt();
        } finally {
          waiting--;
        }
      }
      super.beforeExecute(t, r);
    }

    @Override
    protected void afterExecute(Runnable r, Throwable t) {
      super.afterExecute(r, t);
      synchronized (this) {
        completed++;
      }
    }
  }

  private static volatile String tag = "bug";

  private static void say(String fmt, Object... args) {
    String msg = String.format(fmt, args);
    for (String line : msg.split("\n")) {
      System.out.println("[MC-1][" + tag + "] " + line);
    }
    LOG.info("[MC-1][" + tag + "] " + msg);
  }

  @BeforeEach
  public void setup() throws Exception {
    conf = new Configuration();
    // TestQuorumJournalManager#setup sets this to 0 ("Don't retry connections - it just slows down the tests").
    // Keep the production defaults instead: 10 connect retries, 1000 ms apart.
    conf.setInt(CommonConfigurationKeysPublic.IPC_CLIENT_CONNECT_MAX_RETRIES_KEY,
        CommonConfigurationKeysPublic.IPC_CLIENT_CONNECT_MAX_RETRIES_DEFAULT);
    conf.setInt(CommonConfigurationKeysPublic.IPC_CLIENT_CONNECT_RETRY_INTERVAL_KEY,
        CommonConfigurationKeysPublic.IPC_CLIENT_CONNECT_RETRY_INTERVAL_DEFAULT);
    // As in TestQuorumJournalManager#setup.
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
    for (GatedExecutor g : gates.values()) {
      g.release();
    }
    IOUtils.cleanupWithLogger(LOG, toClose.toArray(new Closeable[0]));
    bg.shutdownNow();
    if (cluster != null) {
      cluster.shutdown();
      cluster = null;
    }
  }

  private int jnIndex(InetSocketAddress addr) {
    for (int i = 0; i < cluster.getNumNodes(); i++) {
      String a = cluster.getJournalNodeIpcAddress(i);
      if (a.endsWith(":" + addr.getPort())) {
        return i;
      }
    }
    throw new IllegalStateException("unknown JN address " + addr);
  }

  private int jnPort(int i) {
    String a = cluster.getJournalNodeIpcAddress(i);
    return Integer.parseInt(a.substring(a.lastIndexOf(':') + 1));
  }

  /** A real QuorumJournalManager whose IPCLoggerChannels run on gated single-thread executors. */
  private QuorumJournalManager createGatedQJM(String writer) throws IOException {
    AsyncLogger.Factory factory = (c, nsInfo, journalId, nameServiceId, addr) -> {
      GatedExecutor ex = new GatedExecutor(writer + "->j" + jnIndex(addr));
      gates.put(writer + "->j" + jnIndex(addr), ex);
      NEXT_EXECUTOR.set(ex);
      try {
        IPCLoggerChannel ch = new IPCLoggerChannel(c, nsInfo, journalId,
            nameServiceId, addr) {
          @Override
          protected ExecutorService createSingleThreadExecutor() {
            return NEXT_EXECUTOR.get();
          }
        };
        return Mockito.spy(ch);
      } finally {
        NEXT_EXECUTOR.remove();
      }
    };
    QuorumJournalManager q = new QuorumJournalManager(conf,
        cluster.getQuorumJournalURI(JID), FAKE_NSINFO, null, factory);
    toClose.add(q);
    return q;
  }

  private GatedExecutor gate(String writer, int jn) {
    return gates.get(writer + "->j" + jn);
  }

  private static void waitFor(Supplier<Boolean> check, String what)
      throws Exception {
    GenericTestUtils.waitFor(check, 20, 30000, "timed out: " + what);
  }

  /** Persisted committed-txid of a JN (read-only; -1 if never written). */
  private long committedTxIdOnDisk(int jn) throws IOException {
    File f = new File(cluster.getCurrentDir(jn, JID), "committed-txid");
    if (!f.exists() || f.length() != 8) {
      return -1;  // never written (INVALID_TXID)
    }
    return ByteBuffer.wrap(Files.readAllBytes(f.toPath())).getLong();
  }

  private String describeSegment1(int jn) throws IOException {
    File dir = cluster.getCurrentDir(jn, JID);
    String[] names = dir.list((d, n) -> n.startsWith("edits_"));
    Arrays.sort(names);
    EditLogFile elf = FileJournalManager.getLogFile(dir, 1);
    String seg = "none";
    if (elf != null) {
      if (elf.isInProgress()) {
        elf.scanLog(Long.MAX_VALUE, false);
      }
      seg = "[" + elf.getFirstTxId() + "," + elf.getLastTxId() + "]"
          + (elf.isInProgress() ? " in-progress" : " finalized");
    }
    long c = committedTxIdOnDisk(jn);
    return String.format("j%d: segment@1=%s committed-txid=%s files=%s", jn,
        seg, c < 0 ? "unset" : Long.toString(c), Arrays.toString(names));
  }

  private void dumpJNs(String when) throws IOException {
    say("JN state %s:", when);
    for (int i = 0; i < cluster.getNumNodes(); i++) {
      say("    %s", describeSegment1(i));
    }
  }

  @SuppressWarnings("unchecked")
  private static <T> ListenableFuture<T> capture(
      org.mockito.invocation.InvocationOnMock inv,
      AtomicReference<ListenableFuture<T>> into) throws Throwable {
    ListenableFuture<T> f = (ListenableFuture<T>) inv.callRealMethod();
    into.set(f);
    return f;
  }

  /** How the purge meets j0's crash and restart. */
  enum Order {
    /** The counterexample's order: purge queued behind txn 2; its task starts after j0 crashed. */
    CE,
    /** Same bug, purge issued after j0 crashed; j0's channel is never held. */
    PURGE_ISSUED_AFTER_CRASH,
    /** Negative control: the purge reaches j0 before j0 crashes. */
    CONTROL
  }

  /** The counterexample: the purge reaches j0 only after j0 restarted. */
  @Test
  @Timeout(300)
  public void testPurgeAfterJNRestartDiscardsCommittedTxn() throws Exception {
    run(Order.CE);
  }

  /**
   * Same bug without holding j0's channel: j0 acks txn 2 and crashes, then the checkpoint purge is issued while
   * the writer still waits for j1's ack. j0's idle channel starts the purge at once (committedTxId=1).
   */
  @Test
  @Timeout(300)
  public void testPurgeIssuedAfterJNCrashDiscardsCommittedTxn() throws Exception {
    run(Order.PURGE_ISSUED_AFTER_CRASH);
  }

  /**
   * Negative control: the same schedule, except that the purge reaches j0 before j0 crashes, while its
   * FileJournalManager still knows the open segment. Nothing is marked stale and txn 2 survives.
   */
  @Test
  @Timeout(300)
  public void testControlPurgeBeforeRestartKeepsCommittedTxn() throws Exception {
    run(Order.CONTROL);
  }

  private void run(Order order) throws Exception {
    tag = order == Order.CE ? "bug" : order == Order.CONTROL ? "control" : "bug-alt";
    LogCapturer ipcClientLog =
        LogCapturer.captureLogs(LoggerFactory.getLogger(Client.class));
    LogCapturer ipcServerLog =
        LogCapturer.captureLogs(LoggerFactory.getLogger(Server.class));
    LogCapturer qjmLog = LogCapturer.captureLogs(
        LoggerFactory.getLogger(QuorumJournalManager.class));
    try {
      scenario(order, ipcClientLog, ipcServerLog, qjmLog);
    } finally {
      ipcClientLog.stopCapturing();
      ipcServerLog.stopCapturing();
      qjmLog.stopCapturing();
    }
  }

  private void scenario(Order order, LogCapturer ipcClientLog,
      LogCapturer ipcServerLog, LogCapturer qjmLog) throws Exception {
    final boolean purgeAfterRestart = order != Order.CONTROL;
    final int j0Port = jnPort(0);
    say("3 JournalNodes: j0=%s j1=%s j2=%s; ipc.client.connect.max.retries=%d interval=%dms",
        cluster.getJournalNodeIpcAddress(0), cluster.getJournalNodeIpcAddress(1),
        cluster.getJournalNodeIpcAddress(2),
        conf.getInt(CommonConfigurationKeysPublic.IPC_CLIENT_CONNECT_MAX_RETRIES_KEY, -1),
        conf.getInt(CommonConfigurationKeysPublic.IPC_CLIENT_CONNECT_RETRY_INTERVAL_KEY, -1));

    // ---------------- writer w1, epoch 1 (CE states 1-26) ----------------
    QuorumJournalManager w1 = createGatedQJM("w1");
    w1.format(FAKE_NSINFO, false);
    w1.recoverUnfinalizedSegments();
    assertEquals(1, w1.getLoggerSetForTests().getEpoch());
    List<AsyncLogger> w1Loggers = w1.getLoggerSetForTests().getLoggersForTests();
    for (AsyncLogger l : w1Loggers) {
      ((IPCLoggerChannel) l).waitForAllPendingCalls();
    }
    // Observe (only) the futures of w1's purge RPCs.
    List<AtomicReference<ListenableFuture<Void>>> purgeFutures = new ArrayList<>();
    for (int i = 0; i < 3; i++) {
      AtomicReference<ListenableFuture<Void>> ref = new AtomicReference<>();
      purgeFutures.add(ref);
      Mockito.doAnswer(inv -> capture(inv, ref)).when(w1Loggers.get(i))
          .purgeLogsOlderThan(Mockito.anyLong());
    }
    GatedExecutor w1j0 = gate("w1", 0);
    GatedExecutor w1j1 = gate("w1", 1);
    GatedExecutor w1j2 = gate("w1", 2);
    say("w1 is the writer, epoch %d", w1.getLoggerSetForTests().getEpoch());

    // j2 lags behind w1: its startLogSegment(1)/journal(txn 1) are delivered late (CE 32-35).
    w1j2.hold();
    EditLogOutputStream stm = w1.startLogSegment(1,
        NameNodeLayoutVersion.CURRENT_LAYOUT_VERSION);         // CE 15-20, quorum {j0,j1}
    writeTxns(stm, 1, 1);                                     // CE 21-26, txn 1 committed on {j0,j1}
    say("CE 15-26: w1 started segment 1 and committed txn 1 on {j0,j1}");
    final int w1j2Base = w1j2.completed();
    w1j2.allow(2);                                            // CE 32-35: late start(1) + journal(txn 1) at j2
    waitFor(() -> w1j2.completed() == w1j2Base + 2, "j2 catches up to txn 1");
    say("CE 32-35: j2 received the late startLogSegment(1) and journal(txn 1) (committedTxId=1)");

    // CE 27: w1 sends txn 2; j1 is slow to answer and j2 is still behind.
    final int w1j0Base = w1j0.completed();
    if (order != Order.PURGE_ISSUED_AFTER_CRASH) {
      w1j0.hold();
    }
    w1j1.hold();
    Future<?> flushTxn2 = bg.submit(() -> {
      writeTxns(stm, 2, 1);
      return null;
    });

    if (order == Order.PURGE_ISSUED_AFTER_CRASH) {
      // j0's channel is not held: txn 2 reaches j0 at once.
      waitFor(() -> w1j0.completed() == w1j0Base + 1 && w1j1.waiting() == 1
          && w1j2.waiting() == 1, "j0 acked txn 2; j1 and j2 pending");
      assertFalse(flushTxn2.isDone(), "txn 2 must not be committed yet");
      dumpJNs("after j0 acked txn 2 (writer has no quorum yet)");
      cluster.getJournalNode(0).stopAndJoin(0);
      say("j0 stopped (crash) right after acking txn 2");
      // The checkpoint purge is issued now, while txn 2 still waits for j1. j0's channel is idle, so its purge
      // task starts at once with the writer's committedTxId (1) and meets the dead JN.
      w1.purgeLogsOlderThan(1);
      waitFor(() -> ipcClientLog.getOutput().contains(
          ":" + j0Port + ". Already tried"), "purge to j0 in IPC connect retry");
      assertFalse(flushTxn2.isDone(), "txn 2 must not be committed yet");
      say("purge(1) issued after j0's crash, before txn 2 committed; IPC client: %s",
          firstLine(ipcClientLog.getOutput(), "Retrying connect to server"));
    } else {
      waitFor(() -> w1j0.waiting() == 1 && w1j1.waiting() == 1
          && w1j2.waiting() == 1, "journal(txn 2) queued on every channel");
      // CE 28: a checkpoint purge is issued while txn 2 waits for its quorum (FSEditLog.logSync flushes outside
      // the FSEditLog lock, so FSEditLog.purgeLogsOlderThan can run meanwhile; minTxIdToKeep <= segment start).
      w1.purgeLogsOlderThan(1);
      waitFor(() -> w1j0.queued() == 1 && w1j1.queued() == 1
          && w1j2.queued() == 1, "purge(1) queued behind txn 2");
      say("CE 27-28: w1 sent txn 2 and purgeLogsOlderThan(1) is queued behind it on every channel");

      // CE 30,33: j0 receives txn 2 and acks it.
      w1j0.allow(1);
      waitFor(() -> w1j0.completed() == w1j0Base + 1 && w1j0.waiting() == 1,
          "j0 acked txn 2");
      assertFalse(flushTxn2.isDone(), "txn 2 must not be committed yet");
      dumpJNs("after j0 acked txn 2 (writer has no quorum yet)");

      if (order == Order.CONTROL) {
        // Control only: the purge (also bound with committedTxId=1) reaches j0 while j0 is still up.
        w1j0.allow(1);
        waitFor(() -> w1j0.completed() == w1j0Base + 2, "purge applied on live j0");
        assertNull(getQuietly(purgeFutures.get(0).get()), "purge on j0");
        say("control: purge(1) applied on j0 before its crash");
      }

      // CE 37: j0 crashes right after acking txn 2.
      cluster.getJournalNode(0).stopAndJoin(0);
      say("CE 37: j0 stopped (crash)");

      if (order == Order.CE) {
        // CE 38: the purge task to j0 starts now. Its RequestInfo is bound with the writer's committedTxId,
        // still 1; the RPC meets a dead JN and stays in the IPC client's connect-retry loop.
        w1j0.allow(1);
        waitFor(() -> ipcClientLog.getOutput().contains(
            ":" + j0Port + ". Already tried"), "purge to j0 in IPC connect retry");
        assertFalse(flushTxn2.isDone(), "txn 2 must not be committed yet");
        say("CE 38: purge(1) to j0 started before txn 2 committed; IPC client: %s",
            firstLine(ipcClientLog.getOutput(), "Retrying connect to server"));
      }
    }

    // CE 31,36,39: j1 receives txn 2 and acks; w1 sees the quorum {j0,j1}: txn 2 is committed.
    final int w1j1Base = w1j1.completed();
    w1j1.allow(1);
    flushTxn2.get(60, TimeUnit.SECONDS);
    say("CE 39: w1's flush of txn 2 returned: txn 2 is acknowledged (quorum {j0,j1})");

    // CE 40-41: the purge to j1 starts after the commit and carries committedTxId=2.
    w1j1.allow(1);
    waitFor(() -> w1j1.completed() == w1j1Base + 2, "purge applied on j1");
    assertNull(getQuietly(purgeFutures.get(1).get()), "purge on j1");
    say("CE 40-41: purge(1) applied on j1 (carried committedTxId=2)");

    // CE 42: j0 restarts on the same RPC port (in the bug run, while the purge to it is still retrying).
    cluster.restartJournalNode(0);
    say("CE 42: j0 restarted");

    File j0Cur = cluster.getCurrentDir(0, JID);
    if (purgeAfterRestart) {
      // CE 47: the retried purge (committedTxId=1) lands on j0's fresh Journal, whose
      // FileJournalManager.currentInProgress is null.
      waitFor(() -> w1j0.completed() == w1j0Base + 2, "purge to j0 finished");
      assertNull(getQuietly(purgeFutures.get(0).get()), "purge on j0");
      int retries = countOccurrences(ipcClientLog.getOutput(),
          ":" + j0Port + ". Already tried");
      assertTrue(new File(j0Cur, NNStorage.getInProgressEditsFileName(1) + ".stale").exists(),
          "j0's open segment was renamed .stale");
      assertFalse(new File(j0Cur, NNStorage.getInProgressEditsFileName(1)).exists());
      say("CE 47: purge(1) delivered to the restarted j0 after %d connect retries;"
          + " j0's open segment was renamed to %s.stale", retries,
          NNStorage.getInProgressEditsFileName(1));
    } else {
      assertTrue(new File(j0Cur, NNStorage.getInProgressEditsFileName(1)).exists());
      assertFalse(new File(j0Cur, NNStorage.getInProgressEditsFileName(1) + ".stale").exists());
      say("control: j0 still has %s after its restart", NNStorage.getInProgressEditsFileName(1));
    }
    dumpJNs("before failover (w1 sends nothing more)");
    assertEquals(1, committedTxIdOnDisk(0));
    assertEquals(2, committedTxIdOnDisk(1));
    assertEquals(1, committedTxIdOnDisk(2));

    // ---------------- writer w2 (failover), CE 43-68: j1 is slow towards w2 ----------------
    QuorumJournalManager w2 = createGatedQJM("w2");
    List<AsyncLogger> w2Loggers = w2.getLoggerSetForTests().getLoggersForTests();
    AtomicReference<ListenableFuture<Void>> j1Accept = new AtomicReference<>();
    Mockito.doAnswer(inv -> capture(inv, j1Accept)).when(w2Loggers.get(1))
        .acceptRecovery(Mockito.any(), Mockito.any());
    GatedExecutor w2j0 = gate("w2", 0);
    GatedExecutor w2j1 = gate("w2", 1);
    GatedExecutor w2j2 = gate("w2", 2);
    w2j1.hold();                 // j1 answers w2 late
    w2j0.hold();
    w2j0.allow(3);               // getJournalState, newEpoch(2), prepareRecovery(1)
    w2j2.hold();
    w2j2.allow(3);
    qjmLog.clearOutput();
    Future<?> recovery = bg.submit(() -> {
      w2.recoverUnfinalizedSegments();
      return null;
    });
    waitFor(() -> w2j0.completed() == 3 && w2j0.waiting() == 1
        && w2j2.completed() == 3 && w2j2.waiting() == 1
        && j1Accept.get() != null, "w2 decided and sent acceptRecovery");
    say("CE 43-65: w2 (epoch %d) recovered with quorum {j0,j2}; QJM log:",
        w2.getLoggerSetForTests().getEpoch());
    for (String l : qjmLog.getOutput().split("\n")) {
      if (l.contains("Recovery prepare phase") || l.contains("prepareRecovery")
          || l.contains("lastCommittedTxId") || l.contains("Using longest log")
          || l.contains("segmentState") || l.contains("lastWriterEpoch")) {
        say("    %s", l.trim());
      }
    }

    // CE 55-68: j1 now handles w2's getJournalState, newEpoch(2), prepareRecovery(1) (too late for the decision)
    // and acceptRecovery([1,1]).
    w2j1.release();
    if (!purgeAfterRestart) {
      j1Accept.get().get(60, TimeUnit.SECONDS);
      assertFalse(ipcServerLog.getOutput().contains("java.lang.AssertionError"));
      say("control: acceptRecovery on j1 succeeded; no AssertionError on any JN");
      w2j0.release();
      w2j2.release();
      recovery.get(120, TimeUnit.SECONDS);
      dumpJNs("after w2's recovery");
      List<Long> txids = readQuorumLog();
      say("edits readable from the quorum after failover (selectInputStreams from txid 1): %s", txids);
      assertEquals(Arrays.asList(1L, 2L), txids);
      say("RESULT(control): txn 2 survives when the purge reaches j0 before its restart");
      return;
    }
    Throwable cause = null;
    try {
      j1Accept.get().get(60, TimeUnit.SECONDS);
      fail("acceptRecovery([1,1]) on j1 unexpectedly succeeded");
    } catch (ExecutionException ee) {
      cause = ee.getCause();
    }
    assertNotNull(cause);
    assertTrue(cause instanceof RemoteException, "unexpected " + cause);
    RemoteException re = (RemoteException) cause;
    say("CE 68: acceptRecovery([1,1]) on j1 failed with remote %s", re.getClassName());
    String[] remote = re.getMessage().split("\n");
    for (int i = 0; i < Math.min(remote.length, 8); i++) {
      say("    %s", remote[i]);
    }
    assertEquals(AssertionError.class.getName(), re.getClassName());
    assertTrue(re.getMessage().contains("would discard already-committed txn 2"));
    assertTrue(re.getMessage().contains(
        "at org.apache.hadoop.hdfs.qjournal.server.Journal.acceptRecovery(Journal.java:"));
    waitFor(() -> ipcServerLog.getOutput().contains("java.lang.AssertionError"),
        "JN j1 IPC server logs the AssertionError");
    say("JN j1 IPC server log:");
    for (String l : excerpt(ipcServerLog.getOutput(), "java.lang.AssertionError", 6)) {
      say("    %s", l);
    }

    // Beyond the CE: acceptRecovery and finalize go to j0 and j2 (a majority).
    boolean qcAsserts = QuorumCall.class.desiredAssertionStatus();
    say("Java assertions enabled for QuorumCall in this JVM: %s", qcAsserts);
    w2j0.release();
    w2j2.release();
    if (qcAsserts) {
      // Test JVMs run with -ea. QuorumCall#checkAssertionErrors runs only then ("in the context of test cases we'd
      // like to actually fail the test case instead of continuing through") and rethrows j1's remote
      // AssertionError although a majority can still answer. Production JVMs run without -ea: see the -da run.
      try {
        recovery.get(120, TimeUnit.SECONDS);
        fail("with -ea, QuorumCall should rethrow j1's remote AssertionError");
      } catch (ExecutionException ee) {
        assertTrue(ee.getCause() instanceof AssertionError, "unexpected " + ee.getCause());
        say("-ea only: w2.recoverUnfinalizedSegments() aborted by QuorumCall.checkAssertionErrors: %s",
            ee.getCause().toString().split("\n")[0]);
      }
      say("RESULT(-ea): Journal.acceptRecovery threw AssertionError on j1 (target reached);"
          + " the writer stopped only because of the test-only -ea check");
      return;
    }
    recovery.get(120, TimeUnit.SECONDS);
    say("w2.recoverUnfinalizedSegments() returned normally (j1's failure was a minority)");
    dumpJNs("after w2's recovery");

    // Consequence: the log readable from the quorum ends at txn 1; txn 2, acknowledged to w1, is lost.
    List<Long> txids = readQuorumLog();
    say("edits readable from the quorum after failover (selectInputStreams from txid 1): %s", txids);
    assertEquals(Arrays.asList(1L), txids,
        "acknowledged txn 2 should be missing from the recovered log");
    say("RESULT: committed txn 2 was acknowledged to w1 but the recovered log is [1,1];"
        + " Journal.acceptRecovery threw AssertionError on j1 only");
  }

  /** What a reader (e.g. a NameNode loading or tailing edits) gets from the quorum, from txid 1. */
  private List<Long> readQuorumLog() throws IOException {
    QuorumJournalManager reader = new QuorumJournalManager(conf,
        cluster.getQuorumJournalURI(JID), FAKE_NSINFO);
    toClose.add(reader);
    List<EditLogInputStream> streams = new ArrayList<>();
    reader.selectInputStreams(streams, 1, false);
    List<Long> txids = new ArrayList<>();
    try {
      for (EditLogInputStream s : streams) {
        FSEditLogOp op;
        while ((op = s.readOp()) != null) {
          txids.add(op.getTransactionId());
        }
      }
    } finally {
      IOUtils.cleanupWithLogger(LOG, streams.toArray(new Closeable[0]));
    }
    return txids;
  }

  private static Object getQuietly(ListenableFuture<Void> f) throws Exception {
    assertNotNull(f);
    return f.get(60, TimeUnit.SECONDS);
  }

  private static String firstLine(String text, String needle) {
    for (String l : text.split("\n")) {
      if (l.contains(needle)) {
        return l.trim();
      }
    }
    return "";
  }

  private static int countOccurrences(String text, String needle) {
    int n = 0;
    for (int i = text.indexOf(needle); i >= 0; i = text.indexOf(needle, i + 1)) {
      n++;
    }
    return n;
  }

  private static List<String> excerpt(String text, String needle, int after) {
    String[] lines = text.split("\n");
    List<String> out = new ArrayList<>();
    for (int i = 0; i < lines.length; i++) {
      if (lines[i].contains(needle)) {
        if (i > 0) {
          out.add(lines[i - 1].trim());
        }
        for (int j = i; j < Math.min(lines.length, i + after + 1); j++) {
          out.add(lines[j].trim());
        }
        break;
      }
    }
    return out;
  }
}
