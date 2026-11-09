/*
 * Reproduction for MC-3 (target: ZKDatabase.addCommittedProposal ISE). Variant of TestAdhocWorkloadB6, same module.
 * Installed as org.apache.zookeeper.server.quorum.BugMC3EvictionTest by test_bugMC-3_eviction_trunc.sh.
 *
 * Nothing here writes committedLog / maxCommittedLog, edits the target method, or fabricates a packet. All packets
 * are the real protocol's. The only test-side interventions, in the codebase's own style (QuorumPeer#makeFollower and
 * #makeObserver overrides, as in QuorumPeerMainTest and DIFFSyncTest; latches, as in TestAdhocWorkloadB6#Holds):
 *  - F's FollowerZooKeeperServer#processTxn waits, before calling super, for one named create (CE: commitQ[F]=<<2>>).
 *  - The LearnerHandler serving the observer waits before it builds NEWLEADER (CE states 33-35); ceOrder only.
 *  - The observer's readPacket/processTxn record what they see and rethrow unchanged.
 * Faults, as in the CE: one observer restart, and the eviction, which is the real cacheCommittedPacket run with a
 * configured limit (zookeeper.observerMaster.sizeLimit, or jute.maxbuffer plus a large znode).
 */
package org.apache.zookeeper.server.quorum;

import static org.apache.zookeeper.test.ClientBase.CONNECTION_TIMEOUT;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.BooleanSupplier;
import javax.security.sasl.SaslException;
import org.apache.jute.BinaryInputArchive;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.PortAssignment;
import org.apache.zookeeper.ZooDefs.Ids;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.server.DataTree;
import org.apache.zookeeper.server.Request;
import org.apache.zookeeper.server.ZKDatabase;
import org.apache.zookeeper.server.ZooKeeperServer;
import org.apache.zookeeper.server.persistence.FileTxnSnapLog;
import org.apache.zookeeper.server.quorum.flexible.QuorumVerifier;
import org.apache.zookeeper.test.ClientBase;
import org.apache.zookeeper.txn.CreateTxn;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

public class BugMC3EvictionTest extends QuorumPeerTestBase {

    private static final int PARTICIPANTS = 3;
    private static final int OBSERVER = PARTICIPANTS + 1;
    private static final long WAIT_SECONDS = 60;

    static {
        // Read once, at class init of BinaryInputArchive / ObserverMaster; surefire forks a JVM per run.
        String mode = System.getProperty("mc3.jute");
        if (mode != null) {
            System.setProperty("jute.maxbuffer", mode);
        }
    }

    private final MainThread[] peers = new MainThread[OBSERVER + 1];
    private final int[] clientPorts = new int[OBSERVER + 1];
    private final int[] observerMasterPorts = new int[PARTICIPANTS + 1];
    private String quorumCfg;
    private int leader;
    private int follower;
    private ZooKeeper client;

    private volatile long holdApplyServer = -1;
    private volatile String holdApplyPath;
    private volatile CountDownLatch applyHeld = new CountDownLatch(1);
    private final CountDownLatch applyRelease = new CountDownLatch(1);

    private final AtomicBoolean holdNewLeader = new AtomicBoolean();
    private final CountDownLatch newLeaderHeld = new CountDownLatch(1);
    private final CountDownLatch newLeaderRelease = new CountDownLatch(1);
    private volatile LearnerHandler observerHandler;

    private final AtomicBoolean holdResync = new AtomicBoolean();
    private final CountDownLatch resyncRelease = new CountDownLatch(1);

    private final List<Throwable> targetFired = new CopyOnWriteArrayList<>();
    private final List<String> observerPackets = new CopyOnWriteArrayList<>();
    private final AtomicInteger observerRuns = new AtomicInteger();

    private static void say(String s) {
        System.out.println("MC3> " + s);
    }

    private static String z(long zxid) {
        return "0x" + Long.toHexString(zxid);
    }

    @AfterEach
    public void releaseAll() {
        applyRelease.countDown();
        newLeaderRelease.countDown();
        resyncRelease.countDown();
    }

    // ---------------------------------------------------------------- Level 1: the CE's order

