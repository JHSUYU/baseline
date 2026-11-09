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

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;
import java.io.IOException;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import javax.security.sasl.SaslException;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.PortAssignment;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.ZooKeeper.States;
import org.apache.zookeeper.common.X509Exception;
import org.apache.zookeeper.proto.ConnectRequest;
import org.apache.zookeeper.server.ClientCnxnLimitException;
import org.apache.zookeeper.server.ServerCnxn;
import org.apache.zookeeper.server.persistence.FileTxnSnapLog;
import org.apache.zookeeper.test.ClientBase;
import org.apache.zookeeper.test.ClientBase.CountdownWatcher;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

/**
 * After a leader election (here: the old leader crashes and later restarts) and before any new
 * transaction, the new leader sets its dataTree.lastProcessedZxid to (newEpoch << 32) in
 * Leader#startZkServer, while the followers, synchronized by an (empty) DIFF, keep the last zxid of
 * the previous epoch. A client that reads from the new leader receives (newEpoch << 32) as the
 * reply zxid and remembers it as lastZxidSeen. When the client then moves to a follower (which is
 * fully in sync with the leader), ZooKeeperServer#processConnectRequest refuses it with
 * CLIENT_ZXID_AHEAD, and keeps refusing it until some client writes a transaction.
 */
public class ZxidAheadAfterElectionTest extends QuorumPeerTestBase {

    private static final int SERVER_COUNT = 3;
    private final MainThread[] mt = new MainThread[SERVER_COUNT];

    static final List<Throwable> REJECTIONS = new CopyOnWriteArrayList<>();

    @BeforeEach
    public void setUp() {
        REJECTIONS.clear();
    }

    @AfterEach
    public void tearDown() throws Exception {
        for (MainThread m : mt) {
            if (m != null) {
                m.shutdown();
            }
        }
    }

    /** Observes (and rethrows unchanged) rejections so that their stack traces reach the test output. */
    static void observe(ServerCnxn.CloseRequestException e) {
        LOG.error("processConnectRequest refused the client", e);
        REJECTIONS.add(e);
    }

    static class ObservingQuorumPeer extends QuorumPeer {

        ObservingQuorumPeer() throws SaslException {
        }

        @Override
        protected Follower makeFollower(FileTxnSnapLog logFactory) throws IOException {
            return new Follower(this, new FollowerZooKeeperServer(logFactory, this, this.getZkDb()) {
                @Override
                public void processConnectRequest(ServerCnxn cnxn, ConnectRequest request)
                        throws IOException, ClientCnxnLimitException {
                    try {
                        super.processConnectRequest(cnxn, request);
                    } catch (ServerCnxn.CloseRequestException e) {
                        observe(e);
                        throw e;
                    }
                }
            });
        }

        @Override
        protected Leader makeLeader(FileTxnSnapLog logFactory) throws IOException, X509Exception {
            return new Leader(this, new LeaderZooKeeperServer(logFactory, this, this.getZkDb()) {
                @Override
                public void processConnectRequest(ServerCnxn cnxn, ConnectRequest request)
                        throws IOException, ClientCnxnLimitException {
                    try {
                        super.processConnectRequest(cnxn, request);
                    } catch (ServerCnxn.CloseRequestException e) {
                        observe(e);
                        throw e;
                    }
                }
            });
        }
    }

    static class ObservingQPMain extends TestQPMain {
        @Override
        protected QuorumPeer getQuorumPeer() throws SaslException {
            return new ObservingQuorumPeer();
        }
    }

    private int findLeader() {
        for (int i = 0; i < SERVER_COUNT; i++) {
            QuorumPeer qp = mt[i].getQuorumPeer();
            if (mt[i].isAlive() && qp != null && qp.leader != null && qp.getPeerState() == QuorumPeer.ServerState.LEADING) {
                return i;
            }
        }
        return -1;
    }

    private int waitForLeader() throws InterruptedException {
        long start = System.currentTimeMillis();
        int l;
        while ((l = findLeader()) < 0) {
            assertTrue(System.currentTimeMillis() - start < ClientBase.CONNECTION_TIMEOUT, "no leader elected");
            Thread.sleep(100);
        }
        return l;
    }

    private static String hp(int port) {
        return "127.0.0.1:" + port;
    }

    @Test
    @Timeout(value = 180)
    public void testClientRefusedByInSyncFollowersAfterElection() throws Exception {
        final int[] clientPorts = new int[SERVER_COUNT];
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < SERVER_COUNT; i++) {
            clientPorts[i] = PortAssignment.unique();
            sb.append("server." + i + "=127.0.0.1:" + PortAssignment.unique() + ":" + PortAssignment.unique()
                    + ":participant;127.0.0.1:" + clientPorts[i] + "\n");
        }
        String quorumCfg = sb.toString();
        Map<String, String> otherConfigs = new HashMap<>();
        // same setting as ReadOnlyModeTest#testSeekForRwServer
        otherConfigs.put("localSessionsEnabled", "true");

