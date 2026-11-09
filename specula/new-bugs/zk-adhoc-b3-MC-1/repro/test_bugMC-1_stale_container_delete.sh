#!/usr/bin/env bash
# MC-1: ContainerManager's stale deleteContainer removes a node a client re-created at the path;
# the client's getData then throws NoNodeException at FinalRequestProcessor.java:674.
#
# usage: test_bugMC-1_stale_container_delete.sh <pristine|worktree> [scenario ...]
#   scenarios (default: all)
#     workload            TestAdhocWorkloadB3#run, unmodified                     expect 0 frames (baseline)
#     level0-standalone   real ZooKeeperServerMain, all manager defaults, no hooks expect > 0 frames
#     level0-control      same manager and client ops, replaced BEFORE the scan    expect 0 frames
#     level0-quorum       real 3-peer quorum, leader's default manager, no hooks   expect > 0 frames
#     level1-persistent   counterexample order, PERSISTENT replacement             expect 2 frames (c6, after restart)
#     level1-container    counterexample order, fresh CONTAINER replacement        expect 1 frame
#     level1-control-*    post-before-create / replacement-has-child / ephemeral   expect 0 frames
#
# Nothing under src/main is edited. The throw frame comes from JDK Flight Recorder's
# jdk.JavaExceptionThrow event, because the server turns the exception into a reply code and never logs it.
# PASS for a scenario means: the observed frame count is what that scenario expects.
set -u
OUT=/users/ZhenyuLi/Specula/runs/20261102-193732-53d6/zk-adhoc-b3/.specula-output
WT=$OUT/confirmation/MC-1/worktree
BASE=eab16599
source /bulk/specula-adhoc/zookeeper/cases/zk-adhoc-b3/env.sh

