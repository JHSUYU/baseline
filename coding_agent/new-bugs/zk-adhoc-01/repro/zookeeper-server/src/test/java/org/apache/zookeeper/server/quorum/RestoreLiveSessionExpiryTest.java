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

import static org.apache.zookeeper.server.ZooKeeperServer.ZOOKEEPER_SERIALIZE_LAST_PROCESSED_ZXID_ENABLED;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.File;
import java.io.IOException;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.zip.CheckedInputStream;
import javax.security.sasl.SaslException;
import org.apache.zookeeper.AsyncCallback;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.KeeperException;
import org.apache.zookeeper.PortAssignment;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.common.X509Exception;
import org.apache.zookeeper.server.SessionTracker;
import org.apache.zookeeper.server.SessionTracker.SessionExpirer;
import org.apache.zookeeper.server.ZooKeeperServerListener;
import org.apache.zookeeper.server.persistence.FileTxnSnapLog;
import org.apache.zookeeper.server.persistence.SnapStream;
import org.apache.zookeeper.test.ClientBase;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Reproduces a failure of the ad hoc check in
 * {@link org.apache.zookeeper.server.SessionTrackerImpl#checkSession(long, Object)}
 * (SessionTrackerImpl.java:317 - {@code session.isClosing()} =&gt;
 * {@code KeeperException.SessionExpiredException}) for a session that is alive.
 *
 * <p>Execution: a three node ensemble, a client holding a live session on a follower, and a
 * snapshot restore on the leader (what the {@code restore} admin command does, see
 * {@code Commands.RestoreCommand#runPost} and
 * {@code org.apache.zookeeper.server.admin.RestoreQuorumTest}) using a snapshot that contains
 * that very session, so the restore is meant to keep the session alive.
 *
 * <p>{@code ZooKeeperServer#restoreFromSnapshot} installs a brand new session tracker but
 * never shuts the previous one down (and never starts the new one). The orphaned tracker keeps
 * running its expiry loop over an expiry queue nothing refreshes any more - every session
 * touch (the client's pings, relayed to the leader in the follower's PING reply) now goes to
 * the new tracker - so one session timeout after the restore it "expires" the live session and
 * submits a closeSession request for it. PrepRequestProcessor preps that closeSession and
 * marks the session closing in the *new* tracker, and from then on the requests the still
 * connected client has in flight fail the ad hoc check: the leader rejects as expired a
 * session that the restore kept and that the client is still pinging.
 */
public class RestoreLiveSessionExpiryTest extends QuorumPeerTestBase {

    private static final Logger LOG = LoggerFactory.getLogger(RestoreLiveSessionExpiryTest.class);

    private static final int SERVER_COUNT = 3;
    private static final int TICK_TIME = 1000;
    private static final int SESSION_TIMEOUT = 4000;
    private static final String PATH = "/restore-live-session";

    /** The client whose live session the leader rejects. */
    static final AtomicReference<ZooKeeper> CLIENT = new AtomicReference<>();

    /**
     * Every SessionExpiredException the leader's checkSession() throws for that client, paired
     * with the state its connection was in at that moment.
     */
    static final List<Object[]> CHECK_SESSION_FAILURES = Collections.synchronizedList(new ArrayList<>());

    /** Session trackers the leader created: #0 is the pre-restore one, #1 the restored one. */
    static final List<SessionTracker> TRACKERS = Collections.synchronizedList(new ArrayList<>());

    private MainThread[] mt;
    private int[] clientPorts;

    @AfterEach
    public void tearDown() throws Exception {
        if (mt != null) {
            for (MainThread t : mt) {
                try {
                    t.shutdown();
                } catch (Exception e) {
                    LOG.warn("exception shutting down server", e);
                }
            }
        }
        System.clearProperty(ZOOKEEPER_SERIALIZE_LAST_PROCESSED_ZXID_ENABLED);
        CHECK_SESSION_FAILURES.clear();
        TRACKERS.clear();
        CLIENT.set(null);
    }

    @Test
    public void testRestoreExpiresLiveSession() throws Exception {
        ClientBase.setupTestEnv();
        // the restore path needs snapshots that carry lastProcessedZxid (production default)
        System.setProperty(ZOOKEEPER_SERIALIZE_LAST_PROCESSED_ZXID_ENABLED, "true");

        startEnsemble();

        final int leaderIdx = findLeader();
        final int followerIdx = (leaderIdx + 1) % SERVER_COUNT;
        LOG.info("leader is server {}, client will connect to follower {}", leaderIdx, followerIdx);

        final LeaderZooKeeperServer leaderZks =
                (LeaderZooKeeperServer) mt[leaderIdx].getQuorumPeer().getActiveServer();

        // A client with a live session on a follower: its writes are forwarded to the leader
        // and prepped there, which is where the ad hoc check runs.
        final ClientBase.CountdownWatcher watcher = new ClientBase.CountdownWatcher();
        final ZooKeeper zk = new ZooKeeper("127.0.0.1:" + clientPorts[followerIdx], SESSION_TIMEOUT, watcher);
        CLIENT.set(zk);
        try {
            watcher.waitForConnected(ClientBase.CONNECTION_TIMEOUT);
            final long sessionId = zk.getSessionId();
            LOG.info("client session 0x{} established on follower {}", Long.toHexString(sessionId), followerIdx);

            zk.create(PATH, new byte[0], ZooDefs.Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
            assertTrue(leaderZks.getSessionTracker().globalSessions().contains(sessionId),
                    "the leader tracks the client's global session");

            // The operator restores a snapshot of the leader on the leader - the same call the
            // "restore" admin command makes (Commands.RestoreCommand#runPost). The snapshot is
            // taken right before, so it holds the live session and the ensemble's current data.
            final File snapshot = leaderZks.takeSnapshot(false, false);
            try (final CheckedInputStream is = SnapStream.getInputStream(snapshot)) {
                leaderZks.restoreFromSnapshot(is);
            }
            LOG.info("restore done on leader {}", leaderIdx);

            assertTrue(TRACKERS.size() >= 2, "the restore created a second session tracker");
            final SessionTracker orphanedTracker = TRACKERS.get(TRACKERS.size() - 2);
            final SessionTracker restoredTracker = TRACKERS.get(TRACKERS.size() - 1);
            assertTrue(leaderZks.getSessionTracker().globalSessions().contains(sessionId),
                    "the restored session tracker kept the live session");
            assertEquals(ZooKeeper.States.CONNECTED, zk.getState(), "the client is still connected");

            // The client keeps using (and pinging) its session. Within one session timeout the
            // orphaned pre-restore tracker expires the session underneath it.
            final AtomicInteger sessionExpiredReplies = new AtomicInteger();
            final AtomicInteger otherErrorReplies = new AtomicInteger();
            final AtomicInteger okReplies = new AtomicInteger();
            final java.util.Map<Integer, AtomicInteger> rcCounts = new java.util.concurrent.ConcurrentHashMap<>();
            final AsyncCallback.StatCallback cb = (rc, path, ctx, stat) -> {
                rcCounts.computeIfAbsent(rc, k -> new AtomicInteger()).incrementAndGet();
                if (rc == KeeperException.Code.OK.intValue()) {
                    okReplies.incrementAndGet();
                } else if (rc == KeeperException.Code.SESSIONEXPIRED.intValue()) {
                    sessionExpiredReplies.incrementAndGet();
                } else {
                    otherErrorReplies.incrementAndGet();
                }
            };

            final long deadline = System.currentTimeMillis() + 60000;
            long lastDiag = 0;
            Object[] failure = null;
            int writes = 0;
            while (System.currentTimeMillis() < deadline) {
                failure = findCheckFailureAt317();
                if (failure != null) {
                    break;
                }
                for (int i = 0; i < 10; i++) {
                    zk.setData(PATH, new byte[]{(byte) writes}, -1, cb, null);
                    writes++;
                }
                Thread.sleep(5);
                if (System.currentTimeMillis() - lastDiag > 1000) {
                    lastDiag = System.currentTimeMillis();
                    LOG.info("client={} orphaned tracker expiry queue={} restored tracker expiry queue={}",
                            zk.getState(), orphanedTracker.getSessionExpiryMap(),
                            restoredTracker.getSessionExpiryMap());
                }
            }
            if (failure == null) {
                failure = findCheckFailureAt317();
            }
            // let the replies for the rejected requests make it back to the client
            Thread.sleep(2000);
            LOG.info("writes issued: {}, ok replies: {}, SESSIONEXPIRED replies: {}, other error replies: {}",
                    writes, okReplies.get(), sessionExpiredReplies.get(), otherErrorReplies.get());
            for (java.util.Map.Entry<Integer, AtomicInteger> e : rcCounts.entrySet()) {
                LOG.info("reply rc {} ({}): {}", e.getKey(),
                        KeeperException.Code.get(e.getKey()), e.getValue().get());
            }

            assertNotNull(failure, "expected the leader's checkSession to reject the live session");
            final KeeperException.SessionExpiredException thrown = (KeeperException.SessionExpiredException) failure[0];
            final ZooKeeper.States stateWhenThrown = (ZooKeeper.States) failure[1];

            final StringWriter sw = new StringWriter();
            thrown.printStackTrace(new PrintWriter(sw));
            final String trace = sw.toString();
            System.out.println("=== the leader threw SessionExpiredException for session 0x"
                    + Long.toHexString(sessionId) + " while its client connection was "
                    + stateWhenThrown + " ===");
            System.out.println(trace);
            LOG.error("ad hoc check (SessionTrackerImpl.java:317) failed for a live session", thrown);

            assertTrue(trace.contains("org.apache.zookeeper.server.SessionTrackerImpl.checkSession"
                            + "(SessionTrackerImpl.java:317)"),
                    "stack trace must contain SessionTrackerImpl.java:317, was:\n" + trace);
            // The session was not expired: the client connection was up (and its pings were
            // being answered) at the very moment the leader rejected its request as expired.
            assertEquals(ZooKeeper.States.CONNECTED, stateWhenThrown,
                    "the client was connected when the leader rejected its request as session expired");

            // Consequence in a real deployment: the live session is force closed. The client
            // never stopped pinging, yet it loses its session (and its ephemeral nodes) a
            // session timeout after the restore that was supposed to preserve it.
            ZooKeeper.States finalState = zk.getState();
            for (int i = 0; i < 100 && finalState == ZooKeeper.States.CONNECTED; i++) {
                Thread.sleep(200);
                finalState = zk.getState();
            }
            LOG.info("client state after the forced expiry: {}", finalState);
            assertTrue(finalState != ZooKeeper.States.CONNECTED,
                    "the live session was killed by the orphaned session tracker, client state: " + finalState);
        } finally {
            CLIENT.set(null);
            try {
                zk.close(1000);
            } catch (Exception e) {
                LOG.warn("exception closing client", e);
            }
        }
    }

    private static Object[] findCheckFailureAt317() {
        synchronized (CHECK_SESSION_FAILURES) {
            for (Object[] record : CHECK_SESSION_FAILURES) {
                for (StackTraceElement f : ((Throwable) record[0]).getStackTrace()) {
                    if ("org.apache.zookeeper.server.SessionTrackerImpl".equals(f.getClassName())
                            && "checkSession".equals(f.getMethodName())
                            && f.getLineNumber() == 317) {
                        return record;
                    }
                }
            }
        }
        return null;
    }

    private void startEnsemble() throws Exception {
        clientPorts = new int[SERVER_COUNT];
        final StringBuilder sb = new StringBuilder();
        for (int i = 0; i < SERVER_COUNT; i++) {
            clientPorts[i] = PortAssignment.unique();
            sb.append(String.format("server.%d=127.0.0.1:%d:%d;127.0.0.1:%d%n",
                    i, PortAssignment.unique(), PortAssignment.unique(), clientPorts[i]));
        }
        final String quorumCfgSection = sb.toString();
        final Map<String, String> otherConfigs = new HashMap<>();
        otherConfigs.put("minSessionTimeout", String.valueOf(SESSION_TIMEOUT));

        mt = new MainThread[SERVER_COUNT];
        for (int i = 0; i < SERVER_COUNT; i++) {
            mt[i] = new MainThread(i, clientPorts[i], quorumCfgSection, otherConfigs, TICK_TIME) {
                @Override
                public TestQPMain getTestQPMain() {
                    return new CapturingQPMain();
                }
            };
            mt[i].start();
        }
        for (int i = 0; i < SERVER_COUNT; i++) {
            assertTrue(ClientBase.waitForServerUp("127.0.0.1:" + clientPorts[i], ClientBase.CONNECTION_TIMEOUT),
                    "server " + i + " being up");
        }
    }

    private int findLeader() throws InterruptedException {
        for (int tries = 0; tries < 100; tries++) {
            for (int i = 0; i < SERVER_COUNT; i++) {
                final QuorumPeer peer = mt[i].getQuorumPeer();
                if (peer != null && peer.getPeerState() == QuorumPeer.ServerState.LEADING
                        && peer.getActiveServer() instanceof LeaderZooKeeperServer) {
                    return i;
                }
            }
            Thread.sleep(200);
        }
        throw new AssertionError("no leader found");
    }

    /**
     * The only hook into the system: the leader's session tracker is subclassed so that the
     * test can observe (and re-throw unchanged) the SessionExpiredException the ad hoc check
     * throws. It is installed through the regular createSessionTracker() factory method, which
     * restoreFromSnapshot() calls too, so the post-restore tracker is observed as well.
     */
    private static class CapturingQPMain extends TestQPMain {

        @Override
        protected QuorumPeer getQuorumPeer() throws SaslException {
            return new QuorumPeer() {
                @Override
                protected Leader makeLeader(FileTxnSnapLog logFactory) throws IOException, X509Exception {
                    return new Leader(this, new LeaderZooKeeperServer(logFactory, this, this.getZkDb()) {
                        @Override
                        public void createSessionTracker() {
                            sessionTracker = new CapturingLeaderSessionTracker(
                                    this,
                                    getZKDatabase().getSessionWithTimeOuts(),
                                    tickTime,
                                    self.getMyId(),
                                    self.areLocalSessionsEnabled(),
                                    getZooKeeperServerListener());
                            TRACKERS.add(sessionTracker);
                            LOG.info("leader created session tracker #{}", TRACKERS.size());
                        }
                    });
                }
            };
        }
    }

    private static class CapturingLeaderSessionTracker extends LeaderSessionTracker {

        CapturingLeaderSessionTracker(SessionExpirer expirer, ConcurrentMap<Long, Integer> sessionsWithTimeouts,
                int tickTime, long id, boolean localSessionsEnabled, ZooKeeperServerListener listener) {
            super(expirer, sessionsWithTimeouts, tickTime, id, localSessionsEnabled, listener);
        }

        @Override
        public void checkSession(long sessionId, Object owner)
                throws KeeperException.SessionExpiredException, KeeperException.SessionMovedException,
                KeeperException.UnknownSessionException {
            try {
                super.checkSession(sessionId, owner);
            } catch (KeeperException.SessionExpiredException e) {
                final ZooKeeper client = CLIENT.get();
                if (client != null && client.getSessionId() == sessionId) {
                    CHECK_SESSION_FAILURES.add(new Object[]{e, client.getState()});
                }
                throw e;
            }
        }
    }
}
