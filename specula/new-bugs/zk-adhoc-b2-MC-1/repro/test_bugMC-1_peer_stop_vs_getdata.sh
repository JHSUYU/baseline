#!/usr/bin/env bash
# MC-1 reproduction: a peer's stop() deletes a listed offer before a participant's getData on it.
# Variant of LeaderElectionSupportTest (same module, same setup, one shared handle, real ClientBase server).
# No source under test is modified. Only public LeaderElectionSupport API and real threads are used.
# Run 1 (plain): no debugger attached. Run 2 (jdi): external read-only JDI watcher records real throw sites.
# Usage: test_bugMC-1_peer_stop_vs_getdata.sh [rounds]   exit 0 = target fired and consequence shown.
set -u
WT=/users/ZhenyuLi/Specula/runs/20261102-193718-3f98/zk-adhoc-b2/.specula-output/confirmation/MC-1/worktree
REPRO=$(cd "$(dirname "$0")" && pwd)
ROUNDS=${1:-300}
source /bulk/specula-adhoc/zookeeper/cases/zk-adhoc-b2/env.sh
MOD=zookeeper-recipes/zookeeper-recipes-election
TESTF=$WT/$MOD/src/test/java/org/apache/zookeeper/recipes/leader/SpeculaAdhocMC1Test.java
TOOL=$(mktemp -d /tmp/mc1_tool.XXXXXX)
trap 'rm -f "$TESTF"; rm -f "$TOOL/Mc1ExceptionWatcher.java"; rmdir "$TOOL" 2>/dev/null' EXIT

cat > "$TESTF" <<'JAVA'
package org.apache.zookeeper.recipes.leader;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import java.util.ArrayList;
import java.util.List;
import java.util.Random;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.KeeperException;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.recipes.leader.LeaderElectionSupport.EventType;
import org.apache.zookeeper.test.ClientBase;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/** MC-1 variant of LeaderElectionSupportTest: setup copied, public API only. */
public class SpeculaAdhocMC1Test extends ClientBase {

    private static final String TEST_ROOT_NODE = "/" + System.currentTimeMillis() + "_";
    private static final int ROUNDS = Integer.getInteger("mc1.rounds", 300);
    private static final long SETTLE_MS = 3000;

    private ZooKeeper zooKeeper;
    private final Random random = new Random(20261104L);

    private String root() {
        return TEST_ROOT_NODE + Thread.currentThread().getId();
    }

