#!/usr/bin/env bash
# MC-2 reproduction: a stale REVALIDATE from an abandoned follower handshake
# overwrites the session owner set by the leader for the client's live
# connection; the client's next ops on the leader fail with
# SessionMovedException thrown at SessionTrackerImpl.checkSession:246.
#
# Escalation level: 1 (timing assistance only).
#   - Pristine source at base_commit 31794056e6 (git archive HEAD of the
#     confirmation worktree; Specula trace instrumentation NOT included).
#   - No source of the system under test is modified.
#   - The only control is a delay of follower F's REVALIDATE on the
#     follower->leader link: a test thread holds the monitor of F's
#     Learner.leaderOs (the monitor Learner.writePacket takes, Learner.java:121)
#     for ~3 s, i.e. the REVALIDATE packet is late on the wire. That is a
#     network delay, below syncLimit*tickTime (6 s), so no peer fails.
#   - The workload's setup (QuorumBase, 5 servers, DisconnectableZooKeeper,
#     same /w, /w/e nodes) is copied from TestAdhocWorkloadK1. One client
#     handle is live at any time; no request is in flight during the move.
#   - A JDI observer (separate JVM, read-only) attaches to the test JVM and
#     prints the stack of every SessionMovedException construction/throw, to
#     show the server-side frame SessionTrackerImpl.checkSession:246.
#
# Usage: test_bugMC-2_stale_revalidate.sh [RUNS]
set -u
RUNS=${1:-3}
HERE=$(cd "$(dirname "$0")" && pwd)
WD=/users/ZhenyuLi/Specula/runs/20261107-165521-1697/zk-adhoc-k1/.specula-output/confirmation/MC-2
SRC_WT=$WD/worktree
CLEAN=$WD/clean
CASE_SRC=/bulk/specula-adhoc/zookeeper/cases/zk-adhoc-k1/zookeeper
source /bulk/specula-adhoc/zookeeper/cases/zk-adhoc-k1/env.sh

# ---- 1. pristine tree at base_commit + workload test -----------------------
if [ ! -f "$CLEAN/build.xml" ]; then
  mkdir -p "$CLEAN"
  git -C "$SRC_WT" archive HEAD | tar -x -C "$CLEAN"
fi
echo "base commit: $(git -C "$SRC_WT" rev-parse HEAD)"
cp "$SRC_WT/src/java/test/org/apache/zookeeper/test/TestAdhocWorkloadK1.java" \
   "$CLEAN/src/java/test/org/apache/zookeeper/test/"
TD=$CLEAN/src/java/test/org/apache/zookeeper/test

# ---- 2. the workload variant ------------------------------------------------
cat > "$TD/SpeculaAdhocK1StaleOpenTest.java" <<'EOF'
package org.apache.zookeeper.test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.net.InetSocketAddress;
import java.net.SocketAddress;
import java.util.Map;
import java.util.concurrent.CountDownLatch;

import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.KeeperException;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.ZooDefs.Ids;
import org.apache.zookeeper.server.quorum.Learner;
import org.apache.zookeeper.server.quorum.QuorumPeer;
import org.apache.zookeeper.server.quorum.QuorumPeer.ServerState;
import org.apache.zookeeper.test.ClientBase.CountdownWatcher;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;

/**
 * Variant of TestAdhocWorkloadK1 (MC-2): the session is reopened at follower
 * F, F's REVALIDATE is delayed on the F->leader link past the client's
 * connectTimeout, the client gives up and reopens at the leader L, then the
 * delayed REVALIDATE reaches L.
 */
public class SpeculaAdhocK1StaleOpenTest {
    private final QuorumBase qb = new QuorumBase();

    @Before
    public void setUp() throws Exception { qb.setUp(); }

    @After
    public void tearDown() throws Exception { qb.tearDown(); }

    static void log(String s) {
        System.out.println("[MC2 " + System.currentTimeMillis() % 100000 + "] " + s);
    }

    static SocketAddress remote(ZooKeeper zk) throws Exception {
        Method m = ZooKeeper.class.getDeclaredMethod("testableRemoteSocketAddress");
        m.setAccessible(true);
        return (SocketAddress) m.invoke(zk);
    }

    @SuppressWarnings("unchecked")
    static Map<Long, ?> pendingRevalidations(Learner l) throws Exception {
        Field f = Learner.class.getDeclaredField("pendingRevalidations");
        f.setAccessible(true);
        return (Map<Long, ?>) f.get(l);
    }

    static Object leaderOs(Learner l) throws Exception {
        Field f = Learner.class.getDeclaredField("leaderOs");
        f.setAccessible(true);
        return f.get(l);
    }

