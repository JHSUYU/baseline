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

import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;

import org.apache.log4j.Logger;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.KeeperException;
import org.apache.zookeeper.PortAssignment;
import org.apache.zookeeper.ZooDefs.Ids;
import org.apache.zookeeper.server.SessionTrackerImpl;
import org.apache.zookeeper.server.ZKDatabase;
import org.apache.zookeeper.server.ZooKeeperServer;
import org.apache.zookeeper.server.persistence.FileTxnSnapLog;
import org.apache.zookeeper.server.quorum.QuorumPeer.QuorumServer;
import org.apache.zookeeper.server.quorum.QuorumPeer.ServerState;
import org.apache.zookeeper.server.quorum.flexible.QuorumMaj;
import org.apache.zookeeper.test.ClientBase;
import org.apache.zookeeper.WatchedEvent;
import org.apache.zookeeper.Watcher;
import org.apache.zookeeper.Watcher.Event.KeeperState;
import org.apache.zookeeper.test.DisconnectableZooKeeper;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;

/**
 * A client reconnect attempt to follower F1 times out (the client's connect
 * request is delayed on the network), the client successfully re-establishes
 * its session on follower F2 and keeps working there. When the delayed
 * connect request finally reaches F1, F1 revalidates the session with the
 * leader and the leader hands the session's ownership to F1's LearnerHandler.
 * From then on every request the client sends through F2 (the only server it
 * is connected to) is rejected by SessionTrackerImpl.checkSession with
 * SessionMovedException.
 *
 * The only test-side additions are (a) a TCP proxy in front of F1 that delays
 * delivery of the client's bytes (network delay) and (b) a leader whose
 * session tracker records, without changing, the SessionMovedExceptions
 * thrown by the real SessionTrackerImpl.checkSession so that the server-side
 * stack trace can be shown.
 */
public class StaleRevalidateSessionMovedTest {
    private static final Logger LOG =
        Logger.getLogger(StaleRevalidateSessionMovedTest.class);

    static final List<KeeperException.SessionMovedException> moved =
        new CopyOnWriteArrayList<KeeperException.SessionMovedException>();

    /** Leader server whose session tracker only observes checkSession. */
    static class ObservedLeaderZooKeeperServer extends LeaderZooKeeperServer {
        ObservedLeaderZooKeeperServer(FileTxnSnapLog logFactory,
                QuorumPeer self, ZKDatabase zkDb) throws IOException {
            super(logFactory, self,
                    new ZooKeeperServer.BasicDataTreeBuilder(), zkDb);
        }

        @Override
        protected void createSessionTracker() {
            sessionTracker = new SessionTrackerImpl(this,
                    getZKDatabase().getSessionWithTimeOuts(), tickTime,
                    self.getId()) {
                @Override
                public synchronized void checkSession(long sessionId,
                        Object owner)
                    throws KeeperException.SessionExpiredException,
                           KeeperException.SessionMovedException
                {
                    try {
                        super.checkSession(sessionId, owner);
                    } catch (KeeperException.SessionMovedException e) {
                        LOG.error("checkSession rejected session 0x"
                                + Long.toHexString(sessionId), e);
                        moved.add(e);
                        throw e;
                    }
                }
            };
            ((SessionTrackerImpl) sessionTracker).start();
        }
    }

    /** Unmodified QuorumPeer except that its leader uses the observed tracker. */
    static class ObservedQuorumPeer extends QuorumPeer {
        private ZKDatabase db;

        ObservedQuorumPeer(HashMap<Long, QuorumServer> peers, File dir,
                int clientPort, long myid, int tickTime, int initLimit,
                int syncLimit) throws IOException {
            super(peers, dir, dir, clientPort, 3, myid, tickTime, initLimit,
                    syncLimit, new QuorumMaj(peers.size()));
            setZKDatabase(new ZKDatabase(getTxnFactory()));
        }

        @Override
        public void setZKDatabase(ZKDatabase database) {
            this.db = database;
            super.setZKDatabase(database);
        }

        @Override
        protected Leader makeLeader(FileTxnSnapLog logFactory)
            throws IOException
        {
            return new Leader(this,
                    new ObservedLeaderZooKeeperServer(logFactory, this, db));
        }
    }

