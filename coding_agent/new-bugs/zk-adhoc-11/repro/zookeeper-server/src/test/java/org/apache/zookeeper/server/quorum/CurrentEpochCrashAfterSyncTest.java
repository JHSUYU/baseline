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
import java.io.File;
import java.io.IOException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.PortAssignment;
import org.apache.zookeeper.ZooDefs.Ids;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.common.AtomicFileOutputStream;
import org.apache.zookeeper.server.admin.AdminServer.AdminServerException;
import org.apache.zookeeper.server.util.ZxidUtils;
import org.apache.zookeeper.test.ClientBase;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

/**
 * A follower that rejoins the ensemble after a new epoch was established persists the
 * new-epoch transactions it receives during synchronization (txn log commit / snapshot)
 * before it writes the new epoch to the currentEpoch file (Learner.syncWithLeader,
 * NEWLEADER handling). If the follower crashes (power loss, kill -9, disk error) in that
 * window, the currentEpoch file still holds the old epoch and no currentEpoch.tmp exists.
 * On restart QuorumPeer.loadDataBase() then refuses to start:
 * "The current epoch, x, is older than the last zxid, y".
 */
public class CurrentEpochCrashAfterSyncTest extends QuorumPeerTestBase {

    private static final int SERVER_COUNT = 3;
    private final MainThread[] mt = new MainThread[SERVER_COUNT];
    private final int[] clientPorts = new int[SERVER_COUNT];

    /** Set once the injected "crash" happened (first attempt to persist currentEpoch >= target). */
    private static final CountDownLatch crashed = new CountDownLatch(1);
    private static volatile long crashOnEpoch = Long.MAX_VALUE;

    @AfterEach
    public void tearDown() throws InterruptedException {
        for (MainThread m : mt) {
            if (m != null) {
                m.shutdown();
            }
        }
    }

    /** QuorumPeer that "crashes" right before the currentEpoch file is written for the new epoch. */
    static class CrashBeforeCurrentEpochWritePeer extends QuorumPeer {
        CrashBeforeCurrentEpochWritePeer() throws javax.security.sasl.SaslException {
            super();
        }

        @Override
        void writeLongToFile(String name, long value) throws IOException {
            if (CURRENT_EPOCH_FILENAME.equals(name) && value >= crashOnEpoch) {
                // Simulated crash point: nothing of the currentEpoch file (nor its .tmp) gets written.
                crashed.countDown();
                throw new IOException("Simulated crash before writing " + name + "=" + value);
            }
            super.writeLongToFile(name, value);
        }
    }

    static class CrashingQPMain extends TestQPMain {
        @Override
        protected QuorumPeer getQuorumPeer() throws javax.security.sasl.SaslException {
            return new CrashBeforeCurrentEpochWritePeer();
        }
    }

    static class RecordingQPMain extends TestQPMain {
        final AtomicReference<Throwable> startupFailure = new AtomicReference<>();
        final CountDownLatch done = new CountDownLatch(1);

        @Override
        public void runFromConfig(QuorumPeerConfig config) throws IOException, AdminServerException {
            try {
                super.runFromConfig(config);
            } catch (RuntimeException e) {
                startupFailure.set(e);
                throw e;
            } finally {
                done.countDown();
            }
        }
    }

    @Test
    @Timeout(value = 180)
    public void testFollowerCrashBetweenSyncPersistAndCurrentEpochWrite() throws Exception {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < SERVER_COUNT; i++) {
            clientPorts[i] = PortAssignment.unique();
            sb.append("server.").append(i).append("=127.0.0.1:").append(PortAssignment.unique()).append(":")
              .append(PortAssignment.unique()).append(":participant;127.0.0.1:").append(clientPorts[i]).append("\n");
        }
        String cfg = sb.toString();