    @BeforeEach
    public void setUp() throws Exception {
        super.setUp();
        zooKeeper = createClient();
        zooKeeper.create(root(), new byte[0], ZooDefs.Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
    }

    @AfterEach
    public void tearDown() throws Exception {
        if (zooKeeper != null) {
            zooKeeper.delete(root(), -1);
        }
        super.tearDown();
    }

    /** A participant on the shared handle, recording what a LeaderElectionAware listener is told. */
    private final class Participant {
        final String name;
        final String rootNode;
        final LeaderElectionSupport les = new LeaderElectionSupport();
        final List<EventType> events = new CopyOnWriteArrayList<>();
        final CountDownLatch elected = new CountDownLatch(1);
        boolean stopped;

        Participant(String name, String rootNode) {
            this.name = name;
            this.rootNode = rootNode;
            les.setZooKeeper(zooKeeper);
            les.setRootNodeName(rootNode);
            les.setHostName(name);
            les.addListener(e -> {
                events.add(e);
                if (e == EventType.ELECTED_COMPLETE) {
                    elected.countDown();
                }
            });
        }

        boolean failed() {
            return events.contains(EventType.FAILED);
        }

        void stop() {
            if (!stopped) {
                stopped = true;
                les.stop();
            }
        }

        /** Events the listener saw after FAILED; empty means the library never re-entered the election. */
        List<EventType> afterFailed() {
            int i = events.indexOf(EventType.FAILED);
            return i < 0 ? new ArrayList<>() : new ArrayList<>(events.subList(i + 1, events.size()));
        }
    }

    private void log(String s) {
        System.out.println("MC1 " + s);
        System.out.flush();
    }

    private static void spin(long nanos) {
        long end = System.nanoTime() + nanos;
        while (System.nanoTime() < end) {
            Thread.yield();
        }
    }

    private void cleanup(String rootNode, Participant... ps) throws Exception {
        for (Participant p : ps) {
            p.stop();
        }
        assertEquals(new ArrayList<String>(), zooKeeper.getChildren(rootNode, false), "offers left behind");
    }

    /** Run a and b at once; b starts offsetNanos after a. */
    private void race(Runnable a, Runnable b, long offsetNanos) throws Exception {
        CyclicBarrier barrier = new CyclicBarrier(2);
        Thread ta = new Thread(() -> {
            try {
                barrier.await();
                a.run();
            } catch (Exception e) {
                throw new RuntimeException(e);
            }
        });
        Thread tb = new Thread(() -> {
            try {
                barrier.await();
                spin(offsetNanos);
                b.run();
            } catch (Exception e) {
                throw new RuntimeException(e);
            }
        });
        ta.start();
        tb.start();
        ta.join();
        tb.join();
    }

    /** Observable election state after a FAILED participant: nobody is told ELECTED, the failed offer heads the line. */
    private void showNoLeader(String label, Participant failedOne, String root) throws Exception {
        Thread.sleep(SETTLE_MS);
        List<String> offers = zooKeeper.getChildren(root, false);
        Participant probe = new Participant("probe", root);
        String leaderHost = probe.les.getLeaderHostName();
        log(label + " after " + SETTLE_MS + "ms: live offers=" + offers + " getLeaderHostName()=" + leaderHost
            + " " + failedOne.name + ".toString=" + failedOne.les);
        log(label + " events of " + failedOne.name + " after FAILED: " + failedOne.afterFailed());
        assertEquals(failedOne.name, leaderHost, "reported leader is the FAILED participant");
        assertFalse(failedOne.events.contains(EventType.ELECTED_COMPLETE), "FAILED participant was never told ELECTED");
        assertEquals(new ArrayList<EventType>(), failedOne.afterFailed(), "library never retried");

        Participant joiner = new Participant("p4", root);
        joiner.les.start();
        boolean joinerElected = joiner.elected.await(SETTLE_MS, TimeUnit.MILLISECONDS);
        log(label + " new joiner p4 events=" + joiner.events + " elected within " + SETTLE_MS + "ms=" + joinerElected);
        assertFalse(joinerElected, "healthy joiner queues behind the FAILED offer");
        log(label + " RESULT: no participant holds ELECTED while live offers exist; healthy p4 is blocked behind FAILED "
            + failedOne.name);

        failedOne.stop();
        boolean afterStop = joiner.elected.await(SETTLE_MS, TimeUnit.MILLISECONDS);
        log(label + " only after an explicit " + failedOne.name + ".stop(): p4 elected=" + afterStop);
        joiner.stop();
    }

    /** Control: same operations, no overlap. Each stop hands leadership to the next in line. */
    @Test
    public void testControlNoOverlap() throws Exception {
        String root = root();
        Participant p1 = new Participant("p1", root);
        Participant p2 = new Participant("p2", root);
        Participant p3 = new Participant("p3", root);
        p1.les.start();
        p2.les.start();
        p3.les.start();
        p1.stop();
        boolean e2 = p2.elected.await(SETTLE_MS, TimeUnit.MILLISECONDS);
        p2.stop();
        boolean e3 = p3.elected.await(SETTLE_MS, TimeUnit.MILLISECONDS);
        log("CONTROL p2 elected=" + e2 + " p3 elected=" + e3 + " anyFailed="
            + (p1.failed() || p2.failed() || p3.failed()));
        assertTrue(e2 && e3);
        assertFalse(p1.failed() || p2.failed() || p3.failed());
        cleanup(root, p3);
    }

    /** Level 0: runElectionSupportThread's exact shape (start, sleep, stop) with a short sleepDuration. */
    @Test
    public void testWorkloadShape() throws Exception {
        String root = root();
        int[] sleeps = {0, 1, 2, 5, 10};
        int failedRounds = 0;
        int failedParticipants = 0;
        AtomicInteger failureCounter = new AtomicInteger();
        for (int r = 0; r < ROUNDS; r++) {
            long sleepDuration = sleeps[r % sleeps.length];
            List<Participant> ps = new ArrayList<>();
            List<Thread> ts = new ArrayList<>();
            for (int i = 0; i < 3; i++) {
                Participant p = new Participant("p" + (i + 1), root);
                ps.add(p);
                Thread t = new Thread(() -> {
                    try {
                        p.les.start();
                        Thread.sleep(sleepDuration);
                        p.stop();
                    } catch (Exception e) {
                        failureCounter.incrementAndGet();
                    }
                });
                ts.add(t);
                t.start();
            }
            for (Thread t : ts) {
                t.join();
            }
            int f = 0;
            for (Participant p : ps) {
                f += p.failed() ? 1 : 0;
            }
            failedParticipants += f;
            failedRounds += f > 0 ? 1 : 0;
        }
        log("WORKLOAD-SHAPE rounds=" + ROUNDS + " roundsWithFAILED=" + failedRounds + " FAILEDparticipants="
            + failedParticipants + " workload failureCounter=" + failureCounter.get());
    }

    /** S1-i, the counterexample: p1 ELECTED, p2 READY, p3 inside start() while p1 stops. */
    @Test
    public void testLateStartVsLeaderStop() throws Exception {
        String root = root();
        int hits = 0;
        boolean shown = false;
        for (int r = 0; r < ROUNDS; r++) {
            Participant p1 = new Participant("p1", root);
            Participant p2 = new Participant("p2", root);
            Participant p3 = new Participant("p3", root);
            p1.les.start();
            p2.les.start();
            race(p3.les::start, p1::stop, (long) (random.nextDouble() * 4_000_000L));
            if (p3.failed()) {
                hits++;
                if (!shown) {
                    shown = true;
                    boolean e2 = p2.elected.await(SETTLE_MS, TimeUnit.MILLISECONDS);
                    log("S1-i round " + r + ": p3 events=" + p3.events + " p3 offer live, p2 elected=" + e2
                        + " live offers=" + zooKeeper.getChildren(root, false));
                    log("S1-i (control would hand leadership to p3 on p2.stop()); stopping p2 now");
                    p2.stop();
                    showNoLeader("S1-i", p3, root);
                }
            }
            cleanup(root, p1, p2, p3);
        }
        log("S1-i rounds=" + ROUNDS + " p3FAILED=" + hits);
        assertTrue(hits > 0, "no S1-i overlap hit");
    }

    /** S1-ii: p1 ELECTED, p2 READY, p3 READY; p2's EventThread re-determines while p3 stops. */
    @Test
    public void testSuccessorRedeterminationVsThirdStop() throws Exception {
        String root = root();
        int hits = 0;
        boolean shown = false;
        for (int r = 0; r < ROUNDS; r++) {
            Participant p1 = new Participant("p1", root);
            Participant p2 = new Participant("p2", root);
            Participant p3 = new Participant("p3", root);
            p1.les.start();
            p2.les.start();
            p3.les.start();
            race(p1::stop, p3::stop, (long) (random.nextDouble() * 4_000_000L));
            boolean e2 = p2.elected.await(p2.failed() ? 1 : 200, TimeUnit.MILLISECONDS);
            if (p2.failed()) {
                hits++;
                if (!shown) {
                    shown = true;
                    log("S1-ii round " + r + ": p2 events=" + p2.events + " elected=" + e2
                        + " live offers=" + zooKeeper.getChildren(root, false));
                    showNoLeader("S1-ii", p2, root);
                }
            }
            cleanup(root, p1, p2, p3);
        }
        log("S1-ii rounds=" + ROUNDS + " p2FAILED=" + hits);
        assertTrue(hits > 0, "no S1-ii overlap hit");
    }

    /**
     * Class Javadoc: "It is up to the user to ensure any failure to become the leader ... results in a revocation
     * of its leader offer (i.e. that stop() is called)". Does an application that obeys this recover?
     */
    @Test
    public void testContractObeyingListener() throws Exception {
        String root = root();
        int hits = 0;
        boolean shown = false;
        for (int r = 0; r < ROUNDS && !shown; r++) {
            Participant p1 = new Participant("p1", root);
            Participant p2 = new Participant("p2", root);
            Participant p3 = new Participant("p3", root);
            CountDownLatch revoked = new CountDownLatch(1);
            p2.les.addListener(e -> {
                if (e == EventType.FAILED) {
                    p2.stop();
                    revoked.countDown();
                }
            });
            p1.les.start();
            p2.les.start();
            p3.les.start();
            race(p1::stop, p3::stop, (long) (random.nextDouble() * 4_000_000L));
            if (revoked.await(200, TimeUnit.MILLISECONDS)) {
                hits++;
                shown = true;
                Thread.sleep(SETTLE_MS);
                List<String> offers = zooKeeper.getChildren(root, false);
                String leaderHost = new Participant("probe", root).les.getLeaderHostName();
                log("OBEYING round " + r + ": p2 FAILED then stop() from its listener; p2 events=" + p2.events);
                log("OBEYING after " + SETTLE_MS + "ms: live offers=" + offers + " getLeaderHostName()=" + leaderHost
                    + " elected events on p2=" + p2.events.contains(EventType.ELECTED_COMPLETE));
                assertEquals(new ArrayList<String>(), offers);
                assertFalse(p2.events.contains(EventType.ELECTED_COMPLETE));
                log("OBEYING RESULT: blocking offer gone, but the only live candidate left the election; no leader");
                Participant retry = new Participant("p2-retry", root);
                retry.les.start();
                log("OBEYING application-level re-start() (not documented by the recipe): elected="
                    + retry.elected.await(SETTLE_MS, TimeUnit.MILLISECONDS));
                retry.stop();
            }
            cleanup(root, p1, p2, p3);
        }
        log("OBEYING hits=" + hits);
        assertTrue(hits > 0, "no overlap hit");
    }

    /** getLeaderHostName path: the public reader gets NoNodeException from a peer's ordinary stop(). */
    @Test
    public void testGetLeaderHostNameVsPeerStop() throws Exception {
        String root = root();
        int hits = 0;
        KeeperException.NoNodeException sample = null;
        for (int r = 0; r < ROUNDS; r++) {
            Participant p1 = new Participant("p1", root);
            Participant p2 = new Participant("p2", root);
            Participant p3 = new Participant("p3", root);
            p1.les.start();
            p2.les.start();
            p3.les.start();
            KeeperException.NoNodeException[] seen = new KeeperException.NoNodeException[1];
            race(() -> {
                try {
                    p2.les.getLeaderHostName();
                } catch (KeeperException.NoNodeException e) {
                    seen[0] = e;
                } catch (Exception e) {
                    throw new RuntimeException(e);
                }
            }, p3::stop, (long) (random.nextDouble() * 500_000L));
            if (seen[0] != null) {
                hits++;
                sample = seen[0];
            }
            cleanup(root, p1, p2, p3);
        }
        log("GETLEADER rounds=" + ROUNDS + " NoNodeException to caller=" + hits);
        if (sample != null) {
            log("GETLEADER sample: " + sample);
            for (StackTraceElement f : sample.getStackTrace()) {
                if (f.getClassName().contains("LeaderElectionSupport") || f.getClassName().endsWith(".ZooKeeper")) {
                    log("GETLEADER   at " + f);
                }
            }
        }
        assertTrue(hits > 0, "no getLeaderHostName overlap hit");
    }
}
JAVA

cat > "$TOOL/Mc1ExceptionWatcher.java" <<'JAVA'
import com.sun.jdi.*;
import com.sun.jdi.connect.*;
import com.sun.jdi.event.*;
import com.sun.jdi.request.*;
import java.util.*;

/** Read-only: on each NoNodeException throw, record the throw location and frames. Never writes to the target VM. */
public class Mc1ExceptionWatcher {
    static final String CLS = "org.apache.zookeeper.KeeperException$NoNodeException";