    /**
     * TCP proxy that models a slow network path from the client to F1: it
     * accepts the client's connection and holds whatever the client sends
     * until release() is called.
     */
    static class DelayingProxy extends Thread {
        final ServerSocket ss;
        final InetSocketAddress target;
        final ByteArrayOutputStream held = new ByteArrayOutputStream();
        volatile boolean clientGone = false;

        DelayingProxy(int port, InetSocketAddress target) throws IOException {
            super("DelayingProxy");
            setDaemon(true);
            ss = new ServerSocket();
            ss.setReuseAddress(true);
            ss.bind(new InetSocketAddress("127.0.0.1", port));
            this.target = target;
        }

        @Override
        public void run() {
            try {
                while (true) {
                    Socket s = ss.accept();
                    InputStream in = s.getInputStream();
                    byte[] b = new byte[4096];
                    int n;
                    try {
                        while ((n = in.read(b)) > 0) {
                            synchronized (held) {
                                held.write(b, 0, n);
                            }
                        }
                    } catch (IOException e) {
                        // client reset the connection
                    }
                    s.close();
                    synchronized (held) {
                        if (held.size() > 0) {
                            clientGone = true;
                            held.notifyAll();
                        }
                    }
                }
            } catch (IOException e) {
                // proxy closed
            }
        }

        synchronized boolean hasHeldRequest() {
            synchronized (held) {
                return held.size() > 0 && clientGone;
            }
        }

        /**
         * Deliver the held bytes to F1 (late), wait for F1's answer and
         * return the number of answer bytes.
         */
        int release() throws IOException {
            byte[] data;
            synchronized (held) {
                data = held.toByteArray();
            }
            Socket up = new Socket();
            up.connect(target, 5000);
            OutputStream out = up.getOutputStream();
            out.write(data);
            out.flush();
            up.setSoTimeout(10000);
            int got = 0;
            InputStream in = up.getInputStream();
            byte[] b = new byte[4096];
            try {
                int n = in.read(b);
                if (n > 0) {
                    got += n;
                }
            } catch (SocketTimeoutException e) {
                // no answer
            }
            up.close();
            return got;
        }

        void shutdown() {
            try {
                ss.close();
            } catch (IOException e) {
                // ignore
            }
        }
    }

    static class CountdownWatcher implements Watcher {
        private boolean connected = false;

        public synchronized void process(WatchedEvent event) {
            connected = event.getState() == KeeperState.SyncConnected;
            notifyAll();
        }

        synchronized void waitForConnected(long timeout) throws Exception {
            long expire = System.currentTimeMillis() + timeout;
            long left = timeout;
            while (!connected && left > 0) {
                wait(left);
                left = expire - System.currentTimeMillis();
            }
            if (!connected) {
                throw new Exception("Did not connect");
            }
        }
    }

    private final List<QuorumPeer> peers = new ArrayList<QuorumPeer>();
    private final int[] clientPorts = new int[3];
    private DelayingProxy proxy;

    @Before
    public void setUp() throws Exception {
        ClientBase.setupTestEnv();
        moved.clear();
        HashMap<Long, QuorumServer> qs = new HashMap<Long, QuorumServer>();
        for (int i = 0; i < 3; i++) {
            clientPorts[i] = PortAssignment.unique();
            qs.put(Long.valueOf(i + 1), new QuorumServer(i + 1,
                    new InetSocketAddress("127.0.0.1", PortAssignment.unique()),
                    new InetSocketAddress("127.0.0.1", PortAssignment.unique())));
        }
        for (int i = 0; i < 3; i++) {
            File dir = ClientBase.createTmpDir();
            QuorumPeer p = new ObservedQuorumPeer(qs, dir, clientPorts[i],
                    i + 1, 2000, 3, 3);
            peers.add(p);
        }
        for (QuorumPeer p : peers) {
            p.start();
        }
        for (int i = 0; i < 3; i++) {
            assertTrue("server " + (i + 1) + " up", ClientBase.waitForServerUp(
                    "127.0.0.1:" + clientPorts[i], ClientBase.CONNECTION_TIMEOUT));
        }
    }

    @After
    public void tearDown() throws Exception {
        if (proxy != null) {
            proxy.shutdown();
        }
        for (QuorumPeer p : peers) {
            p.shutdown();
            if (p.getElectionAlg() != null) {
                p.getElectionAlg().shutdown();
            }
            p.join(30000);
        }
    }

