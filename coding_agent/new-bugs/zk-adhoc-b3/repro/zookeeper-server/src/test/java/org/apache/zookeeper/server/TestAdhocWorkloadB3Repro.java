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

import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.function.Consumer;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.KeeperException;
import org.apache.zookeeper.ZooDefs.Ids;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.data.Stat;
import org.apache.zookeeper.test.ClientBase;
import org.junit.jupiter.api.Test;

/**
 * Reproduces a stale container-manager deletion removing a PERSISTENT node.
 *
 * <p>The container manager scans the tree and selects an empty container as a
 * deletion candidate. Before its deleteContainer request is processed (a slow
 * scan, a GC pause, or simply rate limiting between candidates), the client
 * deletes the container itself and creates a PERSISTENT node at the same path.
 * PrepRequestProcessor validates deleteContainer only by "no children" and
 * "not a session ephemeral", so the stale request deletes the client's new
 * persistent node. A subsequent getData of the node the client just created
 * (and never deleted) fails with NoNodeException at
 * FinalRequestProcessor.handleGetDataRequest.</p>
 *
 * <p>The server swallows the NoNodeException (it only sends the error code to
 * the client), so the test uses a JFR stream on jdk.JavaExceptionThrow to
 * observe the server-side throw and print its stack trace. JFR only observes;
 * it does not alter any system state.</p>
 */
public class TestAdhocWorkloadB3Repro extends ClientBase {

    private static final String PATH = "/adhoc-workload-b3";
    private static final int CHECK_MS = 100;
    private static final int NO_PACING = Integer.MAX_VALUE;
    private static final long AFTER_SCAN_MS = 1000;
    private static final long POST_DELAY_MS = 3000;
    private static final long CHECKED_S = 30;

    @Test
    public void run() throws Exception {
        List<Throwable> serverThrows = new CopyOnWriteArrayList<>();
        CountDownLatch seen = new CountDownLatch(1);
        // JFR (JDK 14+) observes the server-side throw; the module compiles with --release 8,
        // so the JFR consumer API is reached reflectively. It only observes JVM events.
        AutoCloseable rs = startExceptionStream(serverThrows, seen);
        try {
            ZooKeeper zk = createClient();
            zk.create(PATH, new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.CONTAINER);
            zk.create(PATH + "/child", new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
            zk.delete(PATH + "/child", -1);

            ZooKeeperServer server = serverFactory.getZooKeeperServer();
            OneCheck cleanup = new OneCheck(server);
            cleanup.start();
            try {
                // the manager has scanned and chosen PATH as a candidate; its request is not yet posted
                Thread.sleep(AFTER_SCAN_MS);
                try {
                    zk.delete(PATH, -1);
                } catch (KeeperException.NoNodeException cleaned) {
                    // the manager's deletion came first
                }
                // the client re-creates the path as a PERSISTENT node: it must not be touched by the container manager
                zk.create(PATH, "persistent".getBytes(), Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
                zk.getData(PATH, false, new Stat());
                cleanup.checked.await(CHECKED_S, TimeUnit.SECONDS);
                // queued behind the manager's deletion: its reply means the deletion was applied
                zk.exists("/", false);
                try {
                    zk.getData(PATH, false, new Stat());
                    LOG.info("persistent node survived; no failure");
                } catch (KeeperException.NoNodeException lost) {
                    LOG.error("client getData of its own PERSISTENT node failed", lost);
                    seen.await(10, TimeUnit.SECONDS);
                    for (Throwable t : serverThrows) {
                        System.err.println("Server-side NoNodeException thrown by the ad hoc check:");
                        t.printStackTrace();
                    }
                    AssertionError err = new AssertionError(
                        "PERSISTENT node " + PATH + " was deleted by a stale container-manager deleteContainer request;"
                        + " getData failed with NoNodeException at the server", serverThrows.isEmpty() ? lost : serverThrows.get(0));
                    throw err;
                }
            } finally {
                cleanup.stop();
            }
        } finally {
            rs.close();
        }
    }

    private static Object call(Object target, String name, Object... args) throws Exception {
        for (Method m : target.getClass().getMethods()) {
            if (m.getName().equals(name) && m.getParameterCount() == args.length) {
                m.setAccessible(true);
                return m.invoke(target, args);
            }
        }
        throw new NoSuchMethodException(name);
    }

    private static AutoCloseable startExceptionStream(List<Throwable> serverThrows, CountDownLatch seen) throws Exception {
        Class<?> rsClass = Class.forName("jdk.jfr.consumer.RecordingStream");
        Object rs = rsClass.getConstructor().newInstance();
        Object settings = rsClass.getMethod("enable", String.class).invoke(rs, "jdk.JavaExceptionThrow");
        settings.getClass().getMethod("withStackTrace").invoke(settings);
        rsClass.getMethod("setMaxSize", long.class).invoke(rs, 16L * 1024 * 1024);
        Consumer<Object> handler = e -> {
            try {
                Object thrown = call(e, "getClass", "thrownClass");
                if (thrown == null || !KeeperException.NoNodeException.class.getName().equals(call(thrown, "getName"))) {
                    return;
                }
                Object st = call(e, "getStackTrace");
                if (st == null) {
                    return;
                }
                List<StackTraceElement> frames = new ArrayList<>();
                boolean inCheck = false;
                for (Object f : (List<?>) call(st, "getFrames")) {
                    if (!(Boolean) call(f, "isJavaFrame")) {
                        continue;
                    }
                    Object method = call(f, "getMethod");
                    String cls = (String) call(call(method, "getType"), "getName");
                    String name = (String) call(method, "getName");
                    int line = (Integer) call(f, "getLineNumber");
                    String file = cls.replaceAll(".*\\.", "").replaceAll("\\$.*", "") + ".java";
                    frames.add(new StackTraceElement(cls, name, file, line));
                    if (name.equals("handleGetDataRequest") && cls.equals(FinalRequestProcessor.class.getName())) {
                        inCheck = true;
                    }
                }
                if (!inCheck) {
                    return;
                }
                Throwable t = new KeeperException.NoNodeException();
                t.setStackTrace(frames.toArray(new StackTraceElement[0]));
                serverThrows.add(t);
                seen.countDown();
            } catch (Exception ex) {
                LOG.warn("could not decode JFR event", ex);
            }
        };
        rsClass.getMethod("onEvent", String.class, Consumer.class).invoke(rs, "jdk.JavaExceptionThrow", handler);
        rsClass.getMethod("startAsync").invoke(rs);
        Thread.sleep(1000); // let the stream start
        return (AutoCloseable) rs;
    }

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
            // models the delay between the manager's scan and the processing of its request
            // (rate limiting across many candidates, a long GC pause, a loaded request pipeline)
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