    public static void main(String[] a) throws Exception {
        AttachingConnector c = null;
        for (AttachingConnector x : Bootstrap.virtualMachineManager().attachingConnectors()) {
            if (x.name().equals("com.sun.jdi.SocketAttach")) c = x;
        }
        Map<String, Connector.Argument> args = c.defaultArguments();
        args.get("hostname").setValue("127.0.0.1");
        args.get("port").setValue(a[0]);
        VirtualMachine vm = null;
        for (int i = 0; i < 600 && vm == null; i++) {
            try { vm = c.attach(args); } catch (java.io.IOException e) { Thread.sleep(500); }
        }
        if (vm == null) { System.out.println("JDI attach failed"); return; }
        EventRequestManager erm = vm.eventRequestManager();
        ClassPrepareRequest cpr = erm.createClassPrepareRequest();
        cpr.addClassFilter(CLS);
        cpr.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);
        cpr.enable();
        for (ReferenceType t : vm.classesByName(CLS)) arm(erm, t);
        vm.resume();
        Map<String, Integer> counts = new TreeMap<>();
        Map<String, Integer> printed = new HashMap<>();
        boolean up = true;
        while (up) {
            EventSet set = vm.eventQueue().remove();
            for (Event ev : set) {
                if (ev instanceof ClassPrepareEvent) {
                    arm(erm, ((ClassPrepareEvent) ev).referenceType());
                } else if (ev instanceof ExceptionEvent) {
                    report((ExceptionEvent) ev, counts, printed);
                } else if (ev instanceof VMDisconnectEvent || ev instanceof VMDeathEvent) {
                    up = false;
                }
            }
            if (up) set.resume();
        }
        System.out.println("JDI-SUMMARY (throw location | first LeaderElectionSupport frames) count:");
        counts.forEach((k, v) -> System.out.println("JDI-SUMMARY " + v + "  " + k));
    }

