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

package org.apache.zookeeper.server.quorum;

import java.io.IOException;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.net.InetSocketAddress;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import javax.security.sasl.SaslException;

import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.KeeperException;
import org.apache.zookeeper.PortAssignment;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.client.HostProvider;
import org.apache.zookeeper.server.DataTree.ProcessTxnResult;
import org.apache.zookeeper.server.Request;
import org.apache.zookeeper.server.ServerCnxn;
import org.apache.zookeeper.server.persistence.FileTxnSnapLog;
import org.apache.zookeeper.server.quorum.QuorumPeer.ServerState;
import org.apache.zookeeper.test.ClientBase;
import org.apache.zookeeper.test.ClientBase.CountdownWatcher;
import org.junit.After;
import org.junit.Assert;
import org.junit.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Same ensemble configuration as SessionUpgradeTest (local sessions enabled,
 * upgrading enabled). Reproduces the ZOOKEEPER-710 style race:
 *
 * a client's reconnect attempt to a slow follower A times out, the client
 * then successfully reconnects to the leader, and afterwards A's (delayed)
 * REVALIDATE for that abandoned attempt reaches the leader. The leader's
 * LearnerHandler unconditionally re-assigns the session owner to A, so the
 * leader now believes the client is attached to A although it is attached
 * to the leader. The next legitimate write of the client fails the ad hoc
 * owner check in SessionTrackerImpl.checkSession with SessionMovedException.
 *
 * Fault injection (test code only):
 *  - follower A delays sending its REVALIDATE packet to the leader until a
 *    latch is opened (= slow follower / slow quorum link);
 *  - follower B is shut down (= crash) to make the client reconnect.
 * Observation only: the leader's processTxn records the KeeperException that
 * PrepRequestProcessor attached to the request so that its stack trace can be
 * printed (the server itself only logs the message).
 */
public class SessionMovedStaleRevalidateTest extends QuorumPeerTestBase {
    protected static final Logger LOG =
        LoggerFactory.getLogger(SessionMovedStaleRevalidateTest.class);

    private static final int SERVER_COUNT = 3;

    /** SessionMovedExceptions observed on the leader's request pipeline. */
    static final ConcurrentLinkedQueue<KeeperException> MOVED =
        new ConcurrentLinkedQueue<KeeperException>();

    private MainThread[] mt;

    /** Follower that can delay the REVALIDATE message it sends to the leader. */
    static class DelayingFollower extends Follower {
        private final CustomQuorumPeer peer;
        private volatile boolean delayedSent = false;

        DelayingFollower(CustomQuorumPeer self, FollowerZooKeeperServer zk) {
            super(self, zk);
            this.peer = self;
        }

        @Override
        void validateSession(final ServerCnxn cnxn, final long clientId,
                final int timeout) throws IOException {
            final CountDownLatch gate = peer.revalidateGate;
            if (gate == null) {
                super.validateSession(cnxn, clientId, timeout);
                return;
            }
            peer.revalidateGate = null;
            LOG.info("Delaying REVALIDATE of session 0x"
                    + Long.toHexString(clientId) + " to the leader");
            peer.delayedRevalidateIssued.countDown();
            Thread t = new Thread("delayed-revalidate") {
                public void run() {
                    try {
                        gate.await();
                        LOG.info("Sending delayed REVALIDATE of session 0x"
                                + Long.toHexString(clientId));
                        delayedSent = true;
                        doValidate(cnxn, clientId, timeout);
                    } catch (Exception e) {
                        LOG.error("delayed revalidate failed", e);
                    }
                }
            };
            t.setDaemon(true);
            t.start();
        }

        private void doValidate(ServerCnxn cnxn, long clientId, int timeout)
                throws IOException {
            super.validateSession(cnxn, clientId, timeout);
        }

        @Override
        protected void revalidate(QuorumPacket qp) throws IOException {
            super.revalidate(qp);
            if (delayedSent) {
                peer.delayedRevalidateAnswered.countDown();
            }
        }
    }