    /** TRUNC(Z1), INFORM(Z3), NEWLEADER: states 33-37 of MC_hunt_S3_bfs_r1.out. */
    @Test
    @Timeout(240)
    public void ceOrder() throws Exception {
        System.setProperty("zookeeper.observerMaster.sizeLimit", "1024");
        byte[] data = new byte[2048];
        run(data, data, data, true);
        assertFiredAtTarget("Learner.syncWithLeader");
        consequence();
    }

    /** Same, with the default limit: a znode over 0.8 * 32 MiB, under a raised jute.maxbuffer (-Dmc3.jute=31000000). */
    @Test
    @Timeout(280)
    public void ceOrderJuteMaxBuffer() throws Exception {
        assertEquals(31000000, BinaryInputArchive.maxBuffer, "run with -Dmc3.jute=31000000");
        run(new byte[16], new byte[27000000], new byte[16], true);
        assertFiredAtTarget("Learner.syncWithLeader");
        consequence();
    }

    /** No hold around NEWLEADER: the INFORM arrives once the observer is already serving. */
    @Test
    @Timeout(240)
    public void afterUptodate() throws Exception {
        System.setProperty("zookeeper.observerMaster.sizeLimit", "1024");
        byte[] data = new byte[2048];
        run(data, data, data, false);
        assertFiredAtTarget("FinalRequestProcessor");
        consequence();
    }

    /** Negative control: the same schedule, but the packets fit: the retained queue fills the gap. */
    @Test
    @Timeout(240)
    public void controlRetainedQueue() throws Exception {
        byte[] data = new byte[2048];
        run(data, data, data, true, false);
        applyRelease.countDown();
        await("the observer did not apply /z2 and /z3", () -> has(OBSERVER, "/z2") && has(OBSERVER, "/z3"));
        say("control: packets seen by the observer: " + observerPackets);
        say("control: target fired " + targetFired.size() + " time(s)");
        assertTrue(targetFired.isEmpty(), "the target fired with a retained queue");
        assertTrue(observerPackets.stream().anyMatch(p -> p.startsWith("TRUNC")), "control did not take the TRUNC path");
    }

    // ---------------------------------------------------------------- Level 0: no holds