MODE=${1:-pristine}; shift || true
SCENARIOS=("$@")
[ ${#SCENARIOS[@]} -eq 0 ] && SCENARIOS=(workload level0-standalone level0-control level0-quorum level1-persistent level1-container level1-control-post-before-create level1-control-child level1-control-ephemeral)

S=zookeeper-server/src/main/java/org/apache/zookeeper/server
T=zookeeper-server/src/test/java/org/apache/zookeeper/server
if [ "$MODE" = pristine ]; then
  TREE=${MC1_PRISTINE:-/tmp/mc1-pristine-$BASE}
  if [ ! -d "$TREE/$S" ]; then
    mkdir -p "$TREE"
    git -C "$WT" archive "$BASE" | tar -x -C "$TREE"
  fi
  for f in FinalRequestProcessor PrepRequestProcessor ContainerManager DataTree EphemeralType RequestThrottler; do
    git -C "$WT" show "$BASE:$S/$f.java" | cmp - "$TREE/$S/$f.java" || { echo "PRISTINE TREE DIFFERS: $f"; exit 3; }
  done
  [ -e "$TREE/$S/SpeculaTrace.java" ] && { echo "PRISTINE TREE HAS TRACE CODE"; exit 3; }
  cp "$WT/$T/TestAdhocWorkloadB3.java" "$TREE/$T/"
else
  TREE=$WT
fi
echo "== tree: $TREE  mode=$MODE  commit=$(git -C "$WT" rev-parse --short "$BASE")"
echo "== src/main diff vs $BASE: $(cd "$TREE" && if [ "$MODE" = pristine ]; then echo 'none (exported with git archive; six cited files compared with cmp)'; else git diff --stat "$BASE" -- zookeeper-server/src/main | tail -1; fi)"
echo "== handleGetDataRequest as compiled here:"; sed -n 670,675p "$TREE/$S/FinalRequestProcessor.java"
echo "== java: $(java -version 2>&1 | head -1)"

############################ variant tests (same module as the workload) ############################
cat > "$TREE/$T/SpeculaAdhocB3Mc1Level0Test.java" <<'JAVA'
package org.apache.zookeeper.server;

import static org.junit.jupiter.api.Assertions.assertTrue;
import java.io.File;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.apache.jute.Record;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.KeeperException;
import org.apache.zookeeper.Op;
import org.apache.zookeeper.PortAssignment;
import org.apache.zookeeper.ZKTestCase;
import org.apache.zookeeper.ZooDefs;
import org.apache.zookeeper.ZooDefs.Ids;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.data.Stat;
import org.apache.zookeeper.server.ZooKeeperServerMainTest.MainThread;
import org.apache.zookeeper.server.persistence.FileTxnLog;
import org.apache.zookeeper.server.persistence.TxnLog.TxnIterator;
import org.apache.zookeeper.test.ClientBase;
import org.apache.zookeeper.test.QuorumUtil;
import org.apache.zookeeper.txn.DeleteTxn;
import org.apache.zookeeper.txn.TxnHeader;
import org.junit.jupiter.api.Test;

/**
 * Level 0: the workload's client operations over many containers against the server's own manager.
 * No manager subclass, no hook, no sleep inside the server, no znode.container.* property: pacing is
 * the production default of one post per 6 ms, so the scan's result ages for seconds.
 */
public class SpeculaAdhocB3Mc1Level0Test extends ZKTestCase {

    private static final String PATH = "/adhoc-workload-b3-";
    private static final long MANAGER_WAIT_MS = 120000;
    /** Default pacing is 60000 / 10000 = 6 ms per candidate. */
    private static final long PACING_MS = 6;

    private static void out(String s) {
        System.out.println("MC1| " + s);
    }

    private static void defaultsUntouched() {
        out("znode.container.checkIntervalMs=" + System.getProperty("znode.container.checkIntervalMs")
                + " znode.container.maxPerMinute=" + System.getProperty("znode.container.maxPerMinute"));
    }

    /** The workload's c1-c3 for each path, batched so that setup ends well before the first scan at 60 s. */
    private static List<String> makeUsedEmptyContainers(ZooKeeper zk, String prefix, int n) throws Exception {
        List<String> paths = new ArrayList<>();
        List<Op> batch = new ArrayList<>();
        for (int i = 0; i < n; i++) {
            String p = prefix + i;
            batch.add(Op.create(p, new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.CONTAINER));
            batch.add(Op.create(p + "/child", new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT));
            batch.add(Op.delete(p + "/child", -1));
            paths.add(p);
            if (batch.size() >= 150 || i == n - 1) {
                zk.multi(batch);
                batch.clear();
            }
        }
        return paths;
    }

    /** A scan during setup would leave nothing to go stale: that run says nothing about the bug. */
    private static void setupBeforeFirstScan(ZooKeeper zk, int n, long t0) throws Exception {
        long ms = System.currentTimeMillis() - t0;
        int nodes = zk.getAllChildrenNumber("/");
        out("setup: " + n + " used empty containers in " + ms + " ms; nodes under / = " + nodes);
        assertTrue(ms < 50000 && nodes >= n, "INCONCLUSIVE: setup crossed the manager's first scan");
    }

    /** The only sign of the manager's scan a client has: its first deletion. */
    private static void awaitFirstManagerDeletion(ZooKeeper zk) throws Exception {
        int baseline = zk.getAllChildrenNumber("/");
        long end = System.currentTimeMillis() + MANAGER_WAIT_MS;
        while (zk.getAllChildrenNumber("/") >= baseline) {
            assertTrue(System.currentTimeMillis() < end, "the manager never ran");
            Thread.sleep(10);
        }
    }

    /** The workload's c4-c6 for each path: same calls, same tolerance of a cleaned container. */
    private static Map<String, Long> replaceAndRead(ZooKeeper zk, List<String> paths) throws Exception {
        Map<String, Long> czxid = new HashMap<>();
        int cleaned = 0;
        int inline = 0;
        for (String p : paths) {
            try {
                zk.delete(p, -1);
            } catch (KeeperException.NoNodeException alreadyCleaned) {
                cleaned++;
            }
            Stat stat = new Stat();
            zk.create(p, new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT, stat);
            czxid.put(p, stat.getCzxid());
            try {
                zk.getData(p, false, null);
            } catch (KeeperException.NoNodeException e) {
                inline++;
                out("IMMEDIATE c6 getData threw " + e + " right after this client's create returned czxid=0x"
                        + Long.toHexString(stat.getCzxid()));
            }
        }
        out("client replaced " + paths.size() + " paths; delete found already cleaned=" + cleaned + "; immediate c6 NoNode=" + inline);
        return czxid;
    }

    private static List<String> readAll(ZooKeeper zk, List<String> paths) throws Exception {
        List<String> missing = new ArrayList<>();
        for (String p : paths) {
            try {
                zk.getData(p, false, null);
            } catch (KeeperException.NoNodeException e) {
                missing.add(p);
            }
        }
        return missing;
    }

    /** Who deleted each lost node, from the durable transaction log. */
    private static void attribute(File version2, Map<String, Long> czxid, List<String> lost) throws Exception {
        Map<String, Long> managerDelete = new HashMap<>();
        Map<String, Long> managerDeleteClient = new HashMap<>();
        Map<String, Long> clientDelete = new HashMap<>();
        TxnIterator it = new FileTxnLog(version2).read(1);
        try {
            while (it.getHeader() != null) {
                TxnHeader h = it.getHeader();
                Record r = it.getTxn();
                if (r instanceof DeleteTxn) {
                    String p = ((DeleteTxn) r).getPath();
                    if (h.getType() == ZooDefs.OpCode.deleteContainer) {
                        managerDelete.put(p, h.getZxid());
                        managerDeleteClient.put(p, h.getClientId());
                    } else {
                        clientDelete.put(p, h.getZxid());
                    }
                }
                if (!it.next()) {
                    break;
                }
            }
        } finally {
            it.close();
        }
        int byStale = 0;
        int byClient = 0;
        for (String p : lost) {
            Long dc = managerDelete.get(p);
            Long d = clientDelete.get(p);
            if (dc != null && dc > czxid.get(p)) {
                byStale++;
            }
            if (d != null && d > czxid.get(p)) {
                byClient++;
            }
        }
        out("txnlog: lost=" + lost.size() + " removedByDeleteContainerAfterClientCreate=" + byStale
                + " removedByAClientDeleteAfterClientCreate=" + byClient);
        if (!lost.isEmpty()) {
            String p = lost.get(0);
            out("txnlog sample " + p + ": client create czxid=0x" + Long.toHexString(czxid.get(p))
                    + "; deleteContainer zxid=0x" + Long.toHexString(managerDelete.get(p))
                    + " session=0x" + Long.toHexString(managerDeleteClient.get(p)));
        }
    }

    @Test
    public void standalone() throws Exception {
        int n = 1000;
        ClientBase.setupTestEnv();
        defaultsUntouched();
        int port = PortAssignment.unique();
        String hp = "127.0.0.1:" + port;
        MainThread main = new MainThread(port, true, null);
        main.start();
        assertTrue(ClientBase.waitForServerUp(hp, ClientBase.CONNECTION_TIMEOUT));
        ZooKeeper zk = ClientBase.createZKClient(hp);
        long t0 = System.currentTimeMillis();
        List<String> paths = makeUsedEmptyContainers(zk, PATH, n);
        setupBeforeFirstScan(zk, n, t0);
        awaitFirstManagerDeletion(zk);
        out("manager's first deletion seen " + (System.currentTimeMillis() - t0) + " ms after setup began; client replaces now");
        long t1 = System.currentTimeMillis();
        Map<String, Long> czxid = replaceAndRead(zk, paths);
        out("replace loop took " + (System.currentTimeMillis() - t1) + " ms");
        Thread.sleep(n * PACING_MS + 3000);
        List<String> lost = readAll(zk, paths);
        out("RESULT later getData NoNode on " + lost.size() + " of " + n
                + " nodes this client created and never deleted; first=" + (lost.isEmpty() ? null : lost.get(0)));
        zk.close();

        main.shutdown();
        main.join(30000);
        attribute(new File(main.logDir, "version-2"), czxid, lost);

        MainThread again = new MainThread(port, null, false, main.tmpDir, null);
        again.start();
        assertTrue(ClientBase.waitForServerUp(hp, ClientBase.CONNECTION_TIMEOUT));
        ZooKeeper zk2 = ClientBase.createZKClient(hp);
        List<String> lostAfterRestart = readAll(zk2, paths);
        out("AFTER RESTART getData NoNode on " + lostAfterRestart.size() + " nodes; same set=" + lostAfterRestart.equals(lost));
        zk2.close();
        again.shutdown();
        again.join(30000);
        out("TOTAL expected line-674 frames = immediate c6 hits above + " + lost.size() + " + " + lostAfterRestart.size());
        assertTrue(!lost.isEmpty(), "no node was lost");
    }

    /** Same manager, same operations; the replacement finishes before the scan, so nothing is stale. */
    @Test
    public void controlReplacedBeforeScan() throws Exception {
        int n = 200;
        ClientBase.setupTestEnv();
        defaultsUntouched();
        int port = PortAssignment.unique();
        String hp = "127.0.0.1:" + port;
        MainThread main = new MainThread(port, true, null);
        main.start();
        assertTrue(ClientBase.waitForServerUp(hp, ClientBase.CONNECTION_TIMEOUT));
        ZooKeeper zk = ClientBase.createZKClient(hp);
        long t0 = System.currentTimeMillis();
        List<String> paths = makeUsedEmptyContainers(zk, PATH, n);
        replaceAndRead(zk, paths);
        // never replaced: its deletion tells the client that the manager's scan came after the replacements
        makeUsedEmptyContainers(zk, "/sentinel-", 1);
        out("replacement done " + (System.currentTimeMillis() - t0) + " ms after setup began (first scan is at about 60000 ms)");
        awaitFirstManagerDeletion(zk);
        out("sentinel deleted by the manager " + (System.currentTimeMillis() - t0) + " ms after setup began");
        Thread.sleep(3000);
        List<String> lost = readAll(zk, paths);
        out("RESULT later getData NoNode on " + lost.size() + " of " + n + " nodes");
        zk.close();
        main.shutdown();
        main.join(30000);
        assertTrue(lost.isEmpty(), "control lost nodes");
    }

    /** The leader's own manager (LeaderZooKeeperServer.java:80) in a real quorum. */
    @Test
    public void quorum() throws Exception {
        int n = 1000;
        defaultsUntouched();
        QuorumUtil qu = new QuorumUtil(1);
        qu.startAll();
        ZooKeeper zk = ClientBase.createZKClient(qu.getConnString());
        long t0 = System.currentTimeMillis();
        List<String> paths = makeUsedEmptyContainers(zk, PATH, n);
        setupBeforeFirstScan(zk, n, t0);
        awaitFirstManagerDeletion(zk);
        out("manager's first deletion seen; client replaces now");
        Map<String, Long> czxid = replaceAndRead(zk, paths);
        Thread.sleep(n * PACING_MS + 3000);
        List<String> lost = readAll(zk, paths);
        int leader = qu.getLeaderServer();
        out("leader is peer " + leader + " type=" + qu.getPeer(leader).peer.getActiveServer().getClass().getSimpleName());
        out("RESULT later getData NoNode on " + lost.size() + " of " + n
                + " nodes this client created and never deleted; first=" + (lost.isEmpty() ? null : lost.get(0)));
        zk.close();
        File dataDir = qu.getPeer(leader).dataDir;
        qu.shutdownAll();
        attribute(new File(dataDir, "version-2"), czxid, lost);
        qu.startAll();
        ZooKeeper zk2 = ClientBase.createZKClient(qu.getConnString());
        List<String> lostAfterRestart = readAll(zk2, paths);
        out("AFTER QUORUM RESTART getData NoNode on " + lostAfterRestart.size() + " nodes; same set=" + lostAfterRestart.equals(lost));
        zk2.close();
        qu.shutdownAll();
        out("TOTAL expected line-674 frames = immediate c6 hits above + " + lost.size() + " + " + lostAfterRestart.size());
        assertTrue(!lost.isEmpty(), "no node was lost");
    }
}
JAVA

cat > "$TREE/$T/SpeculaAdhocB3Mc1Level1Test.java" <<'JAVA'
package org.apache.zookeeper.server;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import java.util.Collection;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.KeeperException;
import org.apache.zookeeper.ZooDefs.Ids;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.data.Stat;
import org.apache.zookeeper.test.ClientBase;
import org.junit.jupiter.api.Test;

/**
 * Level 1: TestAdhocWorkloadB3's client, path and manager constructor. The workload delays the post by
 * a fixed 3 s in postDeleteRequest; this variant holds it at the same hook until the counterexample's
 * step. The scan, the post and everything behind them are the real code.
 */
public class SpeculaAdhocB3Mc1Level1Test extends ClientBase {

    private static final String PATH = "/adhoc-workload-b3";
    private static final int CHECK_MS = 100;
    private static final int NO_PACING = Integer.MAX_VALUE;
    private static final long WAIT_S = 30;

    private static void out(String s) {
        System.out.println("MC1| " + s);
    }

    private static final class HeldManager extends ContainerManager {

        private final CountDownLatch scanned = new CountDownLatch(1);
        private final CountDownLatch release = new CountDownLatch(1);
        private final CountDownLatch posted = new CountDownLatch(1);

        HeldManager(ZooKeeperServer server) {
            super(server.getZKDatabase(), server.firstProcessor, CHECK_MS, NO_PACING);
        }

        @Override
        protected Collection<String> getCandidates() {
            Collection<String> candidates = super.getCandidates();
            out("MgrScan candidates=" + candidates);
            scanned.countDown();
            return candidates;
        }

        @Override
        public void checkContainers() throws InterruptedException {
            try {
                super.checkContainers();
            } finally {
                stop();
            }
        }

        @Override
        protected void postDeleteRequest(Request request) throws RequestProcessor.RequestProcessorException {
            try {
                assertTrue(release.await(WAIT_S, TimeUnit.SECONDS));
            } catch (InterruptedException stopped) {
                Thread.currentThread().interrupt();
                return;
            }
            super.postDeleteRequest(request);
            posted.countDown();
        }

        void post() throws InterruptedException {
            release.countDown();
            assertTrue(posted.await(WAIT_S, TimeUnit.SECONDS));
            out("MgrPost stale deleteContainer entered PrepRequestProcessor's queue");
        }
    }

    /** c1-c3 and the scan. */
    private HeldManager usedEmptyContainerScanned(ZooKeeper zk) throws Exception {
        zk.create(PATH, new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.CONTAINER);
        zk.create(PATH + "/child", new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        zk.delete(PATH + "/child", -1);
        HeldManager manager = new HeldManager(serverFactory.getZooKeeperServer());
        manager.start();
        assertTrue(manager.scanned.await(WAIT_S, TimeUnit.SECONDS));
        return manager;
    }

    private long c5(ZooKeeper zk, CreateMode mode) throws Exception {
        Stat stat = new Stat();
        zk.create(PATH, new byte[0], Ids.OPEN_ACL_UNSAFE, mode, stat);
        out("c5 create(" + mode + ") returned OK czxid=0x" + Long.toHexString(stat.getCzxid()));
        return stat.getCzxid();
    }

    @Test
    public void persistent() throws Exception {
        ZooKeeper zk = createClient();
        HeldManager manager = usedEmptyContainerScanned(zk);
        zk.delete(PATH, -1);
        out("c4 delete returned OK");
        c5(zk, CreateMode.PERSISTENT);
        manager.post();
        KeeperException.NoNodeException e = assertThrows(KeeperException.NoNodeException.class, () -> zk.getData(PATH, false, null));
        out("RESULT c6 getData threw " + e);
        assertNull(zk.exists(PATH, false));
        out("exists after c6 = null; this client issued no delete after c5");
        zk.close();

        stopServer();
        startServer();
        ZooKeeper again = createClient();
        assertNull(again.exists(PATH, false));
        KeeperException.NoNodeException e2 = assertThrows(KeeperException.NoNodeException.class, () -> again.getData(PATH, false, null));
        out("AFTER RESTART exists = null; getData threw " + e2);
        out("TOTAL expected line-674 frames = 2");
    }

    @Test
    public void container() throws Exception {
        ZooKeeper zk = createClient();
        HeldManager manager = usedEmptyContainerScanned(zk);
        zk.delete(PATH, -1);
        c5(zk, CreateMode.CONTAINER);
        manager.post();
        KeeperException.NoNodeException e = assertThrows(KeeperException.NoNodeException.class, () -> zk.getData(PATH, false, null));
        out("RESULT c6 getData threw " + e + " (fresh container, cversion 0, never a candidate)");
        out("TOTAL expected line-674 frames = 1");
    }

    /** The post between c4 and c5: PrepRequestProcessor finds no node, so the stale delete is rejected. */
    @Test
    public void controlPostBeforeCreate() throws Exception {
        ZooKeeper zk = createClient();
        HeldManager manager = usedEmptyContainerScanned(zk);
        zk.delete(PATH, -1);
        manager.post();
        zk.exists("/", false);
        c5(zk, CreateMode.PERSISTENT);
        zk.getData(PATH, false, null);
        out("RESULT c6 getData OK");
        assertNotNull(zk.exists(PATH, false));
        out("TOTAL expected line-674 frames = 0");
    }

    /** A child in the replacement: childCount > 0 rejects the stale delete. */
    @Test
    public void controlReplacementHasChild() throws Exception {
        ZooKeeper zk = createClient();
        HeldManager manager = usedEmptyContainerScanned(zk);
        zk.delete(PATH, -1);
        c5(zk, CreateMode.PERSISTENT);
        zk.create(PATH + "/child", new byte[0], Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
        manager.post();
        zk.getData(PATH, false, null);
        out("RESULT c6 getData OK");
        assertEquals(1, zk.getChildren(PATH, false).size());
        out("TOTAL expected line-674 frames = 0");
    }

    /** An EPHEMERAL replacement: EphemeralType NORMAL rejects the stale delete. */
    @Test
    public void controlEphemeral() throws Exception {
        ZooKeeper zk = createClient();
        HeldManager manager = usedEmptyContainerScanned(zk);
        zk.delete(PATH, -1);
        c5(zk, CreateMode.EPHEMERAL);
        manager.post();
        zk.getData(PATH, false, null);
        out("RESULT c6 getData OK");
        out("TOTAL expected line-674 frames = 0");
    }
}
JAVA

######################################### JFR wrapper and parser #########################################
scan_frames() {  # scan_frames <jfr_dir>: count and show server-side throws at FinalRequestProcessor:674
  local dir=$1 f
  for f in "$dir"/fork-*.jfr; do
    [ -s "$f" ] || continue
    jfr print --events jdk.JavaExceptionThrow --stack-depth 16 "$f" 2>/dev/null
  done | python3 -c '
import re, sys, collections
text = sys.stdin.read()
blocks = re.findall(r"jdk\.JavaExceptionThrow \{.*?\n\}", text, re.S)
hits, threads = [], collections.Counter()
for b in blocks:
    if "KeeperException$NoNodeException" not in b.split("stackTrace")[0]:
        continue
    frames = [l.strip() for l in b.split("stackTrace = [")[1].splitlines() if " line: " in l]
    top = [l for l in frames if not re.match(r"(java\.lang\.(Throwable|Exception)|org\.apache\.zookeeper\.KeeperException(\$NoNodeException)?)\.<init>", l)]
    if top and top[0].startswith("org.apache.zookeeper.server.FinalRequestProcessor.handleGetDataRequest") and top[0].endswith("line: 674"):
        hits.append(b)
        threads[re.search(r"eventThread = \"([^\"]+)\"", b).group(1)] += 1
print("FRAMES@674 %d" % len(hits))
if hits:
    print("threads: %s" % dict(threads))
    print(hits[0])
'
}

run_one() {  # run_one <scenario> <-Dtest value> <expected: 0, N or +>
  local name=$1 testspec=$2 expect=$3 d rc frames
  d=$(mktemp -d /tmp/mc1-jfr.XXXXXX)
  mkdir -p "$d/bin"
  cat > "$d/ex.jfc" <<'JFC'
<?xml version="1.0" encoding="UTF-8"?>
<configuration version="2.0"><event name="jdk.JavaExceptionThrow"><setting name="enabled">true</setting><setting name="stackTrace">true</setting></event></configuration>
JFC
  cat > "$d/bin/java" <<'WRAP'
#!/usr/bin/env bash
exec "$JAVA_HOME/bin/java" "-XX:StartFlightRecording=filename=$JFR_DIR/fork-$$.jfr,settings=$JFR_DIR/ex.jfc,dumponexit=true" "$@"
WRAP
  chmod +x "$d/bin/java"
  rm -rf "$TREE/zookeeper-server/target/surefire-reports" "$TREE/zookeeper-server/target/surefire"
  echo
  echo "################ scenario: $name"
  echo "== cmd: mvn -B -o test -pl zookeeper-server -Dtest='$testspec' -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false -Djvm=<JFR wrapper> -Dcheckstyle.skip=true -Dspotbugs.skip=true"
  ( cd "$TREE" && JFR_DIR=$d timeout 560 mvn -B -o test -pl zookeeper-server -Dtest="$testspec" \
      -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false -Djvm="$d/bin/java" \
      -Dcheckstyle.skip=true -Dspotbugs.skip=true > "$d/mvn.log" 2>&1 )
  rc=$?
  echo "== mvn exit=$rc"
  grep -E 'Tests run:.*(Time elapsed|Failures)|BUILD (SUCCESS|FAILURE)|^\[ERROR\].*(COMPILATION|\.java|expected|Test\.)' "$d/mvn.log" | head -12
  local outfile
  for outfile in "$TREE"/zookeeper-server/target/surefire-reports/*-output.txt; do
    [ -f "$outfile" ] || continue
    cp "$outfile" "$d/"
    grep -h 'MC1| ' "$outfile" | sed 's/^.*MC1| /MC1| /'
    grep -hoE 'Using checkIntervalMs=[0-9]+ maxPerMinute=[0-9]+ maxNeverUsedIntervalMs=[0-9]+' "$outfile" | sort | uniq -c
    echo "manager log lines 'Attempting to delete candidate container': $(grep -c 'Attempting to delete candidate container' "$outfile")"
  done
  local scan; scan=$(scan_frames "$d")
  echo "$scan"
  frames=$(echo "$scan" | sed -n 's/^FRAMES@674 //p')
  local ok=FAIL
  case "$expect" in
    +) [ "${frames:-0}" -gt 0 ] && ok=PASS ;;
    *) [ "${frames:-x}" = "$expect" ] && ok=PASS ;;
  esac
  [ "$rc" -eq 0 ] || ok=FAIL
  echo "== SCENARIO $name: mvn_exit=$rc frames_at_FinalRequestProcessor_674=${frames:-?} expected=$expect -> $ok  (artifacts: $d)"
  [ "$ok" = PASS ] || FAILED=1
}

FAILED=0
for s in "${SCENARIOS[@]}"; do
  case "$s" in
    workload)          run_one "$s" 'TestAdhocWorkloadB3#run' 0 ;;
    level0-standalone) run_one "$s" 'SpeculaAdhocB3Mc1Level0Test#standalone' + ;;
    level0-control)    run_one "$s" 'SpeculaAdhocB3Mc1Level0Test#controlReplacedBeforeScan' 0 ;;
    level0-quorum)     run_one "$s" 'SpeculaAdhocB3Mc1Level0Test#quorum' + ;;
    level1-persistent) run_one "$s" 'SpeculaAdhocB3Mc1Level1Test#persistent' 2 ;;
    level1-container)  run_one "$s" 'SpeculaAdhocB3Mc1Level1Test#container' 1 ;;
    level1-control-post-before-create) run_one "$s" 'SpeculaAdhocB3Mc1Level1Test#controlPostBeforeCreate' 0 ;;
    level1-control-child)     run_one "$s" 'SpeculaAdhocB3Mc1Level1Test#controlReplacementHasChild' 0 ;;
    level1-control-ephemeral) run_one "$s" 'SpeculaAdhocB3Mc1Level1Test#controlEphemeral' 0 ;;
    *) echo "unknown scenario $s"; FAILED=1 ;;
  esac
done
if [ "$MODE" = worktree ]; then rm -f "$WT/$T/SpeculaAdhocB3Mc1Level0Test.java" "$WT/$T/SpeculaAdhocB3Mc1Level1Test.java"; fi
echo
echo "== OVERALL failed=$FAILED"
exit "$FAILED"