    static class CustomQuorumPeer extends QuorumPeer {
        volatile CountDownLatch revalidateGate;
        final CountDownLatch delayedRevalidateIssued = new CountDownLatch(1);
        final CountDownLatch delayedRevalidateAnswered = new CountDownLatch(1);

        public CustomQuorumPeer() throws SaslException {
        }

        @Override
        protected Follower makeFollower(FileTxnSnapLog logFactory)
                throws IOException {
            return new DelayingFollower(this,
                    new FollowerZooKeeperServer(logFactory, this, getZkDb()));
        }

        @Override
        protected Leader makeLeader(FileTxnSnapLog logFactory)
                throws IOException {
            LeaderZooKeeperServer zk =
                new LeaderZooKeeperServer(logFactory, this, getZkDb()) {
                    @Override
                    public ProcessTxnResult processTxn(Request request) {
                        KeeperException ke = request.getException();
                        if (ke instanceof KeeperException.SessionMovedException) {
                            LOG.error("Leader rejected request " + request
                                    + " with SessionMovedException", ke);
                            MOVED.add(ke);
                        }
                        return super.processTxn(request);
                    }
                };
            return new Leader(this, zk);
        }
    }

    static class CustomQPMain extends TestQPMain {
        @Override
        protected QuorumPeer getQuorumPeer() throws SaslException {
            return new CustomQuorumPeer();
        }
    }

    /** Tries the servers in exactly the given order (round robin). */
    static class OrderedHostProvider implements HostProvider {
        private final List<InetSocketAddress> addrs;
        private int next = 0;

        OrderedHostProvider(List<InetSocketAddress> addrs) {
            this.addrs = addrs;
        }

        public int size() {
            return addrs.size();
        }

        public InetSocketAddress next(long spinDelay) {
            if (next > 0 && next % addrs.size() == 0 && spinDelay > 0) {
                try {
                    Thread.sleep(spinDelay);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }
            InetSocketAddress a = addrs.get(next % addrs.size());
            next++;
            return a;
        }

        public void onConnected() {
        }

        public boolean updateServerList(
                Collection<InetSocketAddress> serverAddresses,
                InetSocketAddress currentHost) {
            return false;
        }
    }

    @After
    public void tearDown() throws Exception {
        if (mt != null) {
            for (MainThread m : mt) {
                if (m != null) {
                    m.shutdown();
                }
            }
        }
    }

    @Test
    public void testStaleRevalidateFromSlowFollowerFailsOwnerCheck()
            throws Exception {
        MOVED.clear();
        final int clientPorts[] = new int[SERVER_COUNT];
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < SERVER_COUNT; i++) {
            clientPorts[i] = PortAssignment.unique();
            sb.append("server." + i + "=127.0.0.1:" + PortAssignment.unique()
                    + ":" + PortAssignment.unique() + ":participant;127.0.0.1:"
                    + clientPorts[i] + "\n");
        }
        String cfg = sb.toString();
        // Same session configuration as SessionUpgradeTest
        String extra = "localSessionsEnabled=true\n"
                + "localSessionsUpgradingEnabled=true\n";
        mt = new MainThread[SERVER_COUNT];
        for (int i = 0; i < SERVER_COUNT; i++) {
            mt[i] = new MainThread(i, clientPorts[i], PortAssignment.unique(),
                    cfg, extra, null, false) {
                @Override
                public TestQPMain getTestQPMain() {
                    return new CustomQPMain();
                }
            };
            mt[i].start();
        }
        for (int i = 0; i < SERVER_COUNT; i++) {
            Assert.assertTrue("server " + i + " up", ClientBase.waitForServerUp(
                    "127.0.0.1:" + clientPorts[i], ClientBase.CONNECTION_TIMEOUT));
        }

        int leader = -1;
        List<Integer> followers = new ArrayList<Integer>();
        for (int i = 0; i < SERVER_COUNT; i++) {
            if (mt[i].getQuorumPeer().getPeerState() == ServerState.LEADING) {
                leader = i;
            } else {
                followers.add(i);
            }
        }
        Assert.assertTrue("no leader", leader != -1);
        Assert.assertEquals(2, followers.size());
        final int b = followers.get(0); // first server of the client, crashes
        final int a = followers.get(1); // slow follower
        LOG.info("leader=" + leader + " slowFollowerA=" + a + " followerB=" + b);

