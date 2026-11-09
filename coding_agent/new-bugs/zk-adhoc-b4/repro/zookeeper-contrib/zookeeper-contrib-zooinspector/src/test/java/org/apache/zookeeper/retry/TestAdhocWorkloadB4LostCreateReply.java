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

package org.apache.zookeeper.retry;

import static org.junit.Assert.assertTrue;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.File;
import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Stream;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.KeeperException;
import org.apache.zookeeper.StatsTrack;
import org.apache.zookeeper.Watcher;
import org.apache.zookeeper.ZooDefs.Ids;
import org.apache.zookeeper.ZooDefs.OpCode;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.cli.SetQuotaCommand;
import org.apache.zookeeper.server.ServerCnxnFactory;
import org.apache.zookeeper.server.ZooKeeperServer;
import org.apache.zookeeper.server.persistence.FilePadding;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;

/**
 * Same workload as {@link TestAdhocWorkloadB4}, but the network between the
 * retrying client and the server loses the server's reply to the first
 * (already committed) sequential create. The connection drops, the client
 * reconnects within its session, and ZooKeeperRetry re-issues the create
 * because {@code exists("/adhoc-workload-b4/n-")} (the un-suffixed path) is
 * always null for a sequential node. The duplicate child consumes the quota,
 * so the application's second create is rejected by the hard count quota.
 */
public class TestAdhocWorkloadB4LostCreateReply {

    private static final String PATH = "/adhoc-workload-b4";
    private static final int COUNT_HARD_LIMIT = 3;
    private static final int CONNECTION_TIMEOUT = 30000;
    private static final int TICK_TIME = 3000;

    private File dataDir;
    private ServerCnxnFactory serverFactory;
    private String hostPort;
    private DropReplyProxy proxy;
    private final List<KeeperException.QuotaExceededException> serverSideRejections = new CopyOnWriteArrayList<>();

    /** Records (and rethrows unchanged) quota rejections so the server-side stack trace can be shown. */
    private class ObservingZooKeeperServer extends ZooKeeperServer {
        ObservingZooKeeperServer(File snapDir, File logDir, int tickTime) throws IOException {
            super(snapDir, logDir, tickTime);
        }

        @Override
        public void checkQuota(String path, byte[] lastData, byte[] data, int type)
                throws KeeperException.QuotaExceededException {
            try {
                super.checkQuota(path, lastData, data, type);
            } catch (KeeperException.QuotaExceededException e) {
                serverSideRejections.add(e);
                throw e;
            }
        }
    }

    @Before
    public void setUp() throws Exception {
        System.setProperty(ZooKeeperServer.ENFORCE_QUOTA, "true");
        System.setProperty("zookeeper.preAllocSize", "100");
        FilePadding.setPreallocSize(100 * 1024);
        dataDir = Files.createTempDirectory("adhoc-workload-b4-lost").toFile();
        serverFactory = ServerCnxnFactory.createFactory(new InetSocketAddress("127.0.0.1", 0), 0);
        ZooKeeperServer zks = new ObservingZooKeeperServer(dataDir, dataDir, TICK_TIME);
        zks.setCreateSessionTrackerServerId(1);
        serverFactory.startup(zks);
        hostPort = "127.0.0.1:" + serverFactory.getLocalPort();
        proxy = new DropReplyProxy(serverFactory.getLocalPort());
        proxy.start();
    }

    @After
    public void tearDown() throws Exception {
        try {
            if (proxy != null) {
                proxy.close();
            }
            if (serverFactory != null) {
                serverFactory.shutdown();
            }
        } finally {
            System.clearProperty(ZooKeeperServer.ENFORCE_QUOTA);
            deleteRecursively(dataDir);
        }
    }