    /** Writes and observer restarts, no hold at all. Reports whether the path shows up unaided. */
    @Test
    @Timeout(280)
    public void level0Stress() throws Exception {
        System.setProperty("zookeeper.observerMaster.sizeLimit", "1024");
        bringUp();
        AtomicBoolean stop = new AtomicBoolean();
        AtomicInteger written = new AtomicInteger();
        ZooKeeper writer = client;
        Thread t = new Thread(() -> {
            byte[] d = new byte[2048];
            while (!stop.get()) {
                try {
                    writer.create("/s" + written.incrementAndGet(), d, Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
                    // Unthrottled, the observer kept failing Learner.java:553 during sync; its restarts could not complete.
                    Thread.sleep(Long.getLong("mc3.writeDelayMs", 20));
                } catch (Exception e) {
                    say("writer: " + e);
                    return;
                }
            }
        });
        t.start();
        long end = System.nanoTime() + TimeUnit.SECONDS.toNanos(Long.getLong("mc3.stressSeconds", 90));
        int restarts = 0;
        int notBack = 0;
        while (System.nanoTime() < end && targetFired.isEmpty()) {
            stopObserver();
            peers[OBSERVER].start();
            restarts++;
            long back = System.nanoTime() + TimeUnit.SECONDS.toNanos(20);
            while (System.nanoTime() < back && !serving(OBSERVER)) {
                Thread.sleep(20);
            }
            if (!serving(OBSERVER)) {
                notBack++;
            }
            Thread.sleep(100);
        }
        stop.set(true);
        t.join();
        if (!targetFired.isEmpty()) {
            Throwable first = targetFired.get(0);
            say("LEVEL0 TARGET FIRED: " + first);
            for (StackTraceElement e : first.getStackTrace()) {
                say("    at " + e);
            }
            int last = written.get();
            await("leader did not settle", () -> has(leader, "/s" + (last - 1)));
            Thread.sleep(3000);
            QuorumPeer op = peers[OBSERVER].getQuorumPeer();
            List<String> missing = new ArrayList<>();
            for (int i = 1; i < last; i++) {
                if (has(leader, "/s" + i) && !has(OBSERVER, "/s" + i)) {
                    missing.add("/s" + i);
                }
            }
            say("level0 aftermath: written=" + last + " committed on the leader but absent on the observer=" + missing
                + " observer run thread alive=" + peers[OBSERVER].isAlive()
                + " QuorumPeer thread alive=" + (op != null && op.isAlive())
                + " serving=" + serving(OBSERVER) + " target fired " + targetFired.size() + " time(s) via processTxn");
        }
        long truncs = observerPackets.stream().filter(p -> p.startsWith("TRUNC")).count();
        say("level0: restarts=" + restarts + " txns=" + written.get() + " TRUNC=" + truncs
            + " targetFired=" + targetFired.size() + " restartsNotServingWithin20s=" + notBack);
    }

    // ---------------------------------------------------------------- the schedule

    private void bringUp() throws Exception {
        ClientBase.setupTestEnv();
        StringBuilder cfg = new StringBuilder();
        for (int sid = 1; sid <= OBSERVER; sid++) {
            clientPorts[sid] = PortAssignment.unique();
            cfg.append(String.format("server.%d=127.0.0.1:%d:%d:%s;127.0.0.1:%d%n", sid, PortAssignment.unique(),
                PortAssignment.unique(), sid <= PARTICIPANTS ? "participant" : "observer", clientPorts[sid]));
            if (sid <= PARTICIPANTS) {
                observerMasterPorts[sid] = PortAssignment.unique();
            }
        }
        quorumCfg = cfg.toString();
        for (int sid = 1; sid <= PARTICIPANTS; sid++) {
            peers[sid] = new Peer(sid, clientPorts[sid], PortAssignment.unique(), quorumCfg, config(observerMasterPorts[sid]));
        }
        servers = new Servers();
        servers.mt = new MainThread[] {peers[1], peers[2], peers[3]};
        for (int sid = 1; sid <= PARTICIPANTS; sid++) {
            peers[sid].start();
        }
        for (int sid = 1; sid <= PARTICIPANTS; sid++) {
            assertTrue(ClientBase.waitForServerUp("127.0.0.1:" + clientPorts[sid], CONNECTION_TIMEOUT));
        }
        leader = role(true);
        follower = role(false);
        peers[OBSERVER] = new Peer(OBSERVER, clientPorts[OBSERVER], PortAssignment.unique(), quorumCfg, config(observerMasterPorts[follower]));
        servers.mt = new MainThread[] {peers[1], peers[2], peers[3], peers[OBSERVER]};
        peers[OBSERVER].start();
        assertTrue(ClientBase.waitForServerUp("127.0.0.1:" + clientPorts[OBSERVER], CONNECTION_TIMEOUT));
        client = ClientBase.createZKClient("127.0.0.1:" + clientPorts[leader]);
        servers.zk = new ZooKeeper[] {client};
        say("leader=" + leader + " F=" + follower + " observer=" + OBSERVER + " omLimit="
            + peers[follower].getQuorumPeer().follower.om.getPktsSizeLimit() + " jute.maxbuffer=" + BinaryInputArchive.maxBuffer);
    }

    private static String config(int observerMasterPort) {
        return String.format("observerMasterPort=%d%nsnapCount=100000%nadmin.enableServer=false%n", observerMasterPort);
    }

    private void run(byte[] d1, byte[] d2, byte[] d3, boolean beforeNewLeader) throws Exception {
        run(d1, d2, d3, beforeNewLeader, true);
    }

    private void run(byte[] d1, byte[] d2, byte[] d3, boolean beforeNewLeader, boolean expectFire) throws Exception {
        bringUp();

        // CE 23-27: Z1 reaches F and O.
        client.create("/z1", d1, Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        await("/z1 on F and O", () -> has(follower, "/z1") && has(OBSERVER, "/z1"));
        long z1 = database(leader).getDataTreeLastProcessedZxid();

        // CE 28-30: F holds commit Z2 in its commit queue. Its ObserverMaster caches (and may evict) and sends it.
        holdApplyPath = "/z2";
        holdApplyServer = follower;
        client.create("/z2", d2, Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        assertTrue(applyHeld.await(WAIT_SECONDS, TimeUnit.SECONDS), "F did not reach Z2's apply");
        await("/z2 on O", () -> has(OBSERVER, "/z2"));
        long z2 = database(OBSERVER).getDataTreeLastProcessedZxid();
        assertEquals(z1 + 1, z2);
        say("state30: F lastProcessed=" + z(database(follower).getDataTreeLastProcessedZxid())
            + " F maxCommittedLog=" + z(database(follower).getmaxCommittedLog())
            + " O lastProcessed=" + z(z2));
        assertEquals(z1, database(follower).getDataTreeLastProcessedZxid());

        // CE 31-33: the observer restarts, ahead of F. F sends TRUNC(Z1) and activates it on the queue.
        holdNewLeader.set(beforeNewLeader);
        stopObserver();
        observerPackets.clear();
        peers[OBSERVER].start();
        String sampleZ3 = "/z3";
        if (beforeNewLeader) {
            assertTrue(newLeaderHeld.await(WAIT_SECONDS, TimeUnit.SECONDS), "handler did not reach NEWLEADER");
            LearnerHandler lh = observerHandler;
            say("state33: handler queue " + queue(lh));
            // CE 34: COMMIT(Z3) reaches F, whose ObserverMaster forwards INFORM(Z3).
            client.create(sampleZ3, d3, Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
            long z3 = database(leader).getDataTreeLastProcessedZxid();
            assertEquals(z2 + 1, z3);
            await("INFORM(Z3) queued for the observer", () -> queue(lh).contains("INFORM " + z(z3)));
            say("state34: handler queue " + queue(lh));
            // CE 35-37.
            newLeaderRelease.countDown();
        } else {
            await("observer serving through F's ObserverMaster", () -> {
                QuorumPeer p = peers[OBSERVER].getQuorumPeer();
                ZooKeeperServer s = p == null ? null : p.getActiveServer();
                return s != null && s.isRunning() && p.observer != null && p.observer.getSocket() != null;
            });
            say("observer serving; its packets so far: " + observerPackets);
            client.create(sampleZ3, d3, Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        }
        if (expectFire) {
            await("the target did not fire", () -> !targetFired.isEmpty());
        }
    }

    private void assertFiredAtTarget(String caller) {
        assertTrue(!targetFired.isEmpty(), "the target did not fire");
        Throwable t = targetFired.get(0);
        say("TARGET FIRED: " + t);
        for (StackTraceElement e : t.getStackTrace()) {
            say("    at " + e);
        }
        say("packets seen by the observer in this run: " + observerPackets);
        assertEquals(IllegalStateException.class, t.getClass());
        StackTraceElement top = null;
        for (StackTraceElement e : t.getStackTrace()) {
            if (e.getClassName().equals(ZKDatabase.class.getName())) {
                top = e;
                break;
            }
        }
        assertNotNull(top);
        assertEquals("addCommittedProposal", top.getMethodName());
        assertEquals(341, top.getLineNumber());
        assertTrue(Arrays.toString(t.getStackTrace()).contains(caller), "expected caller " + caller);
    }

    /**
     * What happens after the check fails. Everything below is observation of the unmodified system: F is released, the
     * observer resyncs by itself, then a client of the observer and a restart of the observer are the consumers.
     */
    private void consequence() throws Exception {
        say("consequence: releasing F; the observer's reconnect waits for F. observer runs=" + observerRuns.get());
        applyRelease.countDown();
        await("F applied /z3", () -> has(follower, "/z3"));
        say("F lastProcessed=" + z(database(follower).getDataTreeLastProcessedZxid())
            + " leader lastProcessed=" + z(database(leader).getDataTreeLastProcessedZxid()));
        int firedBefore = targetFired.size();
        observerPackets.clear();
        resyncRelease.countDown();
        await("observer serving again", () -> serving(OBSERVER));
        say("observer resynced by itself; packets: " + observerPackets + " runs=" + observerRuns.get());
        snapshot("after resync");
        assertTrue(has(leader, "/z2") && has(follower, "/z2"), "the committed /z2 is on the leader and on F");
        boolean diverged = !has(OBSERVER, "/z2");
        say("DIVERGENCE: observer lacks committed /z2 while reporting the same zxid as F: " + diverged);

        clientOfObserver("first client");
        client.create("/z4", new byte[2048], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        Thread.sleep(8000);
        say("after /z4: target fired " + (targetFired.size() - firedBefore) + " more time(s); observer runs=" + observerRuns.get());
        for (int i = firedBefore; i < Math.min(targetFired.size(), firedBefore + 3); i++) {
            Throwable t = targetFired.get(i);
            say("  fired[" + i + "]: " + t);
            for (int k = 0; k < Math.min(6, t.getStackTrace().length); k++) {
                say("      at " + t.getStackTrace()[k]);
            }
        }
        snapshot("after /z4");
        clientOfObserver("second client");

        say("restarting the observer from its disk");
        stopObserver();
        observerPackets.clear();
        peers[OBSERVER].start();
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(30);
        while (System.nanoTime() < deadline && !serving(OBSERVER)) {
            Thread.sleep(50);
        }
        say("after restart: main thread alive=" + peers[OBSERVER].isAlive() + " peer running="
            + peers[OBSERVER].isQuorumPeerRunning() + " serving=" + serving(OBSERVER) + " packets=" + observerPackets);
        snapshot("after restart");
        clientOfObserver("client after restart");
        assertTrue(diverged, "expected the observer to have lost /z2");
    }

    /**
     * MainThread#shutdown joins for 500 ms only, and a run thread ending after the next start() would null its handle, so
     * join. If the observer's QuorumPeer thread already died, MainThread#shutdown is a no-op and its client listener stays
     * bound: a real server's process exits there (QuorumPeerMain#main). In this one JVM, close it through TestQPMain.
     */
    private void stopObserver() throws InterruptedException {
        boolean runThreadAlive = peers[OBSERVER].isAlive();
        QuorumPeer before = peers[OBSERVER].getQuorumPeer();
        if (!runThreadAlive || !before.isAlive()) {
            say("observer already dead when asked to stop: run thread alive=" + runThreadAlive + " QuorumPeer thread alive="
                + (before != null && before.isAlive()));
        }
        peers[OBSERVER].shutdown();
        peers[OBSERVER].join(TimeUnit.SECONDS.toMillis(WAIT_SECONDS));
        assertTrue(!peers[OBSERVER].isAlive(), "the observer's run thread did not end");
        if (!runThreadAlive) {
            peers[OBSERVER].main.shutdown();
        }
    }

    private boolean serving(int sid) {
        QuorumPeer p = peers[sid].getQuorumPeer();
        ZooKeeperServer s = p == null ? null : p.getActiveServer();
        return s != null && s.isRunning();
    }

    private void snapshot(String when) {
        List<String> r = new ArrayList<>();
        for (int sid : new int[] {leader, follower, OBSERVER}) {
            ZKDatabase db = database(sid);
            r.add((sid == OBSERVER ? "O" : sid == leader ? "L" : "F") + "{z2=" + has(sid, "/z2") + ",z3=" + has(sid, "/z3")
                + ",z4=" + has(sid, "/z4") + ",last=" + (db == null ? "?" : z(db.getDataTreeLastProcessedZxid()))
                + ",maxCommittedLog=" + (db == null ? "?" : z(db.getmaxCommittedLog())) + "}");
        }
        say(when + ": " + r);
    }

    /** A real consumer: a client of the observer, after sync(), the documented way to read the latest. */
    private void clientOfObserver(String who) {
        try (ZooKeeper oc = new ZooKeeper("127.0.0.1:" + clientPorts[OBSERVER], 8000, event -> { })) {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10);
            while (System.nanoTime() < deadline && !oc.getState().isConnected()) {
                Thread.sleep(50);
            }
            if (!oc.getState().isConnected()) {
                say(who + ": could not connect to the observer within 10s, state=" + oc.getState());
                return;
            }
            CountDownLatch synced = new CountDownLatch(1);
            oc.sync("/", (rc, path, ctx) -> synced.countDown(), null);
            boolean ok = synced.await(5, TimeUnit.SECONDS);
            say(who + ": sync done=" + ok + " exists(/z2)=" + (oc.exists("/z2", false) != null)
                + " exists(/z3)=" + (oc.exists("/z3", false) != null));
        } catch (Throwable t) {
            say(who + ": observer client failed: " + t);
        }
    }

    private static String queue(LearnerHandler lh) {
        List<String> out = new ArrayList<>();
        for (QuorumPacket p : lh.queuedPackets) {
            if (p.getType() != 0) { // type 0 is LearnerHandler's local marker, which is never written to the wire
                out.add(name(p));
            }
        }
        return out.toString();
    }

    private static String name(QuorumPacket p) {
        if (p.getType() == Leader.LEADERINFO) {
            return "LEADERINFO " + z(p.getZxid());
        }
        String e = LearnerHandler.packetToString(p);
        String[] parts = e == null ? new String[] {"type" + p.getType()} : e.split(" ");
        return parts[0] + " " + z(p.getZxid());
    }

    private ZKDatabase database(int sid) {
        QuorumPeer peer = peers[sid].getQuorumPeer();
        return peer == null ? null : peer.getZkDb();
    }

    private boolean has(int sid, String path) {
        ZKDatabase db = database(sid);
        return db != null && db.getNode(path) != null;
    }

    private int role(boolean leading) throws InterruptedException {
        AtomicInteger found = new AtomicInteger(-1);
        await(leading ? "no leader" : "no follower with an ObserverMaster", () -> {
            for (int sid = 1; sid <= PARTICIPANTS; sid++) {
                QuorumPeer peer = peers[sid].getQuorumPeer();
                if (peer != null && (leading ? peer.leader != null : peer.follower != null && peer.follower.om != null)) {
                    found.set(sid);
                    return true;
                }
            }
            return false;
        });
        return found.get();
    }

    private static void await(String message, BooleanSupplier condition) throws InterruptedException {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(WAIT_SECONDS);
        while (System.nanoTime() < deadline) {
            if (condition.getAsBoolean()) {
                return;
            }
            Thread.sleep(20);
        }
        assertTrue(condition.getAsBoolean(), message);
    }

    private static void hold(CountDownLatch latch) {
        try {
            latch.await(WAIT_SECONDS * 2, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    // ---------------------------------------------------------------- real peers, with the holds above

    private final class Peer extends MainThread {

        Peer(int sid, int clientPort, int adminPort, String cfg, String other) throws IOException {
            super(sid, clientPort, adminPort, cfg, other);
        }

        @Override
        public TestQPMain getTestQPMain() {
            return new TestQPMain() {
                @Override
                protected QuorumPeer getQuorumPeer() throws SaslException {
                    return new CtlPeer();
                }
            };
        }
    }

    private final class CtlPeer extends QuorumPeer {

        CtlPeer() throws SaslException {
        }

        @Override
        public QuorumVerifier getLastSeenQuorumVerifier() {
            Thread t = Thread.currentThread();
            if (t instanceof LearnerHandler && ((LearnerHandler) t).getSid() == OBSERVER && holdNewLeader.compareAndSet(true, false)) {
                observerHandler = (LearnerHandler) t;
                newLeaderHeld.countDown();
                hold(newLeaderRelease);
            }
            return super.getLastSeenQuorumVerifier();
        }

        @Override
        protected Follower makeFollower(FileTxnSnapLog logFactory) throws IOException {
            return new Follower(this, new FollowerZooKeeperServer(logFactory, this, getZkDb()) {
                @Override
                public DataTree.ProcessTxnResult processTxn(Request request) {
                    String path = holdApplyPath;
                    if (path != null && getMyId() == holdApplyServer && request.getTxn() instanceof CreateTxn
                        && path.equals(((CreateTxn) request.getTxn()).getPath())) {
                        holdApplyPath = null;
                        applyHeld.countDown();
                        hold(applyRelease);
                    }
                    return super.processTxn(request);
                }
            });
        }

        @Override
        protected Observer makeObserver(FileTxnSnapLog logFactory) throws IOException {
            observerRuns.incrementAndGet();
            ObserverZooKeeperServer ozk = new ObserverZooKeeperServer(logFactory, this, getZkDb()) {
                @Override
                public DataTree.ProcessTxnResult processTxn(Request request) {
                    try {
                        return super.processTxn(request);
                    } catch (IllegalStateException e) {
                        if (targetFired.isEmpty()) {
                            holdResync.set(true);
                        }
                        targetFired.add(e);
                        throw e;
                    }
                }
            };
            return new Observer(this, ozk) {
                @Override
                void readPacket(QuorumPacket pp) throws IOException {
                    super.readPacket(pp);
                    if (pp.getType() != Leader.PING) {
                        observerPackets.add(name(pp));
                    }
                }

                @Override
                protected long registerWithLeader(int pktType) throws IOException {
                    if (holdResync.compareAndSet(true, false)) {
                        hold(resyncRelease);
                    }
                    return super.registerWithLeader(pktType);
                }
            };
        }
    }
}