    /** Delays everything F writes to the leader while held (link delay). */
    static class LinkHold extends Thread {
        final Object mon; final CountDownLatch held = new CountDownLatch(1);
        final CountDownLatch release = new CountDownLatch(1);
        LinkHold(Object mon) { super("MC2-link-hold"); this.mon = mon; setDaemon(true); }
        public void run() {
            synchronized (mon) {
                held.countDown();
                try { release.await(); } catch (InterruptedException e) { }
            }
        }
    }

    @Test
    public void run() throws Exception {
        String[] hps = qb.hostPort.split(",");
        QuorumPeer[] peers = { qb.s1, qb.s2, qb.s3, qb.s4, qb.s5 };
        int li = -1, fi = -1;
        for (int i = 0; i < peers.length; i++) {
            ServerState st = peers[i].getPeerState();
            if (st == ServerState.LEADING) li = i;
            else if (st == ServerState.FOLLOWING && fi < 0) fi = i;
        }
        assertTrue("leader and follower found", li >= 0 && fi >= 0);
        int lPort = Integer.parseInt(hps[li].split(":")[1]);
        log("leader L = s" + (li + 1) + " " + hps[li] + ", follower F = s" + (fi + 1) + " " + hps[fi]);

        // --- workload prefix (as TestAdhocWorkloadK1) ---
        CountdownWatcher watcher = new CountdownWatcher();
        DisconnectableZooKeeper zk = new DisconnectableZooKeeper(hps[0],
                ClientBase.CONNECTION_TIMEOUT, watcher);
        watcher.waitForConnected(ClientBase.CONNECTION_TIMEOUT);
        zk.create("/w", new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        zk.create("/w/e", new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.EPHEMERAL);
        long sessionId = zk.getSessionId();
        byte[] passwd = zk.getSessionPasswd();
        log("session 0x" + Long.toHexString(sessionId) + " created via " + hps[0]);
        // leave the server without ending the session (workload step)
        zk.disconnect();

        Learner fLearner = peers[fi].follower;
        Map<Long, ?> pending = pendingRevalidations(fLearner);

        // --- move: reopen with the server list {F, L}; F's REVALIDATE is late ---
        int sessionTimeout = 4000;   // client side: connectTimeout = 4000 / 2 hosts = 2000 ms
        DisconnectableZooKeeper zk2 = null;
        CountdownWatcher w2 = null;
        LinkHold hold = null;
        long holdStart = 0;
        for (int attempt = 1; attempt <= 20 && zk2 == null; attempt++) {
            hold = new LinkHold(leaderOs(fLearner));
            hold.start();
            hold.held.await();
            holdStart = System.currentTimeMillis();
            w2 = new CountdownWatcher();
            DisconnectableZooKeeper cand = new DisconnectableZooKeeper(
                    hps[fi] + "," + hps[li], sessionTimeout, w2, sessionId, passwd);
            boolean openedAtF = false;
            while (System.currentTimeMillis() - holdStart < 1500) {
                if (pending.containsKey(sessionId)) { openedAtF = true; break; }
                if (cand.getState() == ZooKeeper.States.CONNECTED) break;
                Thread.sleep(5);
            }
            if (openedAtF) {
                log("attempt " + attempt + ": client opened the session at F; F wrote REVALIDATE"
                        + " (pendingRevalidations has 0x" + Long.toHexString(sessionId)
                        + "), the packet is held on the F->L link");
                zk2 = cand;
            } else {
                // the shuffled list put L first: no handshake at F; retry the move
                log("attempt " + attempt + ": client went to L first, retrying the move");
                hold.release.countDown();
                cand.disconnect();
                Thread.sleep(200);
            }
        }
        assertNotNull("client never opened at F", zk2);

        // client abandons F after connectTimeout and reopens at L
        w2.waitForConnected(10000);
        InetSocketAddress ra = (InetSocketAddress) remote(zk2);
        log("client CONNECTED to port " + ra.getPort() + " (L=" + lPort + ") after "
                + (System.currentTimeMillis() - holdStart) + " ms; REVALIDATE still pending at F: "
                + pending.containsKey(sessionId));
        assertEquals("client reopened at the leader", lPort, ra.getPort());

        // control: on the live connection to L, before the stale REVALIDATE is processed
        assertNotNull(zk2.exists("/w/e", false));
        zk2.setData("/w", "before".getBytes(), -1);
        log("control: exists(/w/e) and setData(/w) on L succeed before the stale REVALIDATE");

        // the delayed REVALIDATE now reaches L
        hold.release.countDown();
        long relAt = System.currentTimeMillis();
        log("releasing F->L link after " + (relAt - holdStart) + " ms hold");
        while (pending.containsKey(sessionId) && System.currentTimeMillis() - relAt < 10000) {
            Thread.sleep(5);
        }
        assertTrue("REVALIDATE answered", !pending.containsKey(sessionId));
        log("L processed F's stale REVALIDATE and answered it (F's pendingRevalidations entry gone)");

        // the client's only live connection is to L; its ops now fail
        int moved = 0;
        String[] ops = { "setData", "exists", "create", "getChildren" };
        for (int round = 0; round < 3; round++) {
            for (String op : ops) {
                try {
                    if (op.equals("setData")) zk2.setData("/w", ("v" + round).getBytes(), -1);
                    else if (op.equals("exists")) zk2.exists("/w/e", false);
                    else if (op.equals("create")) zk2.create("/w/c-", new byte[0],
                            Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT_SEQUENTIAL);
                    else zk2.getChildren("/w", false);
                    log("round " + round + " " + op + " OK");
                } catch (KeeperException.SessionMovedException e) {
                    moved++;
                    log("round " + round + " " + op + " -> " + e + "  (client state="
                            + zk2.getState() + ", connected to port "
                            + ((InetSocketAddress) remote(zk2)).getPort() + " = L)");
                }
            }
            if (round < 2) Thread.sleep(3000);   // pings keep flowing between rounds
        }
        assertEquals("same session", sessionId, zk2.getSessionId());
        log("SessionMovedException count = " + moved + " of " + (3 * ops.length) + " ops");
        if (moved > 0) {
            log("BUG REPRODUCED: TargetSafe violated -- live connection to L rejected with SessionMovedException");
        } else {
            fail("no SessionMovedException observed");
        }
        zk2.close();
    }
}
EOF

# ---- 3. JDI observer (read-only) -------------------------------------------
OBS=$WD/jdi-observer; mkdir -p "$OBS"
cat > "$OBS/SessionMovedObserver.java" <<'EOF'
import com.sun.jdi.*;
import com.sun.jdi.connect.*;
import com.sun.jdi.event.*;
import com.sun.jdi.request.*;
import java.util.*;

/** Attaches to a JVM and prints the stack of each SessionMovedException throw. */
public class SessionMovedObserver {
    static final String CLS = "org.apache.zookeeper.KeeperException$SessionMovedException";
    public static void main(String[] a) throws Exception {
        AttachingConnector c = null;
        for (AttachingConnector ac : Bootstrap.virtualMachineManager().attachingConnectors())
            if (ac.transport().name().equals("dt_socket")) c = ac;
        Map<String, Connector.Argument> args = c.defaultArguments();
        args.get("hostname").setValue("127.0.0.1");
        args.get("port").setValue(a[0]);
        VirtualMachine vm = null;
        for (int i = 0; i < 100 && vm == null; i++) {
            try { vm = c.attach(args); } catch (java.io.IOException e) { Thread.sleep(100); }
        }
        EventRequestManager erm = vm.eventRequestManager();
        List<ReferenceType> loaded = vm.classesByName(CLS);
        if (loaded.isEmpty()) {
            ClassPrepareRequest cpr = erm.createClassPrepareRequest();
            cpr.addClassFilter(CLS);
            cpr.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);
            cpr.enable();
        } else {
            arm(erm, loaded.get(0));
        }
        vm.resume();
        EventQueue q = vm.eventQueue();
        int n = 0;
        while (true) {
            EventSet es;
            try { es = q.remove(); } catch (VMDisconnectedException e) { break; }
            for (Event e : es) {
                if (e instanceof ClassPrepareEvent) {
                    arm(erm, ((ClassPrepareEvent) e).referenceType());
                } else if (e instanceof ExceptionEvent) {
                    ExceptionEvent ee = (ExceptionEvent) e;
                    n++;
                    StringBuilder sb = new StringBuilder();
                    sb.append("[JDI] #" + n + " " + ee.exception().referenceType().name()
                            + " thrown in thread \"" + ee.thread().name() + "\"\n");
                    try {
                        int d = 0;
                        for (StackFrame f : ee.thread().frames()) {
                            Location l = f.location();
                            sb.append("[JDI]     at " + l.declaringType().name() + "."
                                    + l.method().name() + "(" + l.sourceName() + ":"
                                    + l.lineNumber() + ")\n");
                            if (++d >= 6) break;
                        }
                    } catch (Exception x) { sb.append("[JDI]     <" + x + ">\n"); }
                    System.out.print(sb);
                    System.out.flush();
                } else if (e instanceof VMDeathEvent || e instanceof VMDisconnectEvent) {
                    System.out.println("[JDI] target VM ended; " + n + " SessionMovedException throw(s) seen");
                    return;
                }
            }
            es.resume();
        }
        System.out.println("[JDI] target VM ended; " + n + " SessionMovedException throw(s) seen");
    }
    static void arm(EventRequestManager erm, ReferenceType t) {
        ExceptionRequest r = erm.createExceptionRequest(t, true, true);
        r.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);
        r.enable();
    }
}
EOF
"$JAVA_HOME/bin/javac" -cp "$JAVA_HOME/lib/tools.jar" -d "$OBS" "$OBS/SessionMovedObserver.java" || exit 2

