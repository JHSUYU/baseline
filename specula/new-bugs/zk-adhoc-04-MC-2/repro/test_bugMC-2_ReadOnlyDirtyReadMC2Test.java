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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentSkipListMap;
import java.util.concurrent.atomic.AtomicBoolean;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.KeeperException;
import org.apache.zookeeper.PortAssignment;
import org.apache.zookeeper.ZKTestCase;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.ZooKeeper.States;
import org.apache.zookeeper.client.FourLetterWordMain;
import org.apache.zookeeper.common.Time;
import org.apache.zookeeper.data.Stat;
import org.apache.zookeeper.test.ClientBase.CountdownWatcher;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

/**
 * MC-2 reproduction: a variant of ReadOnlyModeTest#testSeekForRwServer.
 *
 * Only public client calls, QuorumUtil start/stop and the workload's own
 * setSuspended are used. Nothing writes lastZxidSeen, lastProcessedZxid, or
 * the data tree, and no production source is changed.
 */
public class ReadOnlyDirtyReadMC2Test extends ZKTestCase {

    private static final int CONNECTION_TIMEOUT = QuorumBase.CONNECTION_TIMEOUT;
    private static final String PREFIX = "/inflight-";
    private static final String REFUSAL = "client must try another server";
    private static final int PENDING = Integer.MIN_VALUE;

    static {
        // Other JVMs on this host share PortAssignment's default range; start at a random offset within it.
        int skip = 500 + new java.util.Random().nextInt(2500);
        for (int i = 0; i < skip; i++) {
            PortAssignment.unique();
        }
    }

    private final QuorumUtil qu = new QuorumUtil(1);

    @BeforeEach
    public void setUp() {
        System.setProperty("readonlymode.enabled", "true");
    }

    @AfterEach
    public void tearDown() throws Exception {
        System.setProperty("readonlymode.enabled", "false");
        for (int i = 1; i <= qu.ALL; i++) {
            if (qu.getPeer(i).peer != null) {
                qu.getPeer(i).peer.setSuspended(false);
            }
        }
        qu.tearDown();
    }

    private static void report(String fmt, Object... args) {
        System.out.println("MC2-REPRO " + String.format(fmt, args));
    }

    private String addr(int sid) {
        return "127.0.0.1:" + qu.getPeer(sid).clientPort;
    }

    /** The faults of the counterexample: a follower stops while a write is in flight at the leader. */
    private List<Integer> writeWhileStopping(ZooKeeper zk, int stopSid) throws Exception {
        Map<Integer, Integer> rcs = new ConcurrentSkipListMap<>();
        AtomicBoolean lost = new AtomicBoolean();
        Thread stopper = new Thread(() -> qu.shutdown(stopSid));
        stopper.start();
        long deadline = Time.currentElapsedTime() + 20000;
        for (int i = 0; !lost.get() && Time.currentElapsedTime() < deadline; i++) {
            final int k = i;
            rcs.put(k, PENDING);
            zk.create(PREFIX + k, ("uncommitted-" + k).getBytes(), ZooDefs.Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT,
                (rc, path, ctx, name) -> {
                    rcs.put(k, rc);
                    if (rc != 0) {
                        lost.set(true);
                    }
                }, null);
            Thread.sleep(5);
        }
        stopper.join();
        while (rcs.containsValue(PENDING) && Time.currentElapsedTime() < deadline + 30000) {
            Thread.sleep(50);
        }
        List<Integer> unacked = new ArrayList<>();
        for (Map.Entry<Integer, Integer> e : rcs.entrySet()) {
            if (e.getValue() != 0) {
                unacked.add(e.getKey());
            }
        }
        report("writes sent=%d acknowledged=%d not-acknowledged=%d", rcs.size(), rcs.size() - unacked.size(), unacked.size());
        return unacked;
    }

