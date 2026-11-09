/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package org.apache.zookeeper.recipes.leader;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.lang.management.ManagementFactory;
import java.nio.charset.StandardCharsets;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.management.MBeanServer;
import javax.management.ObjectName;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.KeeperException;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.recipes.leader.LeaderElectionSupport.EventType;
import org.apache.zookeeper.test.ClientBase;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Reproduces a race in {@link LeaderElectionSupport}: a candidate lists the
 * leader offers with getChildren() and then reads every offer with getData().
 * If another candidate (here: the current leader) crashes between those two
 * calls, its ephemeral offer disappears, the server rejects the getData() with
 * NoNodeException (FinalRequestProcessor.handleGetDataRequest) and the surviving
 * candidate ends up FAILED instead of becoming the leader.
 */
public class LeaderElectionSupportCrashRaceTest extends ClientBase {

    private static final Logger LOG = LoggerFactory.getLogger(LeaderElectionSupportCrashRaceTest.class);

    private String root;
    private ZooKeeper adminZk;

    /** A plain ZooKeeper client that runs a hook right after the first getChildren(path, boolean) returns. */
    static class HookedZooKeeper extends ZooKeeper {
        volatile Runnable afterGetChildren;

        HookedZooKeeper(String connectString, int timeout, CountdownWatcher w) throws IOException {
            super(connectString, timeout, w);
        }

        @Override
        public List<String> getChildren(String path, boolean watch) throws KeeperException, InterruptedException {
            List<String> children = super.getChildren(path, watch);
            Runnable hook = afterGetChildren;
            afterGetChildren = null;
            if (hook != null) {
                hook.run();
            }
            return children;
        }
    }