    @Test
    public void run() throws Exception {
        ZooKeeper zk = connect();
        try {
            zk.create(PATH, new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
            StatsTrack quota = new StatsTrack();
            quota.setCountHardLimit(COUNT_HARD_LIMIT);
            SetQuotaCommand.createQuota(zk, PATH, quota);

            CountDownLatch connected = new CountDownLatch(1);
            // the retrying client talks to the server through the lossy proxy
            ZooKeeperRetry retrying = new ZooKeeperRetry("127.0.0.1:" + proxy.getPort(), CONNECTION_TIMEOUT,
                connectedWatcher(connected));
            try {
                assertTrue("the retrying client did not connect",
                    connected.await(CONNECTION_TIMEOUT, TimeUnit.MILLISECONDS));
                // the reply to the next create request is lost and the connection drops
                proxy.dropNextCreateReply.set(true);
                String first = retrying.create(PATH + "/n-", new byte[0], Ids.OPEN_ACL_UNSAFE,
                    CreateMode.PERSISTENT_SEQUENTIAL);
                System.out.println("first create returned " + first + ", children now: "
                    + zk.getChildren(PATH, false) + ", dropped replies: " + proxy.droppedReplies.get());
                try {
                    retrying.create(PATH + "/n-", new byte[0], Ids.OPEN_ACL_UNSAFE,
                        CreateMode.PERSISTENT_SEQUENTIAL);
                } catch (KeeperException.QuotaExceededException clientSide) {
                    AssertionError failure = new AssertionError(
                        "second sequential create rejected by the count hard quota although the application"
                        + " created only one child before it; children: " + zk.getChildren(PATH, false),
                        serverSideRejections.isEmpty() ? clientSide : serverSideRejections.get(0));
                    failure.addSuppressed(clientSide);
                    throw failure;
                }
            } finally {
                retrying.close();
            }
        } finally {
            zk.close();
        }
    }

    /**
     * A TCP proxy speaking ZooKeeper's length-prefixed framing. When armed, it
     * forwards the next create request to the server, but drops the server's
     * reply to it and closes the client connection (a lost reply / network
     * partition). Later connections are forwarded unchanged.
     */
    private static final class DropReplyProxy implements AutoCloseable {
        private final int serverPort;
        private final ServerSocket listener;
        final AtomicBoolean dropNextCreateReply = new AtomicBoolean(false);
        final AtomicInteger droppedReplies = new AtomicInteger();
        private final List<Socket> sockets = new CopyOnWriteArrayList<>();
        private volatile boolean closed;

        DropReplyProxy(int serverPort) throws IOException {
            this.serverPort = serverPort;
            this.listener = new ServerSocket(0, 50, InetAddress.getByName("127.0.0.1"));
        }

        int getPort() {
            return listener.getLocalPort();
        }

        void start() {
            Thread acceptor = new Thread(() -> {
                while (!closed) {
                    try {
                        Socket client = listener.accept();
                        Socket server = new Socket("127.0.0.1", serverPort);
                        client.setTcpNoDelay(true);
                        server.setTcpNoDelay(true);
                        sockets.add(client);
                        sockets.add(server);
                        AtomicInteger createXid = new AtomicInteger(Integer.MIN_VALUE);
                        startPump("c->s", client, server, true, createXid);
                        startPump("s->c", server, client, false, createXid);
                    } catch (IOException e) {
                        if (!closed) {
                            e.printStackTrace();
                        }
                    }
                }
            }, "drop-reply-proxy-acceptor");
            acceptor.setDaemon(true);
            acceptor.start();
        }

        private void startPump(String name, Socket from, Socket to, boolean clientToServer, AtomicInteger createXid) {
            Thread t = new Thread(() -> {
                try {
                    DataInputStream in = new DataInputStream(from.getInputStream());
                    DataOutputStream out = new DataOutputStream(to.getOutputStream());
                    boolean first = true; // connect request / connect response has no header
                    while (true) {
                        int len = in.readInt();
                        byte[] body = new byte[len];
                        in.readFully(body);
                        if (!first && body.length >= 8) {
                            ByteBuffer bb = ByteBuffer.wrap(body);
                            int xid = bb.getInt();
                            if (clientToServer) {
                                int type = bb.getInt();
                                if (type == OpCode.create && dropNextCreateReply.compareAndSet(true, false)) {
                                    createXid.set(xid);
                                }
                            } else if (xid == createXid.get()) {
                                // the create was committed by the server; lose its reply
                                droppedReplies.incrementAndGet();
                                System.out.println("proxy: dropping reply for create xid " + xid
                                    + " and closing the client connection");
                                closeQuietly(from);
                                closeQuietly(to);
                                return;
                            }
                        }
                        first = false;
                        out.writeInt(len);
                        out.write(body);
                        out.flush();
                    }
                } catch (IOException e) {
                    // connection closed
                } finally {
                    closeQuietly(from);
                    closeQuietly(to);
                }
            }, "drop-reply-proxy-" + name);
            t.setDaemon(true);
            t.start();
        }

        private static void closeQuietly(Socket s) {
            try {
                s.close();
            } catch (IOException ignored) {
                // ignore
            }
        }

        @Override
        public void close() throws IOException {
            closed = true;
            listener.close();
            for (Socket s : sockets) {
                closeQuietly(s);
            }
        }
    }

    private ZooKeeper connect() throws IOException, InterruptedException {
        CountDownLatch connected = new CountDownLatch(1);
        ZooKeeper zk = new ZooKeeper(hostPort, CONNECTION_TIMEOUT, connectedWatcher(connected));
        if (!connected.await(CONNECTION_TIMEOUT, TimeUnit.MILLISECONDS)) {
            zk.close();
            throw new IOException("the client did not connect to " + hostPort);
        }
        return zk;
    }

    private static Watcher connectedWatcher(CountDownLatch connected) {
        return event -> {
            if (event.getState() == Watcher.Event.KeeperState.SyncConnected) {
                connected.countDown();
            }
        };
    }

    private static void deleteRecursively(File dir) throws IOException {
        if (dir == null || !dir.exists()) {
            return;
        }
        try (Stream<Path> paths = Files.walk(dir.toPath())) {
            paths.sorted(Comparator.reverseOrder()).map(Path::toFile).forEach(File::delete);
        }
    }
}
