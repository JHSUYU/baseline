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
import static org.junit.jupiter.api.Assertions.fail;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import javax.security.sasl.SaslException;
import org.apache.zookeeper.PortAssignment;
import org.apache.zookeeper.test.ClientBase;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

/**
 * Leader-side counterpart of ZOOKEEPER-2307.
 *
 * In Leader.getEpochToPropose() the thread that completes the quorum first sets
 * waitingForNewEpoch=false and only then persists the new acceptedEpoch. If that
 * thread is a LearnerHandler and the disk write fails transiently, only the
 * handler dies; the leader thread (waiting in the same method) times out, sees
 * waitingForNewEpoch == false, proceeds with the new epoch and persists it as
 * currentEpoch. The leader's disk now has acceptedEpoch < currentEpoch, and the
 * next restart of that server fails in QuorumPeer.loadDataBase().
 */
public class LeaderAcceptedEpochWriteFailureTest extends QuorumPeerTestBase {

    private static final int SERVER_COUNT = 3;
    private final MainThread[] mt = new MainThread[SERVER_COUNT + 1];

    /** Fails exactly one acceptedEpoch write performed by a LearnerHandler thread (transient disk error). */
    static class FaultyDiskQuorumPeer extends QuorumPeer {
        final AtomicBoolean injected = new AtomicBoolean(false);
        final CountDownLatch faultInjected = new CountDownLatch(1);

        FaultyDiskQuorumPeer() throws SaslException {
            super();
        }

        @Override
        void writeLongToFile(String name, long value) throws IOException {
            if (ACCEPTED_EPOCH_FILENAME.equals(name) && value > 0
                && Thread.currentThread().getName().startsWith("LearnerHandler")
                && injected.compareAndSet(false, true)) {
                LOG.info("Injecting transient I/O error while writing {}={}", name, value);
                faultInjected.countDown();
                throw new IOException("Input/output error (injected, transient)");
            }
            super.writeLongToFile(name, value);
        }
    }

    static class FaultyQPMain extends TestQPMain {
        volatile FaultyDiskQuorumPeer peer;

        @Override
        protected QuorumPeer getQuorumPeer() throws SaslException {
            peer = new FaultyDiskQuorumPeer();
            return peer;
        }
    }

    /** Records the exception that makes the (restarted) server fail to start. */
    static class RecordingQPMain extends TestQPMain {
        final AtomicReference<Throwable> failure = new AtomicReference<>();
        final CountDownLatch done = new CountDownLatch(1);

        @Override
        protected void initializeAndRun(String[] args) throws org.apache.zookeeper.common.ConfigException,
            IOException, org.apache.zookeeper.server.admin.AdminServer.AdminServerException {
            try {
                super.initializeAndRun(args);
            } catch (RuntimeException | IOException e) {
                failure.set(e);
                throw e;
            } finally {
                done.countDown();
            }
        }
    }

    private static long readEpoch(File snapDir, String name) throws IOException {
        return Long.parseLong(new String(Files.readAllBytes(new File(snapDir, name).toPath()), StandardCharsets.UTF_8).trim());
    }

    @Test
    @Timeout(value = 180)
    public void testLeaderRestartFailsAfterTransientAcceptedEpochWriteFailure() throws Exception {
        ClientBase.setupTestEnv();
        int[] clientPorts = new int[SERVER_COUNT + 1];
        StringBuilder sb = new StringBuilder();
        for (int i = 1; i <= SERVER_COUNT; i++) {
            clientPorts[i] = PortAssignment.unique();
            sb.append("server." + i + "=127.0.0.1:" + PortAssignment.unique() + ":" + PortAssignment.unique()
                      + ";" + clientPorts[i] + "\n");
        }
        String quorumCfgSection = sb.toString();
        // shorter tickTime so that the leader's wait in getEpochToPropose() times out quickly
        String extraCfg = "tickTime=1000\n";

        // server 3 (highest sid) will become leader; its disk has a transient write error.
        mt[3] = new MainThread(3, clientPorts[3], quorumCfgSection, extraCfg);
        FaultyQPMain faultyMain = new FaultyQPMain();
        mt[3].start(faultyMain);
        // servers 1 and 2 are normal followers
        for (int i = 1; i <= 2; i++) {
            mt[i] = new MainThread(i, clientPorts[i], quorumCfgSection, extraCfg);
            mt[i].start();
        }

        for (int i = 1; i <= SERVER_COUNT; i++) {
            assertTrue(ClientBase.waitForServerUp("127.0.0.1:" + clientPorts[i], CONNECTION_TIMEOUT * 3),
                       "server " + i + " should come up");
        }

        FaultyDiskQuorumPeer leaderPeer = faultyMain.peer;
        assertTrue(leaderPeer.faultInjected.await(0, TimeUnit.SECONDS), "fault must have been injected");
        assertEquals(QuorumPeer.ServerState.LEADING, leaderPeer.getPeerState(), "server 3 must be leader");

        File snapDir = leaderPeer.getTxnFactory().getSnapDir();
        long acceptedOnDisk = readEpoch(snapDir, QuorumPeer.ACCEPTED_EPOCH_FILENAME);
        long currentOnDisk = readEpoch(snapDir, QuorumPeer.CURRENT_EPOCH_FILENAME);
        LOG.info("Leader established epoch; on disk acceptedEpoch={} currentEpoch={}", acceptedOnDisk, currentOnDisk);
        System.out.println("Leader on-disk acceptedEpoch=" + acceptedOnDisk + " currentEpoch=" + currentOnDisk);

        // The leader now crashes / is restarted (e.g. rolling restart).
        mt[3].shutdown();
        mt[3].join(10000);

        RecordingQPMain restartMain = new RecordingQPMain();
        mt[3].start(restartMain);
        // done only counts down if the server stops (e.g. fails to start)
        restartMain.done.await(30, TimeUnit.SECONDS);
        Throwable t = restartMain.failure.get();
        if (t != null) {
            System.out.println("Restarted leader failed to start:");
            t.printStackTrace(System.out);
            fail("Server 3 cannot restart: its own leader election persisted acceptedEpoch="
                 + acceptedOnDisk + " < currentEpoch=" + currentOnDisk, t);
        }
        assertTrue(ClientBase.waitForServerUp("127.0.0.1:" + clientPorts[3], CONNECTION_TIMEOUT),
                   "server 3 should restart");
    }

    @AfterEach
    public void tearDown() throws InterruptedException {
        for (MainThread m : mt) {
            if (m != null) {
                m.shutdown();
            }
        }
    }
}