        List<InetSocketAddress> order = new ArrayList<InetSocketAddress>();
        order.add(new InetSocketAddress("127.0.0.1", clientPorts[b]));
        order.add(new InetSocketAddress("127.0.0.1", clientPorts[a]));
        order.add(new InetSocketAddress("127.0.0.1", clientPorts[leader]));
        String connectString = "127.0.0.1:" + clientPorts[b] + ",127.0.0.1:"
                + clientPorts[a] + ",127.0.0.1:" + clientPorts[leader];

        CountdownWatcher watcher = new CountdownWatcher();
        // 3 servers, 12s session timeout -> 4s connect timeout per server
        ZooKeeper zk = new ZooKeeper(connectString, 12000, watcher, false,
                new OrderedHostProvider(order));
        try {
            watcher.waitForConnected(ClientBase.CONNECTION_TIMEOUT);

            // 1. Ephemeral create on follower B: local session is upgraded to a
            //    global session; leader records owner = LearnerHandler(B).
            zk.create("/eph", new byte[0], ZooDefs.Ids.OPEN_ACL_UNSAFE,
                    CreateMode.EPHEMERAL);
            LOG.info("session 0x" + Long.toHexString(zk.getSessionId())
                    + " upgraded on follower " + b);

            // 2. Follower A becomes slow in forwarding session revalidations.
            CustomQuorumPeer peerA = (CustomQuorumPeer) mt[a].getQuorumPeer();
            CountDownLatch gate = new CountDownLatch(1);
            peerA.revalidateGate = gate;

            // 3. Follower B crashes. The client reconnects to A first.
            watcher.reset();
            mt[b].shutdown();
            Assert.assertTrue("client never tried follower A",
                    peerA.delayedRevalidateIssued.await(30, TimeUnit.SECONDS));

            // 4. A does not answer within the connect timeout; the client gives
            //    up on A and reconnects to the leader, which revalidates the
            //    session and sets owner = leader (ServerCnxn.me).
            watcher.waitForConnected(ClientBase.CONNECTION_TIMEOUT);
            Assert.assertNotNull(zk.exists("/eph", false));
            LOG.info("client reconnected to the leader, session still valid");

            // 5. A's delayed REVALIDATE (for the abandoned attempt) now reaches
            //    the leader, which sets owner = LearnerHandler(A).
            gate.countDown();
            Assert.assertTrue("delayed revalidate not answered",
                    peerA.delayedRevalidateAnswered.await(30, TimeUnit.SECONDS));

            // 6. A legitimate write by the client on its current connection
            //    (to the leader) fails the owner check.
            try {
                zk.setData("/eph", "x".getBytes(), -1);
                LOG.info("setData succeeded");
            } catch (KeeperException e) {
                LOG.info("client write on its current connection failed: " + e);
            }

            long deadline = System.currentTimeMillis() + 10000;
            while (MOVED.isEmpty() && System.currentTimeMillis() < deadline) {
                Thread.sleep(50);
            }
            KeeperException moved = MOVED.peek();
            Assert.assertNotNull("SessionMovedException was not raised", moved);

            StringWriter sw = new StringWriter();
            moved.printStackTrace(new PrintWriter(sw));
            System.out.println("Leader rejected the client's request: " + sw);

            boolean atCheck = false;
            for (StackTraceElement f : moved.getStackTrace()) {
                if (f.getClassName().equals(
                        "org.apache.zookeeper.server.SessionTrackerImpl")
                        && f.getMethodName().equals("checkSession")
                        && f.getLineNumber() == 310) {
                    atCheck = true;
                    System.out.println("check frame: at " + f);
                }
            }
            Assert.assertTrue("not thrown at SessionTrackerImpl.java:310", atCheck);
        } finally {
            zk.close();
        }
    }
}