    static void arm(EventRequestManager erm, ReferenceType t) {
        ExceptionRequest r = erm.createExceptionRequest(t, true, true);
        r.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);
        r.enable();
    }

    static void report(ExceptionEvent e, Map<String, Integer> counts, Map<String, Integer> printed) {
        try {
            Location l = e.location();
            String where = l.declaringType().name() + "." + l.method().name() + ":" + l.lineNumber();
            List<StackFrame> fs = e.thread().frames();
            StringBuilder les = new StringBuilder();
            for (StackFrame f : fs) {
                Location fl = f.location();
                if (fl.declaringType().name().endsWith("LeaderElectionSupport")) {
                    if (les.length() < 120) les.append(fl.method().name()).append(":").append(fl.lineNumber()).append(" ");
                }
            }
            String key = where + " | " + les;
            counts.merge(key, 1, Integer::sum);
            if (printed.merge(key, 1, Integer::sum) <= 2) {
                String path = "?";
                try {
                    LocalVariable v = fs.get(0).visibleVariableByName("path");
                    if (v != null) path = String.valueOf(fs.get(0).getValue(v));
                } catch (Exception ignored) { }
                System.out.println("JDI-THROW " + e.exception().referenceType().name() + " thread=" + e.thread().name() + " path=" + path);
                int n = 0;
                for (StackFrame f : fs) {
                    Location fl = f.location();
                    String src = "?";
                    try { src = fl.sourceName(); } catch (AbsentInformationException ignored) { }
                    System.out.println("JDI-THROW   at " + fl.declaringType().name() + "." + fl.method().name() + "(" + src + ":" + fl.lineNumber() + ")");
                    if (++n >= 9) break;
                }
            }
        } catch (Exception x) {
            System.out.println("JDI-ERR " + x);
        }
    }
}
JAVA

