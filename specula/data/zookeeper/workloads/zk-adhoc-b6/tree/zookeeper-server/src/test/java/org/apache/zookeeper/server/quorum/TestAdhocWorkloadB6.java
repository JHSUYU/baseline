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
import static org.junit.jupiter.api.Assertions.assertTrue;
import java.io.IOException;
import java.net.SocketAddress;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeSet;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.BooleanSupplier;
import javax.security.sasl.SaslException;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.KeeperException.Code;
import org.apache.zookeeper.PortAssignment;
import org.apache.zookeeper.ZooDefs.Ids;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.common.X509Exception;
import org.apache.zookeeper.server.Request;
import org.apache.zookeeper.server.ZKDatabase;
import org.apache.zookeeper.server.ZooKeeperServer;
import org.apache.zookeeper.server.persistence.FileTxnSnapLog;
import org.apache.zookeeper.test.ClientBase;
import org.apache.zookeeper.txn.CreateTxn;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

/**
 * Three participants, each with an observerMasterPort, and one observer that
 * syncs through a follower F's ObserverMaster. The observer and F stop; a
 * client creates a node whose ACKs the leader holds; F starts again and
 * syncs, logs the create, and the held ACKs are released. The observer then
 * starts again, syncs through F's ObserverMaster, and applies the held create
 * and one more.
 */
public class TestAdhocWorkloadB6 extends QuorumPeerTestBase {

    private static final int PARTICIPANTS = 3;
    private static final int OBSERVER = PARTICIPANTS + 1;

    private final Holds holds = new Holds();
    private final MainThread[] peers = new MainThread[OBSERVER + 1];
    private final int[] clientPorts = new int[OBSERVER + 1];
    private final int[] observerMasterPorts = new int[PARTICIPANTS + 1];

    /** Before QuorumPeerTestBase#tearDown closes the client and shuts the peers down. */
    @AfterEach
    public void releaseHolds() {
        holds.abort();
    }