    private void waitForReadOnly(int sid) throws Exception {
        long deadline = Time.currentElapsedTime() + 30000;
        while (Time.currentElapsedTime() < deadline) {
            try {
                if ("ro\n".equals(FourLetterWordMain.send4LetterWord("127.0.0.1", qu.getPeer(sid).clientPort, "isro"))) {
                    report("sid %d answers isro=ro (read-only server over the fast-forwarded tree)", sid);
                    return;
                }
            } catch (Exception e) {
                // server is between roles
            }
            Thread.sleep(100);
        }
        throw new AssertionError("sid " + sid + " never became read-only");
    }

    /** Reads every unacknowledged write back through the read-only server and returns those visible. */
    private List<Integer> readDirty(ZooKeeper reader, List<Integer> unacked) throws Exception {
        List<Integer> visible = new ArrayList<>();
        String last = null;
        for (int k : unacked) {
            Stat stat = reader.exists(PREFIX + k, false);
            if (stat != null) {
                visible.add(k);
                byte[] data = reader.getData(PREFIX + k, false, null);
                last = String.format("%s%d data=%s czxid=0x%s state=%s", PREFIX, k, new String(data),
                    Long.toHexString(stat.getCzxid()), reader.getState());
                if (visible.size() == 1) {
                    report("RO READ first %s", last);
                }
            }
        }
        report("RO READ last  %s ; unacknowledged writes visible=%d", last, visible.size());
        return visible;
    }

    private void waitForRefusal(ByteArrayOutputStream log, long timeoutMs) throws Exception {
        long deadline = Time.currentElapsedTime() + timeoutMs;
        while (!log.toString().contains(REFUSAL)) {
            assertTrue(Time.currentElapsedTime() < deadline, "server never refused the client");
            Thread.sleep(100);
        }
    }

    private static int refusalCount(ByteArrayOutputStream log) {
        return log.toString().split(REFUSAL, -1).length - 1;
    }