cd "$WT" || exit 2
RPT=$WT/$MOD/target/surefire-reports/org.apache.zookeeper.recipes.leader.SpeculaAdhocMC1Test-output.txt
RES=$WT/$MOD/target/surefire-reports/org.apache.zookeeper.recipes.leader.SpeculaAdhocMC1Test.txt

echo "=== RUN 1: plain, no debugger, rounds=$ROUNDS ==="
timeout 15m mvn -B -o test -pl $MOD -Dtest='SpeculaAdhocMC1Test' -Dmc1.rounds="$ROUNDS" \
  -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false > "$REPRO/MC-1-plain.mvn.log" 2>&1
P=$?
echo "mvn exit=$P"; grep -E 'Tests run:|BUILD' "$REPRO/MC-1-plain.mvn.log" | tail -3
cat "$RES" | head -30 > "$REPRO/MC-1-plain.result.txt"
grep '^MC1 ' "$RPT" | tee "$REPRO/MC-1-plain.out"

echo "=== RUN 2: with read-only JDI watcher, rounds=$ROUNDS ==="
PORT=$((20000 + RANDOM % 20000))
java "$TOOL/Mc1ExceptionWatcher.java" "$PORT" > "$REPRO/MC-1-jdi.frames" 2>&1 &
W=$!
timeout 20m mvn -B -o test -pl $MOD -Dtest='SpeculaAdhocMC1Test' -Dmc1.rounds="$ROUNDS" \
  "-Dmaven.surefire.debug=-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=127.0.0.1:$PORT" \
  -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false > "$REPRO/MC-1-jdi.mvn.log" 2>&1