    @Test
    @Timeout(value = 120)
    public void run() throws Exception {
        ClientBase.setupTestEnv();
        StringBuilder quorumCfg = new StringBuilder();
        for (int sid = 1; sid <= OBSERVER; sid++) {
            clientPorts[sid] = PortAssignment.unique();
            quorumCfg.append(String.format("server.%d=127.0.0.1:%d:%d:%s;127.0.0.1:%d%n", sid,
                PortAssignment.unique(), PortAssignment.unique(), sid <= PARTICIPANTS ? "participant" : "observer",
                clientPorts[sid]));
            if (sid <= PARTICIPANTS) {
                observerMasterPorts[sid] = PortAssignment.unique();
            }
        }
        for (int sid = 1; sid <= PARTICIPANTS; sid++) {
            peers[sid] = holds.participant(sid, clientPorts[sid], quorumCfg.toString(),
                config(observerMasterPorts[sid]));
        }
        servers = new Servers();
        servers.mt = new MainThread[] {peers[1], peers[2], peers[3]};
        for (int sid = 1; sid <= PARTICIPANTS; sid++) {
            peers[sid].start();
        }
        for (int sid = 1; sid <= PARTICIPANTS; sid++) {
            assertTrue(ClientBase.waitForServerUp("127.0.0.1:" + clientPorts[sid], CONNECTION_TIMEOUT),
                "participant " + sid + " did not start");
        }
        int leader = role(true);
        int follower = role(false);

        peers[OBSERVER] = new MainThread(OBSERVER, clientPorts[OBSERVER], PortAssignment.unique(), quorumCfg.toString(),
            config(observerMasterPorts[follower]));
        servers.mt = new MainThread[] {peers[1], peers[2], peers[3], peers[OBSERVER]};
        peers[OBSERVER].start();
        assertTrue(ClientBase.waitForServerUp("127.0.0.1:" + clientPorts[OBSERVER], CONNECTION_TIMEOUT),
            "the observer did not start");

        ZooKeeper client = ClientBase.createZKClient("127.0.0.1:" + clientPorts[leader]);
        servers.zk = new ZooKeeper[] {client};
        client.create("/warm", new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        long warm = database(leader).getDataTreeLastProcessedZxid();
        Holds.await("the observer did not apply the warm-up create", () -> has(OBSERVER, "/warm"));

        stop(OBSERVER);
        stop(follower);

        holds.holdAcksOf("/held");
        CountDownLatch heldDone = new CountDownLatch(1);
        AtomicInteger heldRc = new AtomicInteger(Integer.MIN_VALUE);
        client.create("/held", new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT, (rc, path, ctx, name) -> {
            heldRc.set(rc);
            heldDone.countDown();
        }, null);
        int otherFollower = PARTICIPANTS * (PARTICIPANTS + 1) / 2 - leader - follower;
        holds.awaitAckFrom(leader);
        holds.awaitAckFrom(otherFollower);
        long heldZxid = holds.trackedZxid();
        assertEquals(warm + 1, heldZxid, "the held create should be the next transaction");

        peers[follower].start();
        holds.awaitSync(follower, peers[follower]);
        holds.awaitAckFrom(follower);
        holds.releaseAcks();
        assertTrue(heldDone.await(Holds.WAIT_SECONDS, TimeUnit.SECONDS), "the held create did not finish");
        assertEquals(Code.OK.intValue(), heldRc.get());

        peers[OBSERVER].start();
        try {
            awaitObserverApplies(client, leader, follower, heldZxid);
        } finally {
            // The observer and the handler serving it at F end inside the test.
            List<Thread> serving = handlersOf(OBSERVER);
            peers[OBSERVER].shutdown();
            peers[OBSERVER].join(TimeUnit.SECONDS.toMillis(Holds.WAIT_SECONDS));
            for (Thread handler : serving) {
                handler.join(TimeUnit.SECONDS.toMillis(Holds.WAIT_SECONDS));
            }
        }
        assertTrue(handlersOf(OBSERVER).isEmpty(), "the ObserverMaster handler of the observer did not end");
    }

    /** The observer syncs through F's ObserverMaster, then applies the held create and the follow-up one. */
    private void awaitObserverApplies(ZooKeeper client, int leader, int follower, long heldZxid)
        throws Exception {
        Holds.await("the observer did not sync through the follower's ObserverMaster", () -> {
            QuorumPeer peer = peers[OBSERVER].getQuorumPeer();
            Observer o = peer == null ? null : peer.observer;
            ZooKeeperServer server = peer == null ? null : peer.getActiveServer();
            return o != null && o.getSocket() != null && o.getSocket().getPort() == observerMasterPorts[follower]
                && server != null && server.isRunning();
        });

        client.create("/after", new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        long after = database(leader).getDataTreeLastProcessedZxid();
        assertEquals(heldZxid + 1, after, "the follow-up create should be the next transaction");
        Holds.await("the observer did not apply the held and the follow-up create",
            () -> has(OBSERVER, "/held") && has(OBSERVER, "/after")
                && database(OBSERVER).getmaxCommittedLog() == after);
        assertTrue(peers[OBSERVER].getQuorumPeer().getActiveServer().isRunning(), "the observer stopped serving");
    }

    /** The learner handlers serving server {@code sid} (here F's ObserverMaster's, the observer's only master). */
    private static List<Thread> handlersOf(long sid) {
        Thread[] threads = new Thread[Thread.activeCount() * 2 + 16];
        int count = Thread.enumerate(threads);
        List<Thread> handlers = new ArrayList<>();
        for (int i = 0; i < count; i++) {
            if (threads[i] instanceof LearnerHandler && ((LearnerHandler) threads[i]).getSid() == sid) {
                handlers.add(threads[i]);
            }
        }
        return handlers;
    }

    private static String config(int observerMasterPort) {
        return String.format("observerMasterPort=%d%nsnapCount=100000%nadmin.enableServer=false%n", observerMasterPort);
    }

    /** MainThread#shutdown joins the peer: the server is down when this returns. */
    private void stop(int sid) throws InterruptedException {
        peers[sid].shutdown();
    }

    private ZKDatabase database(int sid) {
        QuorumPeer peer = peers[sid].getQuorumPeer();
        return peer == null ? null : peer.getZkDb();
    }

    private boolean has(int sid, String path) {
        ZKDatabase db = database(sid);
        return db != null && db.getNode(path) != null;
    }

    private int role(boolean leading) throws InterruptedException {
        AtomicInteger found = new AtomicInteger(-1);
        Holds.await(leading ? "no leader" : "no follower with an ObserverMaster", () -> {
            for (int sid = 1; sid <= PARTICIPANTS; sid++) {
                QuorumPeer peer = peers[sid].getQuorumPeer();
                if (peer != null
                    && (leading ? peer.leader != null : peer.follower != null && peer.follower.om != null)) {
                    found.set(sid);
                    return true;
                }
            }
            return false;
        });
        return found.get();
    }

    /**
     * The test's participants: each one's leader can hold the ACKs of one
     * create and pause one follower's startForwarding. Every proposal,
     * commit, queue and zxid is the normal protocol's, and every override
     * waits before it calls the synchronized super, so no lock is held while
     * waiting. The test waits on what the leader sees: a learner's ACK of the
     * tracked create (it logged it) and its ACK of UPTODATE (it synced, or its
     * run ended first). Holds and waits are bounded by {@link #WAIT_SECONDS};
     * the test's own timeout bounds the whole run.
     */
    static final class Holds {

        static final long WAIT_SECONDS = 300;

        private volatile String trackedPath;
        private volatile long trackedZxid = -1;
        private final Map<Long, CountDownLatch> acks = new ConcurrentHashMap<>();
        private final Map<Long, CountDownLatch> held = new ConcurrentHashMap<>();
        private final Map<Long, CountDownLatch> processed = new ConcurrentHashMap<>();
        private volatile boolean holding;
        private volatile CountDownLatch committed = new CountDownLatch(1);
        private final Map<Long, CountDownLatch> synced = new ConcurrentHashMap<>();

        private volatile long pausedSid = -1;
        private final AtomicBoolean pauseTaken = new AtomicBoolean(true);
        private volatile CountDownLatch forwardingPaused = new CountDownLatch(1);
        private volatile CountDownLatch forwardingReleased = new CountDownLatch(0);

        /** A participant whose leader is a {@link HeldLeader} of this object. */
        MainThread participant(int sid, int clientPort, String quorumCfg, String otherCfg) throws IOException {
            return new HeldPeer(sid, clientPort, quorumCfg, otherCfg);
        }

        /** Hold every ACK of the next create of {@code path} until {@link #releaseAcks()}. */
        void holdAcksOf(String path) {
            track(path, true);
        }

        /** Note the ACKs of the next create of {@code path}, holding none. */
        void noteAcksOf(String path) {
            track(path, false);
        }

        private void track(String path, boolean hold) {
            trackedZxid = -1;
            acks.clear();
            held.clear();
            processed.clear();
            committed = new CountDownLatch(1);
            holding = hold;
            trackedPath = path;
        }

        /** Pause the next startForwarding for follower {@code sid} until {@link #releaseForwarding()}. */
        void pauseForwardingOnce(long sid) {
            forwardingPaused = new CountDownLatch(1);
            forwardingReleased = new CountDownLatch(1);
            pausedSid = sid;
            pauseTaken.set(false);
        }

        long trackedZxid() {
            return trackedZxid;
        }

        /** Release the held ACKs one at a time in server id order, each processed before the next. */
        void releaseAcks() throws InterruptedException {
            holding = false;
            for (long sid : new TreeSet<>(held.keySet())) {
                held.get(sid).countDown();
                assertTrue(processed.computeIfAbsent(sid, unprocessed -> new CountDownLatch(1))
                    .await(WAIT_SECONDS, TimeUnit.SECONDS), "the leader did not process server " + sid + "'s ACK");
            }
        }

        void releaseForwarding() {
            forwardingReleased.countDown();
        }

        /** Server {@code sid} logged the tracked create: the leader has its ACK (held or not). */
        void awaitAckFrom(long sid) throws InterruptedException {
            assertTrue(ack(sid).await(WAIT_SECONDS, TimeUnit.SECONDS), "server " + sid + " did not log the create");
        }

        /**
         * Participant {@code sid}, since its last start, finished a sync with the leader: the leader has its
         * ACK of UPTODATE. A run whose server stops before ends the wait at once, and fails it.
         */
        void awaitSync(long sid, MainThread peer) throws InterruptedException {
            assertTrue(synced.get(sid).await(WAIT_SECONDS, TimeUnit.SECONDS), "server " + sid + " did not sync");
            assertTrue(peer.isAlive(), "server " + sid + " stopped before it synced");
        }

        void awaitForwardingPaused() throws InterruptedException {
            assertTrue(forwardingPaused.await(WAIT_SECONDS, TimeUnit.SECONDS), "startForwarding was not reached");
        }

        void awaitCommitted() throws InterruptedException {
            assertTrue(committed.await(WAIT_SECONDS, TimeUnit.SECONDS), "the held create did not commit");
        }

        void abort() {
            releaseForwarding();
            holding = false;
            held.values().forEach(CountDownLatch::countDown);
        }

        static void await(String message, BooleanSupplier condition) throws InterruptedException {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(WAIT_SECONDS);
            while (System.nanoTime() < deadline) {
                if (condition.getAsBoolean()) {
                    return;
                }
                Thread.sleep(20);
            }
            assertTrue(condition.getAsBoolean(), message);
        }

        private CountDownLatch ack(long sid) {
            return acks.computeIfAbsent(sid, unacked -> new CountDownLatch(1));
        }

        private static void hold(CountDownLatch latch, String what) {
            try {
                if (!latch.await(WAIT_SECONDS, TimeUnit.SECONDS)) {
                    throw new IllegalStateException("the test did not release " + what);
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException("interrupted while holding " + what, e);
            }
        }

        private final class HeldPeer extends MainThread {

            private final long sid;
            private volatile CountDownLatch life;

            HeldPeer(int sid, int clientPort, String quorumCfg, String otherCfg) throws IOException {
                super(sid, clientPort, PortAssignment.unique(), quorumCfg, otherCfg);
                this.sid = sid;
            }

            /** Each start is a run whose sync (or end) {@link #awaitSync} waits for. */
            @Override
            public synchronized void start() {
                life = new CountDownLatch(1);
                synced.put(sid, life);
                super.start();
            }

            @Override
            public void run() {
                CountDownLatch mine = life;
                try {
                    super.run();
                } finally {
                    mine.countDown();
                }
            }

            @Override
            public TestQPMain getTestQPMain() {
                return new HeldQPMain();
            }
        }

        private final class HeldQPMain extends TestQPMain {

            @Override
            protected QuorumPeer getQuorumPeer() throws SaslException {
                return new HeldQuorumPeer();
            }
        }

        private final class HeldQuorumPeer extends QuorumPeer {

            HeldQuorumPeer() throws SaslException {
            }

            @Override
            protected Leader makeLeader(FileTxnSnapLog logFactory) throws IOException, X509Exception {
                return new HeldLeader(this, new LeaderZooKeeperServer(logFactory, this, getZkDb()));
            }
        }

        private final class HeldLeader extends Leader {

            HeldLeader(QuorumPeer self, LeaderZooKeeperServer zk) throws IOException, X509Exception {
                super(self, zk);
            }

            @Override
            public Proposal propose(Request request) throws XidRolloverException {
                String path = trackedPath;
                if (path != null && request.getTxn() instanceof CreateTxn
                        && path.equals(((CreateTxn) request.getTxn()).getPath())) {
                    trackedPath = null;
                    trackedZxid = request.zxid;
                }
                return super.propose(request);
            }

            @Override
            public void processAck(long sid, long zxid, SocketAddress followerAddr) {
                if ((zxid & 0xffffffffL) == 0) {
                    CountDownLatch uptodate = synced.get(sid);
                    if (uptodate != null) {
                        uptodate.countDown();
                    }
                } else if (zxid == trackedZxid && holding) {
                    CountDownLatch release = new CountDownLatch(1);
                    held.put(sid, release);
                    ack(sid).countDown();
                    hold(release, "the held ACKs");
                    try {
                        super.processAck(sid, zxid, followerAddr);
                    } finally {
                        processed.computeIfAbsent(sid, unprocessed -> new CountDownLatch(1)).countDown();
                    }
                    return;
                } else if (zxid == trackedZxid) {
                    ack(sid).countDown();
                }
                super.processAck(sid, zxid, followerAddr);
            }

            @Override
            public synchronized boolean tryToCommit(Proposal p, long zxid, SocketAddress followerAddr) {
                boolean done = super.tryToCommit(p, zxid, followerAddr);
                if (done && zxid == trackedZxid) {
                    committed.countDown();
                }
                return done;
            }

            @Override
            public long startForwarding(LearnerHandler handler, long lastSeenZxid) {
                if (handler.getSid() == pausedSid && pauseTaken.compareAndSet(false, true)) {
                    forwardingPaused.countDown();
                    hold(forwardingReleased, "startForwarding");
                }
                return super.startForwarding(handler, lastSeenZxid);
            }
        }
    }
}
