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
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.KeeperException.Code;
import org.apache.zookeeper.PortAssignment;
import org.apache.zookeeper.ZooDefs.Ids;
import org.apache.zookeeper.ZooKeeper;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.classic.spi.ThrowableProxy;
import ch.qos.logback.core.AppenderBase;
import org.apache.zookeeper.server.ZKDatabase;
import org.apache.zookeeper.server.ZooKeeperCriticalThread;
import org.slf4j.LoggerFactory;
import org.apache.zookeeper.server.ZooKeeperServer;
import org.apache.zookeeper.test.ClientBase;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

/**
 * Reproduces a gap in the transactions an ObserverMaster forwards.
 *
 * Same cluster as {@link TestAdhocWorkloadB6}: three participants with an
 * observerMasterPort and one observer that syncs through follower F's
 * ObserverMaster. The observer and F stop; a client creates /held, whose ACKs
 * the leader holds (a slow quorum). F restarts and syncs with the leader;
 * the leader sends F the outstanding /held PROPOSAL during the sync, before
 * F's ObserverMaster exists. The observer restarts and syncs through F's new
 * ObserverMaster while /held is still uncommitted. Then the ACKs are released:
 * /held commits, but F's ObserverMaster never saw its PROPOSAL, so it drops
 * the COMMIT ("ignore missing proposal packet") and forwards nothing. The
 * next create, /after, is forwarded as an INFORM, and the observer applies
 * warm+2 directly after warm: ZKDatabase.addCommittedProposal throws
 * IllegalStateException ("Committed proposal cached out of order").
 */
public class TestAdhocWorkloadB6Repro extends QuorumPeerTestBase {

    private static final int PARTICIPANTS = 3;
    private static final int OBSERVER = PARTICIPANTS + 1;

    private final TestAdhocWorkloadB6.Holds holds = new TestAdhocWorkloadB6.Holds();
    private final MainThread[] peers = new MainThread[OBSERVER + 1];
    private final int[] clientPorts = new int[OBSERVER + 1];
    private final int[] observerMasterPorts = new int[PARTICIPANTS + 1];

    /** Collects what the servers' critical threads (e.g. the observer's CommitProcessor) die of. */
    private final List<Throwable> criticalErrors = new java.util.concurrent.CopyOnWriteArrayList<>();
    private final AppenderBase<ILoggingEvent> criticalAppender = new AppenderBase<ILoggingEvent>() {
        @Override
        protected void append(ILoggingEvent event) {
            if (event.getThrowableProxy() instanceof ThrowableProxy) {
                criticalErrors.add(((ThrowableProxy) event.getThrowableProxy()).getThrowable());
            }
        }
    };

    @org.junit.jupiter.api.BeforeEach
    public void captureCriticalErrors() {
        criticalAppender.start();
        ((Logger) LoggerFactory.getLogger(ZooKeeperCriticalThread.class)).addAppender(criticalAppender);
    }

    @AfterEach
    public void releaseHolds() {
        ((Logger) LoggerFactory.getLogger(ZooKeeperCriticalThread.class)).detachAppender(criticalAppender);
        holds.abort();
    }

    @Test
    @Timeout(value = 120)
    public void observerMissesCommitOfProposalReceivedDuringFollowerSync() throws Exception {
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
        TestAdhocWorkloadB6.Holds.await("the observer did not apply the warm-up create", () -> has(OBSERVER, "/warm"));

        // 1. The observer and follower F crash.
        stop(OBSERVER);
        stop(follower);

        // 2. /held is proposed; the leader and the other follower log it, but its ACKs are slow (held).
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

        // 3. F restarts and syncs; it receives the outstanding /held PROPOSAL during the sync, before its
        //    ObserverMaster is created, and logs it.
        peers[follower].start();
        holds.awaitSync(follower, peers[follower]);
        holds.awaitAckFrom(follower);

        // 4. The observer restarts and syncs through F's new ObserverMaster while /held is still uncommitted.
        peers[OBSERVER].start();
        TestAdhocWorkloadB6.Holds.await("the observer did not sync through the follower's ObserverMaster", () -> {
            QuorumPeer peer = peers[OBSERVER].getQuorumPeer();
            Observer o = peer == null ? null : peer.observer;
            ZooKeeperServer server = peer == null ? null : peer.getActiveServer();
            return o != null && o.getSocket() != null && o.getSocket().getPort() == observerMasterPorts[follower]
                && server != null && server.isRunning();
        });
        TestAdhocWorkloadB6.Holds.await("F's ObserverMaster did not activate the observer",
            () -> peers[follower].getQuorumPeer().follower.om.getNumActiveObservers() == 1);
        assertEquals(warm, database(OBSERVER).getmaxCommittedLog(), "the observer should be synced up to /warm");
        // Catch what the observer's commit processor throws (it would otherwise only be logged).
        ZooKeeperServer observerServer = peers[OBSERVER].getQuorumPeer().getActiveServer();

        // 5. The ACKs arrive: /held commits. F's ObserverMaster drops the COMMIT (no proposal recorded).
        holds.releaseAcks();
        assertTrue(heldDone.await(TestAdhocWorkloadB6.Holds.WAIT_SECONDS, TimeUnit.SECONDS),
            "the held create did not finish");
        assertEquals(Code.OK.intValue(), heldRc.get());
        TestAdhocWorkloadB6.Holds.await("F did not apply /held", () -> has(follower, "/held"));

        // 6. The next create is forwarded to the observer, which never got /held.
        client.create("/after", new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        long after = database(leader).getDataTreeLastProcessedZxid();
        assertEquals(heldZxid + 1, after, "the follow-up create should be the next transaction");

        TestAdhocWorkloadB6.Holds.await("the observer neither applied both creates nor stopped serving",
            () -> !observerServer.isRunning()
                || (has(OBSERVER, "/held") && has(OBSERVER, "/after")));
        for (Throwable t : criticalErrors) {
            if (t instanceof IllegalStateException) {
                // The observer's CommitProcessor died of the ad hoc check in ZKDatabase.addCommittedProposal.
                t.printStackTrace();
                List<Thread> serving = handlersOf(OBSERVER);
                peers[OBSERVER].shutdown();
                for (Thread handler : serving) {
                    handler.join(TimeUnit.SECONDS.toMillis(TestAdhocWorkloadB6.Holds.WAIT_SECONDS));
                }
                throw (IllegalStateException) t;
            }
        }
        boolean observerHasHeld = has(OBSERVER, "/held");
        boolean observerRunning = observerServer.isRunning();
        try {
            assertTrue(observerHasHeld && observerRunning,
                "the observer was forwarded /after (0x" + Long.toHexString(after) + ") without /held (0x"
                    + Long.toHexString(heldZxid) + "): has /held=" + observerHasHeld + ", running="
                    + observerRunning + "; see the IllegalStateException from ZKDatabase.addCommittedProposal above");
        } finally {
            List<Thread> serving = handlersOf(OBSERVER);
            peers[OBSERVER].shutdown();
            peers[OBSERVER].join(TimeUnit.SECONDS.toMillis(TestAdhocWorkloadB6.Holds.WAIT_SECONDS));
            for (Thread handler : serving) {
                handler.join(TimeUnit.SECONDS.toMillis(TestAdhocWorkloadB6.Holds.WAIT_SECONDS));
            }
        }
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
        TestAdhocWorkloadB6.Holds.await(leading ? "no leader" : "no follower with an ObserverMaster", () -> {
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

}