    @BeforeEach
    public void setUp() throws Exception {
        super.setUp();
        adminZk = createClient();
        root = "/election_" + System.currentTimeMillis();
        adminZk.create(root, new byte[0], ZooDefs.Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
    }

    @AfterEach
    public void tearDown() throws Exception {
        if (adminZk != null) {
            adminZk.close();
        }
        super.tearDown();
    }

    private LeaderElectionSupport candidate(ZooKeeper zk, String host, List<EventType> events) {
        LeaderElectionSupport s = new LeaderElectionSupport();
        s.setZooKeeper(zk);
        s.setRootNodeName(root);
        s.setHostName(host);
        s.addListener(events::add);
        return s;
    }

    @Test
    public void testLeaderCrashBetweenGetChildrenAndGetData() throws Exception {
        // Observe (not alter) the server: record exception-throw events with stack traces via JFR.
        Path jfc = Files.createTempFile("adhoc-exc", ".jfc");
        Files.write(jfc, ("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            + "<configuration version=\"2.0\">\n"
            + "  <event name=\"jdk.JavaExceptionThrow\">\n"
            + "    <setting name=\"enabled\">true</setting>\n"
            + "    <setting name=\"stackTrace\">true</setting>\n"
            + "  </event>\n"
            + "</configuration>\n").getBytes(StandardCharsets.UTF_8));
        String recName = "adhoc-" + System.nanoTime();
        jfrCmd("jfrStart", "name=" + recName, "settings=" + jfc);

        // Candidate A: its own client/session (its own process in a real deployment).
        ZooKeeper zkA = createClient();
        List<EventType> eventsA = Collections.synchronizedList(new ArrayList<>());
        LeaderElectionSupport a = candidate(zkA, "hostA", eventsA);
        a.start();
        assertTrue(eventsA.contains(EventType.ELECTED_COMPLETE), "A should be the leader: " + eventsA);

        // Candidate B: its own client/session.
        CountdownWatcher wB = new CountdownWatcher();
        HookedZooKeeper zkB = new HookedZooKeeper(hostPort, CONNECTION_TIMEOUT, wB);
        wB.waitForConnected(CONNECTION_TIMEOUT);
        List<EventType> eventsB = Collections.synchronizedList(new ArrayList<>());
        LeaderElectionSupport b = candidate(zkB, "hostB", eventsB);

        // Right after B has listed the offers (which still include A's), A's process crashes:
        // its session goes away (simulated by closing the session from another thread) and
        // the server removes A's ephemeral offer.
        AtomicBoolean crashed = new AtomicBoolean();
        zkB.afterGetChildren = () -> {
            CountDownLatch done = new CountDownLatch(1);
            Thread crash = new Thread(() -> {
                try {
                    LOG.info("Crashing leader candidate A (closing its session)");
                    zkA.close();
                    crashed.set(true);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                } finally {
                    done.countDown();
                }
            }, "crash-A");
            crash.start();
            try {
                done.await(30, TimeUnit.SECONDS);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        };

        b.start();
        assertTrue(crashed.get(), "A should have crashed during B's determination");

        Path jfr = Files.createTempFile("adhoc-nonode", ".jfr");
        jfrCmd("jfrDump", "name=" + recName, "filename=" + jfr);
        jfrCmd("jfrStop", "name=" + recName);
        Throwable serverSide = findServerSideNoNode(jfr);
        Files.deleteIfExists(jfr);
        Files.deleteIfExists(jfc);

        System.out.println("Events of candidate B: " + eventsB);
        if (serverSide != null) {
            System.out.println("Server-side NoNodeException captured by JFR (jdk.JavaExceptionThrow):");
            serverSide.printStackTrace(System.out);
        }
        zkB.close();

        // Expected (correct) outcome: A is gone, so B is the only candidate and must be elected.
        if (!eventsB.contains(EventType.ELECTED_COMPLETE) || eventsB.contains(EventType.FAILED)) {
            fail("Candidate B must become leader after leader A crashed, but B's events were " + eventsB
                + " (its getData on A's vanished offer was rejected by the server with NoNodeException)", serverSide);
        }
    }

    private static void jfrCmd(String op, String... args) throws Exception {
        MBeanServer mbs = ManagementFactory.getPlatformMBeanServer();
        ObjectName dcmd = new ObjectName("com.sun.management:type=DiagnosticCommand");
        Object out = mbs.invoke(dcmd, op, new Object[]{args}, new String[]{String[].class.getName()});
        LOG.info("{} {} -> {}", op, String.join(" ", args), out);
    }

    private static final Pattern FRAME = Pattern.compile("^\\s*([\\w$.]+)\\.([\\w<>$]+)\\(.*\\)\\s+line:\\s+(-?\\d+)");

    /**
     * Decodes the JFR recording with the JDK's jfr tool and rebuilds the stack trace of the
     * NoNodeException thrown in FinalRequestProcessor.handleGetDataRequest (the ad hoc check).
     */
    private static Throwable findServerSideNoNode(Path jfr) throws Exception {
        String jfrTool = Paths.get(System.getProperty("java.home"), "bin", "jfr").toString();
        Process p = new ProcessBuilder(jfrTool, "print", "--events", "jdk.JavaExceptionThrow",
            "--stack-depth", "64", jfr.toString()).redirectErrorStream(true).start();
        List<String> blocks = new ArrayList<>();
        StringBuilder cur = null;
        try (BufferedReader r = new BufferedReader(new InputStreamReader(p.getInputStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = r.readLine()) != null) {
                if (line.startsWith("jdk.JavaExceptionThrow")) {
                    if (cur != null) {
                        blocks.add(cur.toString());
                    }
                    cur = new StringBuilder();
                }
                if (cur != null) {
                    cur.append(line).append('\n');
                }
            }
        }
        if (cur != null) {
            blocks.add(cur.toString());
        }
        p.waitFor();
        for (String block : blocks) {
            if (!block.contains("KeeperException$NoNodeException")
                || !block.contains("org.apache.zookeeper.server.FinalRequestProcessor.handleGetDataRequest(")) {
                continue;
            }
            System.out.println("Raw JFR event:\n" + block);
            List<StackTraceElement> elems = new ArrayList<>();
            for (String l : block.split("\n")) {
                Matcher m = FRAME.matcher(l);
                if (m.find()) {
                    String cls = m.group(1);
                    String simple = cls.substring(cls.lastIndexOf('.') + 1);
                    int dollar = simple.indexOf('$');
                    String file = (dollar >= 0 ? simple.substring(0, dollar) : simple) + ".java";
                    elems.add(new StackTraceElement(cls, m.group(2), file, Integer.parseInt(m.group(3))));
                }
            }
            Throwable t = new KeeperException.NoNodeException();
            t.setStackTrace(elems.toArray(new StackTraceElement[0]));
            return t;
        }
        return null;
    }
}