        for (int i = 0; i < SERVER_COUNT; i++) {
            mt[i] = new MainThread(i, clientPorts[i], quorumCfg, otherConfigs) {
                @Override
                public TestQPMain getTestQPMain() {
                    return new ObservingQPMain();
                }
            };
            mt[i].start();
        }
        for (int i = 0; i < SERVER_COUNT; i++) {
            assertTrue(ClientBase.waitForServerUp(hp(clientPorts[i]), ClientBase.CONNECTION_TIMEOUT));
        }
        String all = hp(clientPorts[0]) + "," + hp(clientPorts[1]) + "," + hp(clientPorts[2]);

        // 1. some data is written in epoch 1
        CountdownWatcher w0 = new CountdownWatcher();
        ZooKeeper writer = new ZooKeeper(all, ClientBase.CONNECTION_TIMEOUT, w0);
        w0.waitForConnected(ClientBase.CONNECTION_TIMEOUT);
        writer.create("/a", "data".getBytes(), ZooDefs.Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        writer.close();

        // 2. the leader crashes; the two others elect a new leader (epoch 2); the old leader restarts
        //    and rejoins as a follower. No write happens in the new epoch.
        int oldLeader = waitForLeader();
        mt[oldLeader].shutdown();
        int newLeader;
        long start = System.currentTimeMillis();
        while ((newLeader = findLeader()) < 0 || newLeader == oldLeader) {
            assertTrue(System.currentTimeMillis() - start < ClientBase.CONNECTION_TIMEOUT, "no new leader");
            Thread.sleep(100);
        }
        assertTrue(ClientBase.waitForServerUp(hp(clientPorts[newLeader]), ClientBase.CONNECTION_TIMEOUT));
        mt[oldLeader].start();
        assertTrue(ClientBase.waitForServerUp(hp(clientPorts[oldLeader]), ClientBase.CONNECTION_TIMEOUT));
        final int f1 = (newLeader + 1) % SERVER_COUNT;
        final int f2 = (newLeader + 2) % SERVER_COUNT;
        for (int i = 0; i < SERVER_COUNT; i++) {
            QuorumPeer qp = mt[i].getQuorumPeer();
            LOG.info("server {} state {} epoch {} lastLoggedZxid=0x{} dataTree.lastProcessedZxid=0x{}", i,
                    qp.getPeerState(), qp.getCurrentEpoch(), Long.toHexString(qp.getLastLoggedZxid()),
                    Long.toHexString(qp.getZkDb().getDataTreeLastProcessedZxid()));
        }

        // the followers are in sync: a fresh client reads /a from each of them
        for (int f : new int[] {f1, f2}) {
            CountdownWatcher w = new CountdownWatcher();
            ZooKeeper z = new ZooKeeper(hp(clientPorts[f]), ClientBase.CONNECTION_TIMEOUT, w);
            w.waitForConnected(ClientBase.CONNECTION_TIMEOUT);
            assertArrayEquals("data".getBytes(), z.getData("/a", false, null), "follower " + f + " in sync");
            z.close();
        }
        REJECTIONS.clear();

        // 3. a client served by the new leader reads /a; the reply zxid is (2 << 32)
        CountdownWatcher watcher = new CountdownWatcher();
        ZooKeeper zk = new ZooKeeper(hp(clientPorts[newLeader]), ClientBase.CONNECTION_TIMEOUT, watcher);
        watcher.waitForConnected(ClientBase.CONNECTION_TIMEOUT);
        assertArrayEquals("data".getBytes(), zk.getData("/a", false, null));
        LOG.info("client after read from new leader: {}", zk);

        // 4. the client moves to the followers (its connection to the leader is dropped because the
        //    client's server list is rebalanced to the followers, e.g. the leader is taken out of the
        //    client connect string / is no longer reachable from the client)
        watcher.reset();
        zk.updateServerList(hp(clientPorts[f1]) + "," + hp(clientPorts[f2]));

        // 5. both in-sync followers refuse the client: lastZxidSeen 0x200000000 > their 0x100000002
        long waitStart = System.currentTimeMillis();
        while (System.currentTimeMillis() - waitStart < 20000) {
            if (zk.getState() == States.CONNECTED && !REJECTIONS.isEmpty()) {
                break;
            }
            Thread.sleep(200);
        }
        LOG.info("client state after moving to followers: {}, rejections {}", zk, REJECTIONS.size());
        assertFalse(REJECTIONS.isEmpty(), "no CLIENT_ZXID_AHEAD rejection observed");
        Throwable t = REJECTIONS.get(0);
        StringWriter sw = new StringWriter();
        t.printStackTrace(new PrintWriter(sw));
        System.out.println("Followers refused the client " + REJECTIONS.size() + " times:\n" + sw);
        States state = zk.getState();
        zk.close();
        fail("Client that read from the new leader is refused by in-sync followers (state " + state + ", "
                + REJECTIONS.size() + " rejections): " + t.getMessage(), t);
    }
}