        // 1. Start servers 0 and 1 (quorum of 3), epoch 1. Server 2 joins later with the
        //    "crash" hook installed, but the hook is not armed yet.
        mt[0] = new MainThread(0, clientPorts[0], cfg, false);
        mt[1] = new MainThread(1, clientPorts[1], cfg, false);
        mt[2] = new MainThread(2, clientPorts[2], cfg, false) {
            @Override
            public TestQPMain getTestQPMain() {
                return new CrashingQPMain();
            }
        };
        for (MainThread m : mt) {
            m.start();
        }
        for (int i = 0; i < SERVER_COUNT; i++) {
            assertTrue(ClientBase.waitForServerUp("127.0.0.1:" + clientPorts[i], CONNECTION_TIMEOUT));
        }
        write(clientPorts[0], "/epoch1");
        long epochBefore = mt[2].getQuorumPeer().getCurrentEpoch();
        LOG.info("server 2 currentEpoch = {}", epochBefore);

        // 2. Server 2 goes down (e.g. maintenance / network partition / crash).
        mt[2].shutdown();
        assertTrue(ClientBase.waitForServerDown("127.0.0.1:" + clientPorts[2], CONNECTION_TIMEOUT));

        // 3. Servers 0 and 1 restart -> a new epoch is established without server 2,
        //    and clients write data in that new epoch.
        mt[0].shutdown();
        mt[1].shutdown();
        mt[0].start();
        mt[1].start();
        assertTrue(ClientBase.waitForServerUp("127.0.0.1:" + clientPorts[0], CONNECTION_TIMEOUT));
        assertTrue(ClientBase.waitForServerUp("127.0.0.1:" + clientPorts[1], CONNECTION_TIMEOUT));
        write(clientPorts[0], "/epoch2a");
        write(clientPorts[1], "/epoch2b");
        long newEpoch = Math.max(mt[0].getQuorumPeer().getCurrentEpoch(), mt[1].getQuorumPeer().getCurrentEpoch());
        LOG.info("new ensemble epoch = {}", newEpoch);
        assertTrue(newEpoch > epochBefore);

        // 4. Server 2 comes back. While syncing with the leader it persists the new-epoch
        //    txns, then crashes right before it writes currentEpoch = newEpoch.
        crashOnEpoch = newEpoch;
        mt[2].start();
        assertTrue(crashed.await(CONNECTION_TIMEOUT, TimeUnit.MILLISECONDS), "crash point not reached");
        mt[2].shutdown(); // the process is dead

        File snapDir = mt[2].getQuorumPeer() == null ? null : mt[2].getQuorumPeer().getTxnFactory().getSnapDir();
        if (snapDir != null) {
            File tmp = new File(snapDir, QuorumPeer.CURRENT_EPOCH_FILENAME + AtomicFileOutputStream.TMP_EXTENSION);
            LOG.info("after crash: currentEpoch.tmp exists = {}", tmp.exists());
        }

        // 5. Operator restarts server 2 normally (no fault injection anymore).
        RecordingQPMain restarted = new RecordingQPMain();
        mt[2].start(restarted);
        boolean up = ClientBase.waitForServerUp("127.0.0.1:" + clientPorts[2], CONNECTION_TIMEOUT);
        Throwable failure = restarted.startupFailure.get();
        if (failure != null) {
            throw new AssertionError("server 2 cannot restart after crashing during sync (epoch "
                    + newEpoch + " data on disk, currentEpoch file = " + epochBefore + ")", failure);
        }
        assertTrue(up, "server 2 did not come up");
        assertEquals(newEpoch, mt[2].getQuorumPeer().getCurrentEpoch());
        LOG.info("zxid {}", ZxidUtils.zxidToString(mt[2].getQuorumPeer().getLastLoggedZxid()));
    }

    private void write(int port, String path) throws Exception {
        ZooKeeper zk = ClientBase.createZKClient("127.0.0.1:" + port);
        try {
            zk.create(path, "data".getBytes(), Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        } finally {
            zk.close();
        }
    }
}