# ---- 4. build (official Ant build, offline) --------------------------------
cd "$CLEAN"
timeout 15m ant -q compile-test > "$WD/build.log" 2>&1 || { tail -40 "$WD/build.log"; exit 2; }
echo "build OK"

# ---- 5. run via the target's test_command (Ant, report file) ----------------
echo "=== Ant run: ant -Dtestcase=SpeculaAdhocK1StaleOpenTest test-core-java"
timeout 10m ant -Dtestcase=SpeculaAdhocK1StaleOpenTest test-core-java > "$WD/ant-run.log" 2>&1
grep -E "Tests run|BUILD|junit\] Test " "$WD/ant-run.log"
REP=$CLEAN/build/test/logs/TEST-org.apache.zookeeper.test.SpeculaAdhocK1StaleOpenTest.txt
grep -E "^\[MC2|Tests run|SessionMovedException|FAILED|AssertionError" "$REP" | head -60
cp "$REP" "$WD/ant-report-SpeculaAdhocK1StaleOpenTest.txt"

# ---- 6. repeated runs, JUnit directly, with the JDI observer attached -------
CP="$CLEAN/build/classes:$CLEAN/build/test/classes:$CLEAN/conf"
for j in "$CLEAN"/build/lib/*.jar "$CLEAN"/build/test/lib/*.jar; do CP="$CP:$j"; done
PASS=0
for r in $(seq 1 "$RUNS"); do
  PORT=$((20000 + RANDOM % 20000))
  OUT=$WD/run-$r.log
  rm -rf "$CLEAN/build/test/tmp/run$r"; mkdir -p "$CLEAN/build/test/tmp/run$r"
  timeout 5m "$JAVA_HOME/bin/java" -agentlib:jdwp=transport=dt_socket,server=y,suspend=y,address=127.0.0.1:$PORT \
      -Dbuild.test.dir="$CLEAN/build/test/tmp/run$r" -Dlog4j.configuration=file:$CLEAN/conf/log4j.properties \
      -Dzookeeper.DigestAuthenticationProvider.superDigest=super:D/InIHSb7yEEbrWz8b9l71RjZJU= \
      -cp "$CP" org.junit.runner.JUnitCore org.apache.zookeeper.test.SpeculaAdhocK1StaleOpenTest \
      > "$OUT" 2>&1 &
  TPID=$!
  timeout 6m "$JAVA_HOME/bin/java" -cp "$OBS:$JAVA_HOME/lib/tools.jar" SessionMovedObserver $PORT > "$WD/jdi-$r.log" 2>&1 &
  OPID=$!
  wait $TPID; RC=$?
  wait $OPID
  echo "=== direct run $r (exit $RC)"
  grep -E "^\[MC2|^OK \(|^Tests run|FAILURES" "$OUT"
  grep -E "Got user-level KeeperException.*Session moved" "$OUT" | head -2
  # server-side frames of the first throw, plus the count
  awk '/^\[JDI\] #/{blk=$0; getline; blk=blk"\n"$0; getline; blk=blk"\n"$0; getline; blk=blk"\n"$0;
       if (blk ~ /SessionTrackerImpl.checkSession/ && !shown) {print blk; shown=1}} /target VM ended/{print}' "$WD/jdi-$r.log"
  echo "server-side throws at SessionTrackerImpl.checkSession(SessionTrackerImpl.java:246): $(grep -c 'at org.apache.zookeeper.server.SessionTrackerImpl.checkSession(SessionTrackerImpl.java:246)' "$WD/jdi-$r.log")"
  grep -q "BUG REPRODUCED" "$OUT" && PASS=$((PASS + 1))
done
echo "=== SUMMARY: bug triggered in $PASS / $RUNS direct runs"
[ "$PASS" -gt 0 ]
