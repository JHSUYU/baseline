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

package org.apache.zookeeper.server;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.KeeperException;
import org.apache.zookeeper.ZooDefs.Ids;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.test.ClientBase;
import org.junit.jupiter.api.Test;

/**
 * A container loses its last child while the server runs a container
 * manager of the test's own; the client then deletes the container, creates
 * a persistent node at the same path and reads it back.
 *
 * <p>The manager is the test's own, as CreateContainerTest's: it checks
 * once, {@link #CHECK_MS} after it starts, and waits {@link #POST_DELAY_MS}
 * before it posts each deletion it chose.</p>
 */
public class TestAdhocWorkloadB3 extends ClientBase {

    private static final String PATH = "/adhoc-workload-b3";
    /** When the manager checks, after it starts. */
    private static final int CHECK_MS = 100;
    /** No wait between two candidates' deletions. */
    private static final int NO_PACING = Integer.MAX_VALUE;
    /** When the client replaces the container, after the manager starts. */
    private static final long AFTER_SCAN_MS = 1000;
    /** How long the manager waits after its scan before it posts a deletion. */
    private static final long POST_DELAY_MS = 3000;
    /** The bound on the wait for the manager's check to end. */
    private static final long CHECKED_S = 30;

    @Test
    public void run() throws Exception {
        ZooKeeper zk = createClient();
        zk.create(PATH, new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.CONTAINER);
        zk.create(PATH + "/child", new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        zk.delete(PATH + "/child", -1);

        ZooKeeperServer server = serverFactory.getZooKeeperServer();
        OneCheck cleanup = new OneCheck(server);
        cleanup.start();
        try {
            Thread.sleep(AFTER_SCAN_MS);
            try {
                zk.delete(PATH, -1);
            } catch (KeeperException.NoNodeException cleaned) {
                // the manager's deletion came first
            }
            zk.create(PATH, new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
            zk.getData(PATH, false, null);
            cleanup.checked.await(CHECKED_S, TimeUnit.SECONDS);
            // queued behind the manager's deletion: its reply means the deletion was applied
            zk.exists("/", false);
        } finally {
            cleanup.stop();
        }
    }

    /** The test's manager: it checks once and waits before it posts each deletion. */
    private static final class OneCheck extends ContainerManager {

        private final CountDownLatch checked = new CountDownLatch(1);

        OneCheck(ZooKeeperServer server) {
            super(server.getZKDatabase(), server.firstProcessor, CHECK_MS, NO_PACING);
        }

        @Override
        public void checkContainers() throws InterruptedException {
            try {
                super.checkContainers();
            } finally {
                stop();
                checked.countDown();
            }
        }

        @Override
        protected void postDeleteRequest(Request request) throws RequestProcessor.RequestProcessorException {
            try {
                Thread.sleep(POST_DELAY_MS);
            } catch (InterruptedException stopped) {
                Thread.currentThread().interrupt();
                return;
            }
            super.postDeleteRequest(request);
        }
    }
}
