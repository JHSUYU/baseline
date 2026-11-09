/*
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

package org.apache.zookeeper.server.quorum;

import static org.apache.zookeeper.test.ClientBase.CONNECTION_TIMEOUT;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.List;
import java.util.Random;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeUnit;
import javax.security.sasl.SaslException;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.PortAssignment;
import org.apache.zookeeper.ZooDefs.Ids;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.common.AtomicFileOutputStream;
import org.apache.zookeeper.server.ZKDatabase;
import org.apache.zookeeper.server.persistence.FileTxnLog;
import org.apache.zookeeper.server.persistence.FileTxnSnapLog;
import org.apache.zookeeper.server.persistence.TxnLog.TxnIterator;
import org.apache.zookeeper.test.ClientBase;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

/**
 * MC-3: variant of CurrentEpochWriteFailureTest (same base class, MainThread start/stop and
 * writeSomeData). Nothing here writes the guard's operands: the epoch files, the txn log and
 * the data directories are only read. Disk changes come from the servers' own code.
 */
public class SpeculaAdhocMC3Test extends QuorumPeerTestBase {

    private static final int SERVER_COUNT = 3;
    private final int[] clientPorts = new int[SERVER_COUNT];
    private final MainThread[] mt = new MainThread[SERVER_COUNT];
    private final List<ZooKeeper> clients = new ArrayList<>();
    private volatile boolean loadRunning;
    private final List<Thread> writers = new ArrayList<>();

    private static void say(String s) {
        System.out.println("MC3| " + s);
        System.out.flush();
    }

    private String quorumConfig() {
        StringBuilder sb = new StringBuilder("admin.enableServer=false\n");
        for (int i = 0; i < SERVER_COUNT; i++) {
            clientPorts[i] = PortAssignment.unique();
            sb.append("server." + i + "=127.0.0.1:" + PortAssignment.unique() + ":"
                      + PortAssignment.unique() + ":participant;127.0.0.1:" + clientPorts[i] + "\n");
        }
        return sb.toString();
    }

    private void waitUp(int i) {
        assertTrue(ClientBase.waitForServerUp("127.0.0.1:" + clientPorts[i], CONNECTION_TIMEOUT),
            "waiting for server " + i + " being up");
    }

    private ZooKeeper client(int server) throws Exception {
        ZooKeeper zk = ClientBase.createZKClient("127.0.0.1:" + clientPorts[server]);
        clients.add(zk);
        return zk;
    }

