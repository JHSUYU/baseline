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

package org.apache.zookeeper.test;

import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.KeeperException;
import org.apache.zookeeper.Quotas;
import org.apache.zookeeper.StatsTrack;
import org.apache.zookeeper.Watcher;
import org.apache.zookeeper.ZooDefs.Ids;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.cli.SetQuotaCommand;
import org.apache.zookeeper.data.ACL;
import org.apache.zookeeper.server.FinalRequestProcessor;
import org.apache.zookeeper.server.ZooKeeperServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import mockit.Invocation;
import mockit.Mock;
import mockit.MockUp;

/**
 * Same workload as {@link TestAdhocWorkloadB1}, but the (standalone) server
 * crashes right after it committed the client's create of
 * {@code /zookeeper/quota/<path>/zookeeper_limits} and before the client could
 * send the create of {@code .../zookeeper_stats}. The server is restarted,
 * the client reconnects with the same session, and retries the quota call
 * as the workload does on connection loss.
 */
public class TestAdhocWorkloadB1CrashTest extends ClientBase {

    private static final String PATH = "/adhoc-workload-b1";
    private static final int ATTEMPTS = 3;

    /**
     * NoNodeExceptions created inside the server's FinalRequestProcessor. The server
     * swallows them (it only sends the error code back), so the test records them
     * with a pass-through constructor observer (the real constructor runs unchanged)
     * to be able to show where the server threw them.
     */
    private static final List<KeeperException.NoNodeException> SERVER_NO_NODE = new CopyOnWriteArrayList<>();

    private static final class NoNodeObserver extends MockUp<KeeperException.NoNodeException> {
        @Mock
        public void $init(Invocation inv) {
            inv.proceed();
            KeeperException.NoNodeException e = inv.getInvokedInstance();
            for (StackTraceElement frame : e.getStackTrace()) {
                if (frame.getClassName().equals(FinalRequestProcessor.class.getName())) {
                    SERVER_NO_NODE.add(e);
                    break;
                }
            }
        }
    }

    @BeforeEach
    @Override
    public void setUp() throws Exception {
        SERVER_NO_NODE.clear();
        new NoNodeObserver();
        System.setProperty(ZooKeeperServer.ENFORCE_QUOTA, "true");
        super.setUp();
    }

    @AfterEach
    @Override
    public void tearDown() throws Exception {
        System.clearProperty(ZooKeeperServer.ENFORCE_QUOTA);
        super.tearDown();
    }

    /** Client that lets the test crash the server right after one create returned. */
    private final class CrashingClient extends ZooKeeper {
        private final AtomicBoolean crashArmed = new AtomicBoolean(true);

        CrashingClient(Watcher watcher) throws Exception {
            super(hostPort, CONNECTION_TIMEOUT, watcher);
        }

        @Override
        public String create(String path, byte[] data, List<ACL> acl, CreateMode createMode)
                throws KeeperException, InterruptedException {
            String result = super.create(path, data, acl, createMode);
            if (path.equals(Quotas.limitPath(PATH)) && crashArmed.compareAndSet(true, false)) {
                // The create of zookeeper_limits is committed (and persisted in the txn log).
                // Now the server process crashes before the next request arrives.
                try {
                    stopServer();
                } catch (Exception e) {
                    throw new RuntimeException(e);
                }
            }
            return result;
        }
    }

    @Test
    public void run() throws Exception {
        CountDownLatch connected = new CountDownLatch(1);
        CrashingClient zk = new CrashingClient(event -> {
            if (event.getState() == Watcher.Event.KeeperState.SyncConnected) {
                connected.countDown();
            }
        });
        try {
            assertTrue(connected.await(CONNECTION_TIMEOUT, TimeUnit.MILLISECONDS));
            zk.create(PATH, new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);

            KeeperException failure = null;
            for (int attempt = 1; attempt <= ATTEMPTS; attempt++) {
                StatsTrack quota = new StatsTrack();
                quota.setCountHardLimit(2);
                try {
                    SetQuotaCommand.createQuota(zk, PATH, quota);
                    fail("setquota unexpectedly succeeded on attempt " + attempt);
                } catch (KeeperException.ConnectionLossException lost) {
                    LOG.info("attempt {} lost its connection; restarting the crashed server", attempt, lost);
                    // the crashed server comes back up with its persisted state
                    startServer();
                    assertTrue(waitForServerUp(hostPort, CONNECTION_TIMEOUT));
                } catch (KeeperException.NoNodeException noNode) {
                    LOG.error("setquota retry failed with NoNode from the server", noNode);
                    failure = noNode;
                    break;
                }
            }
            assertNotNull(failure, "expected the retried setquota to fail with NoNode");

            // State left behind: limit node exists, stat node does not.
            assertNotNull(zk.exists(Quotas.limitPath(PATH), false));
            assertNull(zk.exists(Quotas.statPath(PATH), false));

            // Every further setquota on the path keeps failing...
            StatsTrack raised = new StatsTrack();
            raised.setCountHardLimit(3);
            assertThrows(KeeperException.NoNodeException.class, () -> SetQuotaCommand.createQuota(zk, PATH, raised));

            // ... and the hard count limit of 2 is silently not enforced.
            for (int i = 1; i <= 5; i++) {
                zk.create(PATH + "/c" + i, new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
            }
            LOG.error("created 5 children under {} although its hard count limit is 2", PATH);

            // Show where the server threw the NoNode it reported to the client.
            assertTrue(!SERVER_NO_NODE.isEmpty(), "no NoNodeException observed in FinalRequestProcessor");
            KeeperException.NoNodeException serverSide = SERVER_NO_NODE.get(0);
            LOG.error("NoNodeException thrown by the server's ad hoc check", serverSide);
            serverSide.printStackTrace(System.out);
            failure.addSuppressed(serverSide);
            // Surface the NoNode as the test's failure (client and server stack traces).
            throw new AssertionError("setquota retry after server crash failed: the server rejected getData of "
                    + Quotas.statPath(PATH) + " (hard quota now unenforced, path can no longer get a quota)", failure);
        } finally {
            zk.close();
        }
    }
}
