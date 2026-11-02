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
import java.io.File;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.stream.Stream;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.StatsTrack;
import org.apache.zookeeper.Watcher;
import org.apache.zookeeper.ZooDefs.Ids;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.cli.SetQuotaCommand;
import org.apache.zookeeper.server.ServerCnxnFactory;
import org.apache.zookeeper.server.ZooKeeperServer;
import org.apache.zookeeper.server.persistence.FilePadding;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;

/**
 * ZooInspector's retrying client creates two sequential children under a
 * hard count quota that fits exactly them.
 *
 * <p>The test runs one standalone server in its own JVM, set up as
 * ClientBase sets up its server (this module's tests do not see ClientBase):
 * a fresh data directory, tick time 3000 ms, server id 1, 100 KB log
 * preallocation, a client connection timeout of 30 s.</p>
 */
public class TestAdhocWorkloadB4 {

    private static final String PATH = "/adhoc-workload-b4";
    /** The path counts itself: two children fit. */
    private static final int COUNT_HARD_LIMIT = 3;
    /** ClientBase.CONNECTION_TIMEOUT. */
    private static final int CONNECTION_TIMEOUT = 30000;
    /** ClientBase's server tick time. */
    private static final int TICK_TIME = 3000;

    private File dataDir;
    private ServerCnxnFactory serverFactory;
    private String hostPort;

    @Before
    public void setUp() throws Exception {
        System.setProperty(ZooKeeperServer.ENFORCE_QUOTA, "true");
        System.setProperty("zookeeper.preAllocSize", "100");
        FilePadding.setPreallocSize(100 * 1024);
        dataDir = Files.createTempDirectory("adhoc-workload-b4").toFile();
        serverFactory = ServerCnxnFactory.createFactory(new InetSocketAddress("127.0.0.1", 0), 0);
        ZooKeeperServer zks = new ZooKeeperServer(dataDir, dataDir, TICK_TIME);
        zks.setCreateSessionTrackerServerId(1);
        serverFactory.startup(zks);
        hostPort = "127.0.0.1:" + serverFactory.getLocalPort();
    }

    @After
    public void tearDown() throws Exception {
        try {
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
            ZooKeeperRetry retrying = new ZooKeeperRetry(hostPort, CONNECTION_TIMEOUT, connectedWatcher(connected));
            try {
                assertTrue("the retrying client did not connect",
                    connected.await(CONNECTION_TIMEOUT, TimeUnit.MILLISECONDS));
                retrying.create(PATH + "/n-", new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT_SEQUENTIAL);
                retrying.create(PATH + "/n-", new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT_SEQUENTIAL);
            } finally {
                retrying.close();
            }
        } finally {
            zk.close();
        }
    }

    /** A client of the server, connected (as ClientBase#createClient). */
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
