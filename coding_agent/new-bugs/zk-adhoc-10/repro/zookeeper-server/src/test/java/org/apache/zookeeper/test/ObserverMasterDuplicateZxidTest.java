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

import static org.apache.zookeeper.test.ClientBase.CONNECTION_TIMEOUT;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.classic.spi.IThrowableProxy;
import ch.qos.logback.classic.spi.ThrowableProxy;
import ch.qos.logback.core.AppenderBase;
import java.io.IOException;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.apache.jute.OutputArchive;
import org.apache.jute.InputArchive;
import org.apache.jute.Record;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.TestableZooKeeper;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.ZooDefs.Ids;
import org.apache.zookeeper.ZooDefs.OpCode;
import org.apache.zookeeper.ZooKeeper.States;
import org.apache.zookeeper.proto.CreateResponse;
import org.apache.zookeeper.proto.ReplyHeader;
import org.apache.zookeeper.proto.RequestHeader;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;

/**
 * A client sends a create request whose body cannot be deserialized while an
 * earlier write of the same pipeline is still being voted on. The leader's
 * PrepRequestProcessor turns the malformed request into an error txn that is
 * stamped with zks.getZxid() (the zxid that was already handed to the previous
 * write) instead of a fresh zxid, so the leader proposes the same zxid twice
 * and commits it only once. Every follower that runs an ObserverMaster then
 * keeps the second (duplicate) proposal at the head of proposedPkts, and the
 * next COMMIT makes the ad hoc check in ObserverMaster.removeProposedPacket
 * throw "Unexpected proposal packet on commit ack".
 */
public class ObserverMasterDuplicateZxidTest extends ObserverMasterTestBase {

    private static final org.slf4j.Logger LOG = LoggerFactory.getLogger(ObserverMasterDuplicateZxidTest.class);

    /** A request body that is not a valid CreateRequest (string length way too large). */
    static class MalformedCreateBody implements Record {
        @Override
        public void serialize(OutputArchive archive, String tag) throws IOException {
            archive.startRecord(this, tag);
            archive.writeInt(Integer.MAX_VALUE, "len");
            archive.endRecord(this, tag);
        }

        @Override
        public void deserialize(InputArchive archive, String tag) throws IOException {
            throw new UnsupportedOperationException();
        }
    }

    /** A client that can pipeline a create request with a malformed body. */
    static class PipeliningZooKeeper extends TestableZooKeeper {
        PipeliningZooKeeper(String host, int sessionTimeout, org.apache.zookeeper.Watcher watcher) throws IOException {
            super(host, sessionTimeout, watcher);
        }

        void queueMalformedCreate() {
            RequestHeader h = new RequestHeader();
            h.setType(OpCode.create);
            cnxn.queuePacket(h, new ReplyHeader(), new MalformedCreateBody(), new CreateResponse(),
                    null, null, null, null, null);
        }
    }

    /** Collects all exceptions logged by the servers. */
    static class ThrowableCollector extends AppenderBase<ILoggingEvent> {
        final List<Throwable> throwables = new CopyOnWriteArrayList<>();

        @Override
        protected void append(ILoggingEvent event) {
            IThrowableProxy p = event.getThrowableProxy();
            if (p instanceof ThrowableProxy) {
                throwables.add(((ThrowableProxy) p).getThrowable());
            }
        }

        Throwable findCheckFailure() {
            for (Throwable t : throwables) {
                if (t instanceof RuntimeException && t.getStackTrace().length > 0) {
                    StackTraceElement top = t.getStackTrace()[0];
                    if (top.getClassName().equals("org.apache.zookeeper.server.quorum.ObserverMaster")
                        && top.getMethodName().equals("removeProposedPacket")) {
                        return t;
                    }
                }
            }
            return null;
        }
    }

    @Test
    public void testMalformedRequestDuplicatesZxidAndBreaksObserverMaster() throws Exception {
        ThrowableCollector collector = new ThrowableCollector();
        Logger root = (Logger) LoggerFactory.getLogger(org.slf4j.Logger.ROOT_LOGGER_NAME);
        collector.setContext(root.getLoggerContext());
        collector.start();
        root.addAppender(collector);
        try {
            setUp(-1, true);
            q3.start();
            assertTrue(ClientBase.waitForServerUp("127.0.0.1:" + CLIENT_PORT_OBS, CONNECTION_TIMEOUT),
                    "waiting for observer to be up");

            // the client talks to the leader; the followers (both run an ObserverMaster) only see the
            // PROPOSAL/COMMIT stream
            int leaderPort = q1.getQuorumPeer().leader != null ? CLIENT_PORT_QP1 : CLIENT_PORT_QP2;
            latch = new CountDownLatch(1);
            PipeliningZooKeeper client = new PipeliningZooKeeper("127.0.0.1:" + leaderPort, CONNECTION_TIMEOUT, this);
            zk = client;
            assertTrue(latch.await(CONNECTION_TIMEOUT, TimeUnit.MILLISECONDS));
            assertEquals(States.CONNECTED, client.getState());

            // some regular traffic so that we are not at the very start of the epoch
            for (int i = 0; i < 5; i++) {
                client.create("/warmup" + i, "x".getBytes(), Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
            }

            // pipeline: a large write (zxid z) immediately followed by a malformed create.
            // The large proposal takes a while to be replicated, logged and acked, so it is still
            // outstanding at the leader when the malformed request is prepared; the error txn of
            // the malformed request is then stamped with the same zxid z.
            byte[] big = new byte[900 * 1024];
            CountDownLatch bigDone = new CountDownLatch(1);
            client.create("/big", big, Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT,
                    (rc, path, ctx, name) -> {
                        LOG.info("big create {} rc={}", path, rc);
                        bigDone.countDown();
                    }, null);
            // queued right behind the large write on the same connection
            client.queueMalformedCreate();

            assertTrue(bigDone.await(30, TimeUnit.SECONDS), "large write did not complete");

            // ordinary writes afterwards from a second client: their COMMITs hit the duplicate
            // proposal left at the head of ObserverMaster.proposedPkts on every follower
            ZooKeeper other = new ZooKeeper("127.0.0.1:" + leaderPort, CONNECTION_TIMEOUT, ev -> { });
            for (int i = 0; i < 5; i++) {
                other.create("/after" + i, "x".getBytes(), Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT,
                        (rc, path, ctx, name) -> LOG.info("after-create {} rc={}", path, rc), null);
            }

            long deadline = System.currentTimeMillis() + 30000;
            Throwable failure = null;
            while (failure == null && System.currentTimeMillis() < deadline) {
                failure = collector.findCheckFailure();
                if (failure == null) {
                    Thread.sleep(100);
                }
            }
            if (failure == null) {
                fail("ObserverMaster ad hoc check did not fail");
            }
            LOG.error("Reproduced ObserverMaster.removeProposedPacket check failure", failure);
            failure.printStackTrace(System.out);
            // surface the check failure as the test failure
            throw new AssertionError("ObserverMaster.removeProposedPacket rejected a commit", failure);
        } finally {
            root.detachAppender(collector);
            try {
                shutdown();
            } catch (Throwable t) {
                LOG.warn("shutdown", t);
            }
        }
    }
}