    @Test
    public void testStaleReconnectStealsSession() throws Exception {
        // wait until a leader is elected and identify two followers
        int leader = -1;
        long deadline = System.currentTimeMillis() + 30000;
        while (leader < 0 && System.currentTimeMillis() < deadline) {
            for (int i = 0; i < 3; i++) {
                if (peers.get(i).getPeerState() == ServerState.LEADING
                        && peers.get(i).leader != null) {
                    leader = i;
                }
            }
            Thread.sleep(100);
        }
        assertTrue("no leader", leader >= 0);
        int f1 = (leader + 1) % 3;
        int f2 = (leader + 2) % 3;
        String hpF1 = "127.0.0.1:" + clientPorts[f1];
        String hpF2 = "127.0.0.1:" + clientPorts[f2];
        LOG.info("leader=" + (leader + 1) + " F1=" + (f1 + 1) + " F2=" + (f2 + 1));

        int proxyPort = PortAssignment.unique();
        proxy = new DelayingProxy(proxyPort,
                new InetSocketAddress("127.0.0.1", clientPorts[f1]));
        proxy.start();
        String hpProxy = "127.0.0.1:" + proxyPort;

        int sessionTimeout = 6000;

        // 1. client creates a session on F2 and does some work
        CountdownWatcher watcher = new CountdownWatcher();
        DisconnectableZooKeeper zk =
            new DisconnectableZooKeeper(hpF2, sessionTimeout, watcher);
        watcher.waitForConnected(ClientBase.CONNECTION_TIMEOUT);
        zk.create("/w", new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        long sessionId = zk.getSessionId();
        byte[] passwd = zk.getSessionPasswd();

        // 2. the client's TCP connection drops; it reconnects with the
        //    server list {F1 (via a slow network path), F2}. Its connect
        //    attempt to F1 times out, so it moves on and re-establishes the
        //    session on F2. (The client library shuffles the server list, so
        //    repeat until it tried F1 first.)
        for (int attempt = 0; attempt < 20 && !proxy.hasHeldRequest(); attempt++) {
            zk.disconnect();
            watcher = new CountdownWatcher();
            zk = new DisconnectableZooKeeper(hpProxy + "," + hpF2,
                    sessionTimeout, watcher, sessionId, passwd);
            watcher.waitForConnected(ClientBase.CONNECTION_TIMEOUT);
        }
        assertTrue("client never tried F1 first", proxy.hasHeldRequest());
        LOG.info("client gave up on F1 and is connected to F2 with session 0x"
                + Long.toHexString(zk.getSessionId()));

        // the session works on F2
        zk.setData("/w", "on-F2".getBytes(), -1);
        zk.create("/w/c-", new byte[0], Ids.OPEN_ACL_UNSAFE,
                CreateMode.PERSISTENT_SEQUENTIAL);

        // 3. the delayed connect request finally reaches F1; F1 revalidates
        //    the session with the leader (which re-assigns the owner to F1)
        int answer = proxy.release();
        LOG.info("F1 answered the late connect request with " + answer + " bytes");

        // 4. the client, still connected only to F2, continues its work
        List<Throwable> clientErrors = new ArrayList<Throwable>();
        for (int i = 0; i < 3; i++) {
            try {
                zk.setData("/w", ("after-" + i).getBytes(), -1);
            } catch (KeeperException.SessionMovedException e) {
                clientErrors.add(e);
            }
        }
        zk.close();

        if (!moved.isEmpty()) {
            KeeperException.SessionMovedException serverSide = moved.get(0);
            System.out.println("Server-side SessionMovedException "
                    + "(leader's SessionTrackerImpl.checkSession):");
            serverSide.printStackTrace(System.out);
            AssertionError err = new AssertionError("Client connected only to F2"
                    + " got " + clientErrors.size() + "/3 SessionMovedException"
                    + " after a stale reconnect attempt to F1 was delivered late;"
                    + " leader rejected the request in checkSession");
            err.initCause(serverSide);
            throw err;
        }
        if (!clientErrors.isEmpty()) {
            fail("client got SessionMovedException: " + clientErrors);
        }
    }
}