    // The workload's writeSomeData
    private String writeSomeData(ZooKeeper zk) throws Exception {
        String path = "/somePath" + System.nanoTime();
        String data = "someData";
        zk.create(path, data.getBytes(), Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        assertEquals(data, new String(zk.getData(path, false, null)));
        return path;
    }

    private void preload(ZooKeeper zk, int nodes, int size) throws Exception {
        zk.create("/mc3", new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        byte[] data = new byte[size];
        Semaphore window = new Semaphore(500);
        for (int i = 0; i < nodes; i++) {
            window.acquire();
            zk.create("/mc3/n" + i, data, Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT,
                (rc, path, ctx, name) -> window.release(), null);
        }
        window.acquire(500);
    }

    /** Client write load through the public async API, for Level 0. */
    private void startLoad(int threads, int nodes) throws Exception {
        loadRunning = true;
        for (int t = 0; t < threads; t++) {
            ZooKeeper zk = client(t % 2);
            final int seed = t;
            Thread w = new Thread(() -> {
                Semaphore window = new Semaphore(256);
                Random r = new Random(seed);
                byte[] data = new byte[64];
                try {
                    while (loadRunning) {
                        window.acquire();
                        zk.setData("/mc3/n" + r.nextInt(nodes), data, -1,
                            (rc, path, ctx, stat) -> window.release(), null);
                    }
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }, "mc3-load-" + t);
            w.setDaemon(true);
            w.start();
            writers.add(w);
        }
    }

    // Inert in the unmodified tree: only the instrumented worktree's SpeculaTrace reads it
    @BeforeAll
    public static void enableTrace() {
        File trace = new File("target/surefire-reports/mc3-trace.ndjson");
        trace.delete();
        System.setProperty("specula.trace.file", trace.getAbsolutePath());
    }

    @AfterEach
    public void cleanUp() throws Exception {
        loadRunning = false;
        for (Thread w : writers) {
            w.join(5000);
        }
        for (ZooKeeper zk : clients) {
            zk.close();
        }
        for (MainThread t : mt) {
            if (t != null) {
                t.shutdown();
            }
        }
    }

    // ---- observation: what start() threw. It never changes behavior.

    static class Recorder {
        final CountDownLatch finished = new CountDownLatch(1);
        volatile RuntimeException failure;
    }

    /** Timing only: every override calls through and leaves the packet and the state alone. */
    static class Order {
        final CountDownLatch snapRead = new CountDownLatch(1);
        final CountDownLatch releaseSnap = new CountDownLatch(1);
        final CountDownLatch proposalSeen = new CountDownLatch(1);
        final CountDownLatch syncDone = new CountDownLatch(1);
        final List<String> seen = new CopyOnWriteArrayList<>();
    }

    static class TestPeer extends QuorumPeer {
        private final Recorder recorder;
        private final Order order;

        TestPeer(Recorder recorder, Order order) throws SaslException {
            this.recorder = recorder;
            this.order = order;
        }

        @Override
        public synchronized void start() {
            try {
                super.start();
            } catch (RuntimeException e) {
                recorder.failure = e;
                throw e;
            } finally {
                recorder.finished.countDown();
            }
        }

        @Override
        protected Follower makeFollower(FileTxnSnapLog logFactory) throws IOException {
            if (order == null) {
                return super.makeFollower(logFactory);
            }
            return new Follower(this, new FollowerZooKeeperServer(logFactory, this, this.getZkDb())) {
                @Override
                void readPacket(QuorumPacket pp) throws IOException {
                    super.readPacket(pp);
                    order.seen.add(Leader.getPacketType(pp.getType()));
                    try {
                        if (pp.getType() == Leader.SNAP) {
                            // Hold off reading the snapshot: the leader's serialization stays
                            // blocked on the socket, so NEWLEADER is not queued yet (CE S25-S26)
                            order.snapRead.countDown();
                            order.releaseSnap.await(60, TimeUnit.SECONDS);
                        } else if (pp.getType() == Leader.PROPOSAL && order.proposalSeen.getCount() > 0) {
                            // The packet is in hand; the stop lands before the next loop check (CE S28-S29)
                            order.proposalSeen.countDown();
                            while (TestPeer.this.isRunning()) {
                                Thread.sleep(1);
                            }
                        }
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                    }
                }

                @Override
                protected void syncWithLeader(long newLeaderZxid) throws Exception {
                    try {
                        super.syncWithLeader(newLeaderZxid);
                    } finally {
                        order.syncDone.countDown();
                    }
                }

                @Override
                public void shutdown() {
                    // Delay only: the stopping thread is slow to reach closeSocket (CE S30-S31 before S32)
                    try {
                        order.syncDone.await(30, TimeUnit.SECONDS);
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                    }
                    super.shutdown();
                }
            };
        }
    }

    private static class Peer2 {
        volatile Recorder recorder = new Recorder();
        volatile Order order;
    }

    private MainThread newPeer2(String config, Peer2 p) throws IOException {
        return new MainThread(2, clientPorts[2], config, false) {
            @Override
            public TestQPMain getTestQPMain() {
                return new TestQPMain() {
                    @Override
                    protected QuorumPeer getQuorumPeer() throws SaslException {
                        return new TestPeer(p.recorder, p.order);
                    }
                };
            }
        };
    }

    // ---- read-only disk inspection

    private static class Disk {
        long currentEpoch;
        long acceptedEpoch;
        boolean tmp;
        List<String> zxids = new ArrayList<>();

        public String toString() {
            return "currentEpoch=" + currentEpoch + " acceptedEpoch=" + acceptedEpoch
                   + " currentEpoch.tmp exists=" + tmp + " txnLog count=" + zxids.size()
                   + (zxids.isEmpty() ? "" : " first=" + zxids.get(0) + " last=" + zxids.get(zxids.size() - 1));
        }
    }

    private static long readLong(File f) throws IOException {
        return Long.parseLong(new String(Files.readAllBytes(f.toPath())).trim());
    }

    private static Disk readDisk(File snapDir, File logDir) throws IOException {
        Disk d = new Disk();
        d.currentEpoch = readLong(new File(snapDir, QuorumPeer.CURRENT_EPOCH_FILENAME));
        d.acceptedEpoch = readLong(new File(snapDir, QuorumPeer.ACCEPTED_EPOCH_FILENAME));
        d.tmp = new File(snapDir, QuorumPeer.CURRENT_EPOCH_FILENAME + AtomicFileOutputStream.TMP_EXTENSION).exists();
        File[] logs = logDir.listFiles((dir, name) -> name.startsWith("log."));
        if (logs != null && logs.length > 0) {
            FileTxnLog log = new FileTxnLog(logDir);
            try (TxnIterator it = log.read(0)) {
                while (it.getHeader() != null) {
                    d.zxids.add("0x" + Long.toHexString(it.getHeader().getZxid()));
                    if (!it.next()) {
                        break;
                    }
                }
            } finally {
                log.close();
            }
        }
        return d;
    }

    // ---- the oracle

    private void assertTargetThrown(Recorder r) {
        RuntimeException e = r.failure;
        assertNotNull(e, "start() must have failed");
        Throwable c = e.getCause();
        assertTrue(c instanceof IOException, "cause must be IOException, got " + c);
        StackTraceElement top = c.getStackTrace()[0];
        say("start() threw: " + e);
        say("  cause: " + c);
        for (int i = 0; i < Math.min(4, c.getStackTrace().length); i++) {
            say("    at " + c.getStackTrace()[i]);
        }
        assertEquals(QuorumPeer.class.getName(), top.getClassName());
        assertEquals("loadDataBase", top.getMethodName());
        assertEquals("QuorumPeer.java", top.getFileName());
        // The statement "throw new IOException(" starts at 1236; javac attributes the constructor
        // call, which is what fills in the stack trace, to its argument at 1237.
        assertTrue(top.getLineNumber() >= 1236 && top.getLineNumber() <= 1238, "frame " + top);
        assertTrue(c.getMessage().startsWith("The current epoch, "), c.getMessage());
        say("TARGET FIRED: java.io.IOException from " + top);
    }

    /** Restarts peer 2 on its own data directory and returns what start() did. */
    private Recorder restart(Peer2 p) throws Exception {
        p.order = null;
        Recorder r = new Recorder();
        p.recorder = r;
        mt[2].start();
        assertTrue(r.finished.await(60, TimeUnit.SECONDS), "start() must return");
        if (r.failure != null) {
            // NIOServerCnxnFactory.configure bound the client port before start() failed. A process
            // would exit here; in this JVM the failed peer's own shutdown releases it for the next try.
            mt[2].getQuorumPeer().shutdown();
        }
        return r;
    }

    private void startQuorumOfTwo(String config) {
        try {
            mt[0] = new MainThread(0, clientPorts[0], config, false);
            mt[1] = new MainThread(1, clientPorts[1], config, false);
        } catch (IOException e) {
            throw new RuntimeException(e);
        }
        mt[0].start();
        mt[1].start();
        waitUp(0);
        waitUp(1);
    }

    /*
     * Level 0: public operations only. Peer 2 is a fresh server joining while clients write, and
     * MainThread.shutdown (QuorumBase.shutdown -> QuorumPeer.shutdown) lands at a random point
     * near the end of the snapshot transfer. No Follower hook, no delay in the stop path.
     */
    @Test
    @Timeout(value = 480)
    public void testLevel0NaturalRace() throws Exception {
        final int nodes = 20000;
        final long budgetMs = TimeUnit.SECONDS.toMillis(Integer.getInteger("mc3.budgetSec", 150));
        String config = quorumConfig();
        startQuorumOfTwo(config);
        ZooKeeper zk = client(0);
        writeSomeData(zk);
        preload(zk, nodes, 512);
        say("preloaded " + nodes + " nodes");
        startLoad(4, nodes);

        Random rnd = new Random(0x4d43L);
        long burstNanos = 0;
        int trial = 0;
        int loggedNoEpoch = 0;
        int noLog = 0;
        int epochWritten = 0;
        int stuck = 0;
        long start = System.currentTimeMillis();
        int fired = 0;

        while (System.currentTimeMillis() - start < budgetMs) {
            trial++;
            boolean calibrate = trial <= 3;
            Peer2 p = new Peer2();
            mt[2] = newPeer2(config, p);
            mt[2].start();
            int expected = mt[0].getQuorumPeer().getZkDb().getNodeCount();
            QuorumPeer qp = null;
            long deadline = System.currentTimeMillis() + 30000;
            boolean reached = false;
            while (System.currentTimeMillis() < deadline) {
                qp = mt[2].getQuorumPeer();
                ZKDatabase db = qp == null ? null : qp.getZkDb();
                if (db != null && qp.getSyncMode() == QuorumPeer.SyncMode.SNAP && db.getNodeCount() >= expected) {
                    reached = true;
                    break;
                }
            }
            if (!reached) {
                say("trial " + trial + ": snapshot end not observed, skipping");
                mt[2].shutdown();
                mt[2].deleteBaseDir();
                continue;
            }
            File snapDir = qp.getTxnFactory().getSnapDir();
            File logDir = qp.getTxnFactory().getDataLogDir();
            if (calibrate) {
                // No stop: how long from the snapshot's end to NEWLEADER's epoch write
                long t0 = System.nanoTime();
                while (qp.getCurrentEpoch() != 1 && System.nanoTime() - t0 < TimeUnit.SECONDS.toNanos(10)) {
                    Thread.yield();
                }
                burstNanos = Math.max(burstNanos, System.nanoTime() - t0);
                say("calibration " + trial + ": snapshot end to epoch write took "
                    + (System.nanoTime() - t0) / 1000 + "us");
                mt[2].shutdown();
                mt[2].deleteBaseDir();
                continue;
            }
            long delay = (long) (rnd.nextDouble() * burstNanos);
            long t0 = System.nanoTime();
            while (System.nanoTime() - t0 < delay) {
                Thread.yield();
            }
            try {
                mt[2].shutdown();
            } catch (Throwable t) {
                stuck++;
                say("trial " + trial + ": shutdown problem " + t);
            }
            // Let the peer's own threads finish before reading the disk
            mt[2].join(5000);
            Disk d = readDisk(snapDir, logDir);
            boolean candidate = d.currentEpoch == 0 && !d.zxids.isEmpty();
            if (d.currentEpoch != 0) {
                epochWritten++;
            } else if (d.zxids.isEmpty()) {
                noLog++;
            } else {
                loggedNoEpoch++;
            }
            if (candidate) {
                say("trial " + trial + ": delay=" + delay / 1000 + "us disk: " + d);
                Recorder r = restart(p);
                if (r.failure != null) {
                    assertTargetThrown(r);
                    fired++;
                    if (fired == 1) {
                        Recorder again = restart(p);
                        say("second restart on the same data dir:");
                        assertTargetThrown(again);
                        say("after failed restarts disk: " + readDisk(snapDir, logDir));
                    }
                    mt[2].deleteBaseDir();
                    continue;
                }
                say("trial " + trial + ": restart succeeded");
                mt[2].shutdown();
            }
            mt[2].deleteBaseDir();
        }
        say("LEVEL0 SUMMARY trials=" + trial + " (3 calibration) epochWritten=" + epochWritten
            + " noTxnLoggedNoEpoch=" + noLog + " txnLoggedNoEpoch=" + loggedNoEpoch + " stopProblems=" + stuck
            + " burstNanos=" + burstNanos + " targetFired=" + fired
            + " wallMs=" + (System.currentTimeMillis() - start));
    }

    /*
     * Level 1: the counterexample's order, realized with the readPacket/makeFollower overrides the
     * codebase's tests already use (DIFFSyncConsistencyTest). Timing only: no state is written.
     *   S20-S25 peer 2 joins a running quorum and reads SNAP
     *   S26     a client write: the leader queues PROPOSAL for peer 2, ahead of NEWLEADER
     *   S28     peer 2 reads the PROPOSAL in the sync loop
     *   S29     QuorumPeer.shutdown sets running = false
     *   S30-S31 the loop ends, the post-loop code logs the proposal
     *   S32     the stop finishes
     *   S33-S34 restart, loadDataBase
     */
    @Test
    @Timeout(value = 240)
    public void testLevel1CounterexampleOrder() throws Exception {
        String config = quorumConfig();
        startQuorumOfTwo(config);
        ZooKeeper zk = client(0);
        writeSomeData(zk);
        // More than the socket buffers hold, so the serialization is still blocked at S26
        preload(zk, 3000, 10240);

        Peer2 p = new Peer2();
        Order order = new Order();
        p.order = order;
        mt[2] = newPeer2(config, p);
        mt[2].start();
        assertTrue(order.snapRead.await(60, TimeUnit.SECONDS), "peer 2 must read SNAP");
        say("peer 2 read SNAP, syncMode=" + mt[2].getQuorumPeer().getSyncMode());

        String forwarded = writeSomeData(zk);
        say("client write committed by peers 0,1 during the sync: " + forwarded);
        order.releaseSnap.countDown();
        assertTrue(order.proposalSeen.await(60, TimeUnit.SECONDS), "peer 2 must read a PROPOSAL");
        QuorumPeer qp = mt[2].getQuorumPeer();
        File snapDir = qp.getTxnFactory().getSnapDir();
        File logDir = qp.getTxnFactory().getDataLogDir();
        say("before the stop: packets read=" + order.seen + " " + readDisk(snapDir, logDir));

        mt[2].shutdown();
        mt[2].join(5000);
        say("packets read in the sync: " + order.seen);
        assertFalse(order.seen.contains("NEWLEADER"), "the loop must have ended before NEWLEADER");
        Disk d = readDisk(snapDir, logDir);
        say("after the stop: " + d);

        Recorder first = restart(p);
        assertTargetThrown(first);
        Recorder second = restart(p);
        say("second restart on the same data dir:");
        assertTargetThrown(second);
        say("after failed restarts: " + readDisk(snapDir, logDir));

        assertTrue(ClientBase.waitForServerDown("127.0.0.1:" + clientPorts[2], CONNECTION_TIMEOUT));
        say("peer 2 is down; peers 0,1 still serve: " + writeSomeData(zk));
    }

    /*
     * Control: same workload, same joiner, no stop in the sync. The epoch write happens and the
     * peer restarts cleanly, so the failure above comes from the stop landing in the loop.
     */
    @Test
    @Timeout(value = 240)
    public void testControlStopAfterSync() throws Exception {
        String config = quorumConfig();
        startQuorumOfTwo(config);
        ZooKeeper zk = client(0);
        writeSomeData(zk);
        preload(zk, 3000, 10240);

        Peer2 p = new Peer2();
        mt[2] = newPeer2(config, p);
        mt[2].start();
        waitUp(2);
        writeSomeData(zk);
        QuorumPeer qp = mt[2].getQuorumPeer();
        File snapDir = qp.getTxnFactory().getSnapDir();
        File logDir = qp.getTxnFactory().getDataLogDir();
        mt[2].shutdown();
        mt[2].join(5000);
        Disk d = readDisk(snapDir, logDir);
        say("control after the stop: " + d);
        assertEquals(1, d.currentEpoch);

        Recorder r = restart(p);
        assertEquals(null, r.failure, "control restart must not fail");
        waitUp(2);
        say("control restart OK, peer 2 serving, currentEpoch=" + mt[2].getQuorumPeer().getCurrentEpoch());
    }

}