    /**
     * The finding's headline, on the route_S2 order: the old leader's read-only
     * server serves a logged-only txn, and a follower of the next epoch refuses
     * the reader. The txn is never committed.
     */
    @Test
    @Timeout(value = 200)
    public void testDirtyReadThenNextEpochFollowerRefuses() throws Exception {
        qu.enableLocalSession(true);
        qu.startQuorum();
        qu.start(3);
        assertTrue(ClientBase.waitForServerUp(addr(3), CONNECTION_TIMEOUT));

        try (LoggerTestTool tool = new LoggerTestTool("org.apache.zookeeper")) {
            ByteArrayOutputStream log = tool.getOutputStream();
            int leader = qu.getLeaderServer();
            int[] followers = new int[2];
            for (int sid = 1, n = 0; sid <= 3; sid++) {
                if (sid != leader) {
                    followers[n++] = sid;
                }
            }
            int next = followers[0];
            int last = followers[1];
            report("leader=%d, stopping follower %d, then follower %d under write load", leader, next, last);

            CountdownWatcher w = new CountdownWatcher();
            ZooKeeper writer = new ZooKeeper(addr(leader), CONNECTION_TIMEOUT, w, false);
            w.waitForConnected(CONNECTION_TIMEOUT);
            writer.create("/committed", "ok".getBytes(), ZooDefs.Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);

            qu.shutdown(next);
            List<Integer> unacked = writeWhileStopping(writer, last);
            writer.close();

            waitForReadOnly(leader);
            CountdownWatcher rw = new CountdownWatcher();
            ZooKeeper reader = new ZooKeeper(addr(leader) + "," + addr(next), CONNECTION_TIMEOUT, rw, true);
            rw.waitForReadOnlyConnected(CONNECTION_TIMEOUT);
            assertEquals(States.CONNECTEDREADONLY, reader.getState());
            List<Integer> seen = readDirty(reader, unacked);
            assertFalse(seen.isEmpty(), "no unacknowledged write was visible at the read-only server");

            // The old leader stops; the two followers form the next epoch without it.
            qu.shutdown(leader);
            log.reset();
            qu.start(next);
            qu.start(last);
            assertTrue(ClientBase.waitForServerUp(addr(next), CONNECTION_TIMEOUT));
            assertTrue(ClientBase.waitForServerUp(addr(last), CONNECTION_TIMEOUT));
            int newLeader = qu.getLeaderServer();
            report("next epoch formed: leader=%d follower=%d follower-role=%s", newLeader, next, qu.getPeer(next).peer.getPeerState());
            assertEquals(last, newLeader);

            waitForRefusal(log, 60000);
            report("REFUSED at the next-epoch follower: reader.state=%s", reader.getState());
            assertFalse(reader.getState().isConnected());

            // A client with no history shows what the ensemble actually holds.
            CountdownWatcher fw = new CountdownWatcher();
            ZooKeeper fresh = new ZooKeeper(addr(next) + "," + addr(last), CONNECTION_TIMEOUT, fw, false);
            fw.waitForConnected(CONNECTION_TIMEOUT);
            assertNotNull(fresh.exists("/committed", false));
            List<Integer> dirty = new ArrayList<>();
            for (int k : seen) {
                if (fresh.exists(PREFIX + k, false) == null) {
                    dirty.add(k);
                }
            }
            report("seen at read-only server=%d ; absent from the next epoch=%d", seen.size(), dirty.size());
            assertFalse(dirty.isEmpty(), "every txn the read-only server showed was committed after all");

            // Without a new write the refusal continues.
            int before = refusalCount(log);
            Thread.sleep(6000);
            report("refusals during 6s with no write in the new epoch: %d, reader.state=%s", refusalCount(log) - before, reader.getState());
            assertFalse(reader.getState().isConnected());

            // Any write in the new epoch moves the follower past the client's zxid.
            fresh.create("/recover", "x".getBytes(), ZooDefs.Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
            fresh.close();
            rw.waitForConnected(CONNECTION_TIMEOUT);
            int d = dirty.get(0);
            assertNull(reader.exists(PREFIX + d, false));
            report("after one new-epoch write the reader reconnects, state=%s; %s%d it read earlier is now NoNode", reader.getState(), PREFIX, d);
            reader.close();

            // The old leader rejoins and truncates; no server retains the txn.
            qu.start(leader);
            assertTrue(ClientBase.waitForServerUp(addr(leader), CONNECTION_TIMEOUT));
            CountdownWatcher ow = new CountdownWatcher();
            ZooKeeper old = new ZooKeeper(addr(leader), CONNECTION_TIMEOUT, ow, false);
            ow.waitForConnected(CONNECTION_TIMEOUT);
            assertNull(old.exists(PREFIX + d, false));
            report("old leader sid %d rejoined as %s and no longer has %s%d", leader, qu.getPeer(leader).peer.getPeerState(), PREFIX, d);
            old.close();
        }
    }

    /**
     * The other path the finding names: restart replay. The old leader restarts
     * alone, replays its whole log, and serves the logged-only txn read-only.
     */
    @Test
    @Timeout(value = 200)
    public void testRestartReplayServesLoggedTxn() throws Exception {
        qu.enableLocalSession(true);
        qu.startQuorum();
        qu.start(3);
        assertTrue(ClientBase.waitForServerUp(addr(3), CONNECTION_TIMEOUT));

        int leader = qu.getLeaderServer();
        int[] followers = new int[2];
        for (int sid = 1, n = 0; sid <= 3; sid++) {
            if (sid != leader) {
                followers[n++] = sid;
            }
        }
        CountdownWatcher w = new CountdownWatcher();
        ZooKeeper writer = new ZooKeeper(addr(leader), CONNECTION_TIMEOUT, w, false);
        w.waitForConnected(CONNECTION_TIMEOUT);
        qu.shutdown(followers[0]);
        List<Integer> unacked = writeWhileStopping(writer, followers[1]);
        writer.close();

        qu.shutdown(leader);
        qu.start(leader);
        waitForReadOnly(leader);
        CountdownWatcher rw = new CountdownWatcher();
        ZooKeeper reader = new ZooKeeper(addr(leader), CONNECTION_TIMEOUT, rw, true);
        rw.waitForReadOnlyConnected(CONNECTION_TIMEOUT);
        List<Integer> seen = readDirty(reader, unacked);
        report("after restart the read-only server shows %d unacknowledged writes", seen.size());
        assertFalse(seen.isEmpty(), "restart replay did not expose a logged-only txn");
        reader.close();
    }

    /**
     * The hunt counterexample: sid 1 stays in the workload's suspended state,
     * read-only and FOLLOWING; the reader moves there when the old leader's
     * read-only server stops on winning the next election.
     */
    @Test
    @Timeout(value = 200)
    public void testHuntCounterexampleSuspendedReadOnlyPeerRefuses() throws Exception {
        qu.enableLocalSession(true);
        qu.startQuorum();

        try (LoggerTestTool tool = new LoggerTestTool("org.apache.zookeeper")) {
            ByteArrayOutputStream log = tool.getOutputStream();

            // Workload prefix, as in testSeekForRwServer.
            qu.shutdown(2);
            CountdownWatcher watcher = new CountdownWatcher();
            ZooKeeper zk = new ZooKeeper(qu.getConnString(), CONNECTION_TIMEOUT, watcher, true);
            watcher.waitForConnected(CONNECTION_TIMEOUT);
            qu.getPeer(1).peer.setSuspended(true);
            watcher.reset();
            qu.start(2);
            qu.start(3);
            ClientBase.waitForServerUp(qu.getConnString(), 2000);
            watcher.waitForConnected(CONNECTION_TIMEOUT);
            zk.close();

            int leader = qu.getLeaderServer();
            int follower = leader == 2 ? 3 : 2;
            report("leader=%d follower=%d; sid 1 role=%s isro=%s", leader, follower, qu.getPeer(1).peer.getPeerState(),
                FourLetterWordMain.send4LetterWord("127.0.0.1", qu.getPeer(1).clientPort, "isro").trim());

            CountdownWatcher w = new CountdownWatcher();
            ZooKeeper writer = new ZooKeeper(addr(leader), CONNECTION_TIMEOUT, w, false);
            w.waitForConnected(CONNECTION_TIMEOUT);
            List<Integer> unacked = writeWhileStopping(writer, follower);
            writer.close();

            waitForReadOnly(leader);
            // The client's list holds the old leader and sid 1; retry until it lands on the old leader.
            ZooKeeper reader = null;
            CountdownWatcher rw = null;
            List<Integer> seen = new ArrayList<>();
            for (int attempt = 0; attempt < 20 && seen.isEmpty(); attempt++) {
                if (reader != null) {
                    reader.close();
                }
                rw = new CountdownWatcher();
                reader = new ZooKeeper(addr(leader) + "," + addr(1), CONNECTION_TIMEOUT, rw, true);
                rw.waitForReadOnlyConnected(CONNECTION_TIMEOUT);
                seen = readDirty(reader, unacked);
            }
            assertFalse(seen.isEmpty(), "no unacknowledged write was visible at the read-only server");

            log.reset();
            // The stopped follower returns; the old leader wins and its read-only server stops.
            qu.start(follower);
            // The client's isro seek rotates its host list, so its next host after the read-only
            // server stops is either sid 1 or the old leader. Only the first gives the counterexample's order.
            waitForRefusal(log, 15000);
            report("REFUSED: sid 1 role=%s isro=%s; reader.state=%s", qu.getPeer(1).peer.getPeerState(),
                FourLetterWordMain.send4LetterWord("127.0.0.1", qu.getPeer(1).clientPort, "isro").trim(), reader.getState());

            // On this route the old leader wins the election and keeps the txn.
            rw.waitForConnected(CONNECTION_TIMEOUT);
            int d = seen.get(seen.size() - 1);
            assertNotNull(reader.exists(PREFIX + d, false));
            report("reader reconnected state=%s to next-epoch leader sid %d, which kept %s%d", reader.getState(), qu.getLeaderServer(), PREFIX, d);
            reader.close();

            qu.getPeer(1).peer.setSuspended(false);
        } catch (KeeperException e) {
            throw new AssertionError(e);
        }
    }
}