J=$?
wait $W
echo "mvn exit=$J"; grep -E 'Tests run:|BUILD' "$REPRO/MC-1-jdi.mvn.log" | tail -3
grep '^MC1 ' "$RPT" | tee "$REPRO/MC-1-jdi.out"
cat "$REPRO/MC-1-jdi.frames"

echo "=== RUN 3: UNMODIFIED LeaderElectionSupportTest#testNodes3+testNodes20+testNodes100 with read-only JDI watcher ==="
PORT=$((20000 + RANDOM % 20000))
java "$TOOL/Mc1ExceptionWatcher.java" "$PORT" > "$REPRO/MC-1-workload.frames" 2>&1 &
W=$!
timeout 10m mvn -B -o test -pl $MOD -Dtest='LeaderElectionSupportTest#testNodes3+testNodes20+testNodes100' \
  "-Dmaven.surefire.debug=-agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=127.0.0.1:$PORT" \
  -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false > "$REPRO/MC-1-workload.mvn.log" 2>&1
echo "mvn exit=$?"
wait $W
grep -E 'Tests run:|BUILD' "$REPRO/MC-1-workload.mvn.log" | tail -3
grep JDI-SUMMARY "$REPRO/MC-1-workload.frames"

grep -q 'JDI-THROW   at org.apache.zookeeper.server.FinalRequestProcessor.handleGetDataRequest(FinalRequestProcessor.java:674)' "$REPRO/MC-1-jdi.frames" \
  && grep -q 'S1-i RESULT' "$REPRO/MC-1-jdi.out" && echo "BUG TRIGGERED: target frame and consequence observed" && exit 0
echo "NOT TRIGGERED"; exit 1
