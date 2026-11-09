#!/usr/bin/env bash
# CR-1 reproduction: an observer that fails ONE currentEpoch write during SNAP sync re-fires
# QuorumPeer.java:1236 on every registerWithLeader and never re-syncs.
#
# Variant of the target workload CurrentEpochWriteFailureTest (same module, same writeSomeData),
# with the fault injected the way EpochWriteFailureTest does (a QuorumPeer.writeLongToFile
# override). Neither the epoch files nor syncMode are written by the test in the bug tests.
#
# Usage: test_bugCR-1_observer_reload_loop.sh <source-tree> [surefire -Dtest filter suffix]
set -u
SRC=${1:?source tree}
FILTER=${2:-}
source /bulk/specula-adhoc/zookeeper/cases/zk-adhoc-11/env.sh
unset SPECULA_TRACE_FILE
T=$SRC/zookeeper-server/src/test/java/org/apache/zookeeper/server/quorum/BugCR1ObserverReloadLoopTest.java
cat > "$T" <<'JAVA'
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
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.stream.Collectors;
import javax.security.sasl.SaslException;
import org.apache.zookeeper.CreateMode;
import org.apache.zookeeper.PortAssignment;
import org.apache.zookeeper.ZooDefs.Ids;
import org.apache.zookeeper.ZooKeeper;
import org.apache.zookeeper.server.persistence.FileTxnSnapLog;
import org.apache.zookeeper.test.ClientBase;
import org.apache.zookeeper.test.ClientBase.CountdownWatcher;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

public class BugCR1ObserverReloadLoopTest extends QuorumPeerTestBase {

    static {
        // Other runs on this host hold the default range (thread 1 of 8); take a slice of our own.
        System.setProperty("test.junit.threads", "8");
        System.setProperty("zookeeper.junit.threadid", "7");
    }

    private enum Fault { NONE, THROW_ONCE, READ_ONLY_DIR_ONCE }

    private static final int PARTICIPANTS = 3;
    private final int[] clientPorts = new int[PARTICIPANTS + 1];
    private final MainThread[] mt = new MainThread[PARTICIPANTS + 1];
    private final Probe probe = new Probe();

    /** Observation only, apart from the one-shot fault and the control's syncMode reset. */
    static class Probe {
        volatile Fault fault = Fault.NONE;
        volatile boolean controlResetSyncMode = false;
        final AtomicBoolean faultFired = new AtomicBoolean();
        volatile String syncModeAtFault = "n/a";
        volatile String syncModeAtEpochWrite = "n/a";
        volatile String faultError = "n/a";
        final AtomicInteger observerAttempts = new AtomicInteger();
        final AtomicInteger registerFires = new AtomicInteger();
        final AtomicInteger startFires = new AtomicInteger();
        volatile String registerTrace;
        volatile String startTrace;
    }

    // The target throw statement spans QuorumPeer.java:1236-1238. javac puts `new` on 1236 and the
    // constructor call, where the JVM records the frame, on 1237 with the message argument (javap -l -c).
    private static boolean isTarget(Throwable c) {
        StackTraceElement f = c.getStackTrace()[0];
        return c.getClass() == IOException.class && c.getMessage().startsWith("The current epoch, ")
            && f.getClassName().equals(QuorumPeer.class.getName())
            && f.getMethodName().equals("loadDataBase") && f.getLineNumber() == 1237;
    }

    private static String describe(RuntimeException e) {
        Throwable c = e.getCause();
        return c + "\n" + Arrays.stream(c.getStackTrace()).limit(7)
            .map(f -> "    at " + f).collect(Collectors.joining("\n"));
    }

    static class ObservedPeer extends QuorumPeer {
        private final Probe p;

        ObservedPeer(Probe p) throws SaslException {
            this.p = p;
        }

        @Override
        void writeLongToFile(String name, long value) throws IOException {
            if (CURRENT_EPOCH_FILENAME.equals(name) && value != 0) {
                p.syncModeAtEpochWrite = getSyncMode().name();
                if (p.fault != Fault.NONE && getSyncMode() == SyncMode.SNAP && p.faultFired.compareAndSet(false, true)) {
                    p.syncModeAtFault = getSyncMode().name();
                    if (p.fault == Fault.THROW_ONCE) {
                        // As in EpochWriteFailureTest.CustomQuorumPeer
                        p.faultError = "java.io.IOException: Input/output error";
                        throw new IOException("Input/output error");
                    }
                    // A real OS error from the real write path, with nothing mocked
                    File dir = getTxnFactory().getSnapDir();
                    assertTrue(dir.setWritable(false));
                    try {
                        super.writeLongToFile(name, value);
                    } catch (IOException e) {
                        p.faultError = e.toString();
                        throw e;
                    } finally {
                        assertTrue(dir.setWritable(true));
                    }
                }
            }
            super.writeLongToFile(name, value);
        }

        @Override
        public long getLastLoggedZxid() {
            try {
                return super.getLastLoggedZxid();
            } catch (RuntimeException e) {
                if (e.getCause() instanceof IOException && isTarget(e.getCause())) {
                    p.registerFires.incrementAndGet();
                    p.registerTrace = describe(e);
                }
                throw e;
            }
        }

        @Override
        public synchronized void start() {
            try {
                super.start();
            } catch (RuntimeException e) {
                if (e.getCause() instanceof IOException && isTarget(e.getCause())) {
                    p.startFires.incrementAndGet();
                    p.startTrace = describe(e);
                }
                throw e;
            }
        }

        @Override
        protected Observer makeObserver(FileTxnSnapLog logFactory) throws IOException {
            p.observerAttempts.incrementAndGet();
            if (p.controlResetSyncMode) {
                // Control only: the stale-syncMode half of the mechanism removed
                setSyncMode(SyncMode.NONE);
            }
            return super.makeObserver(logFactory);
        }
    }

    private class ObservedQPMain extends TestQPMain {
        @Override
        protected QuorumPeer getQuorumPeer() throws SaslException {
            return new ObservedPeer(probe);
        }
    }

    private String quorumConfig() {
        StringBuilder sb = new StringBuilder("admin.enableServer=false\n");
        for (int i = 0; i <= PARTICIPANTS; i++) {
            clientPorts[i] = PortAssignment.unique();
            sb.append("server." + i + "=127.0.0.1:" + PortAssignment.unique() + ":" + PortAssignment.unique() + ":"
                      + (i == PARTICIPANTS ? "observer" : "participant") + ";127.0.0.1:" + clientPorts[i] + "\n");
        }
        return sb.toString();
    }

    private String addr(int i) {
        return "127.0.0.1:" + clientPorts[i];
    }

    // The workload's writeSomeData, against a chosen server
    private void writeSomeData(int server, int rounds) throws Exception {
        ZooKeeper client = ClientBase.createZKClient(addr(server));
        for (int i = 0; i < rounds; i++) {
            String path = "/somePath" + System.nanoTime();
            String data = "someData";
            client.create(path, data.getBytes(), Ids.OPEN_ACL_UNSAFE, CreateMode.PERSISTENT);
            assertEquals(data, new String(client.getData(path, false, null)));
        }
        client.close();
    }

    private void startQuorumWithData() throws Exception {
        String config = quorumConfig();
        for (int i = 0; i < PARTICIPANTS; i++) {
            mt[i] = new MainThread(i, clientPorts[i], config, false);
            mt[i].start();
        }
        for (int i = 0; i < PARTICIPANTS; i++) {
            assertTrue(ClientBase.waitForServerUp(addr(i), CONNECTION_TIMEOUT), "server " + i + " up");
        }
        writeSomeData(0, 2);
        mt[PARTICIPANTS] = new MainThread(PARTICIPANTS, clientPorts[PARTICIPANTS], config, "observer", false) {
            @Override
            public TestQPMain getTestQPMain() {
                return new ObservedQPMain();
            }
        };
    }

    private void report(String what) throws IOException {
        System.out.println("CR1| " + what + ": attempts=" + probe.observerAttempts.get()
            + " registerFires=" + probe.registerFires.get() + " startFires=" + probe.startFires.get());
    }

    private void dumpDisk() throws IOException {
        File dir = mt[PARTICIPANTS].getQuorumPeer().getTxnFactory().getSnapDir();
        System.out.println("CR1| observer disk " + Arrays.stream(dir.list()).sorted().collect(Collectors.toList())
            + " currentEpoch=" + new String(Files.readAllBytes(new File(dir, "currentEpoch").toPath()))
            + " acceptedEpoch=" + new String(Files.readAllBytes(new File(dir, "acceptedEpoch").toPath())));
    }

    private void waitForFires(int atLeast, long millis) throws InterruptedException {
        long end = System.currentTimeMillis() + millis;
        while (probe.registerFires.get() < atLeast && System.currentTimeMillis() < end) {
            Thread.sleep(50);
        }
    }

    /** One write fault, then watch the observer, a client, a leader change and a restart. */
    @Test
    @Timeout(value = 280)
    public void testOneEpochWriteFailureWedgesObserver() throws Exception {
        startQuorumWithData();
        probe.fault = Fault.THROW_ONCE;
        mt[PARTICIPANTS].start();

        waitForFires(1, CONNECTION_TIMEOUT);
        assertTrue(probe.faultFired.get(), "the injected fault must have fired");
        System.out.println("CR1| fault error=" + probe.faultError + " syncMode at fault=" + probe.syncModeAtFault);
        assertEquals("SNAP", probe.syncModeAtFault);
        assertTrue(probe.registerFires.get() >= 1, "QP:1236 must fire out of registerWithLeader");
        System.out.println("CR1| first registerWithLeader failure:\n" + probe.registerTrace);

        // The observer is given 45s, against 200ms of observer election delay between attempts
        boolean upInWindow = ClientBase.waitForServerUp(addr(PARTICIPANTS), 45000);
        report("after 45s");
        dumpDisk();
        assertFalse(upInWindow, "BUG: the observer should stay down");
        int firesAfterWindow = probe.registerFires.get();
        assertTrue(firesAfterWindow >= 5, "QP:1236 must re-fire repeatedly, fired " + firesAfterWindow);

        // The real consumer: a client that only knows the observer
        CountdownWatcher watcher = new CountdownWatcher();
        ZooKeeper client = new ZooKeeper(addr(PARTICIPANTS), CONNECTION_TIMEOUT, watcher);
        boolean connected = true;
        try {
            watcher.waitForConnected(10000);
        } catch (TimeoutException e) {
            connected = false;
        }
        System.out.println("CR1| client on observer connected=" + connected + " state=" + client.getState());
        client.close();
        assertFalse(connected, "BUG: a client of the observer must not be served");

        // The rest of the ensemble is healthy, so nothing but this peer's state is in the way
        writeSomeData(0, 2);
        System.out.println("CR1| participants serving writes: true");

        // Downstream mechanism 1: a new leader
        int leader = -1;
        for (int i = 0; i < PARTICIPANTS; i++) {
            if (mt[i].getQuorumPeer().leader != null) {
                leader = i;
            }
        }
        assertTrue(leader >= 0);
        mt[leader].shutdown();
        int other = leader == 0 ? 1 : 0;
        assertTrue(ClientBase.waitForServerUp(addr(other), CONNECTION_TIMEOUT), "new quorum up");
        writeSomeData(other, 1);
        int firesBeforeWait = probe.registerFires.get();
        waitForFires(firesBeforeWait + 5, 40000);
        report("after leader " + leader + " was replaced");
        assertTrue(probe.registerFires.get() > firesBeforeWait, "QP:1236 keeps firing under the new leader");
        assertFalse(ClientBase.waitForServerUp(addr(PARTICIPANTS), 3000), "BUG: still down under the new leader");

        // Downstream mechanism 2: an operator restart of the observer
        mt[PARTICIPANTS].shutdown();
        mt[PARTICIPANTS].start();
        long end = System.currentTimeMillis() + 20000;
        while (probe.startFires.get() == 0 && System.currentTimeMillis() < end) {
            Thread.sleep(50);
        }
        report("after observer restart");
        assertEquals(1, probe.startFires.get(), "QP:1236 must fire out of QuorumPeer.start on restart");
        System.out.println("CR1| restart failure:\n" + probe.startTrace);
        assertFalse(ClientBase.waitForServerUp(addr(PARTICIPANTS), 5000), "BUG: restart must not bring it back");
        System.out.println("CR1| RESULT bug-test: observer wedged, QP:1236 fired " + probe.registerFires.get()
            + " times from registerWithLeader and once from start");
    }

    /** The same, with a real EACCES out of the real write path instead of a thrown IOException. */
    @Test
    @Timeout(value = 200)
    public void testRealOsWriteErrorWedgesObserver() throws Exception {
        startQuorumWithData();
        probe.fault = Fault.READ_ONLY_DIR_ONCE;
        mt[PARTICIPANTS].start();
        waitForFires(1, CONNECTION_TIMEOUT);
        assertTrue(probe.faultFired.get(), "the injected fault must have fired");
        System.out.println("CR1| fault error=" + probe.faultError + " syncMode at fault=" + probe.syncModeAtFault);
        boolean upInWindow = ClientBase.waitForServerUp(addr(PARTICIPANTS), 30000);
        report("real OS error, after 30s");
        dumpDisk();
        assertFalse(upInWindow, "BUG: the observer should stay down");
        assertTrue(probe.registerFires.get() >= 5, "QP:1236 must re-fire repeatedly");
        System.out.println("CR1| RESULT real-OS-error: observer wedged");
    }

    /** Control: no fault. A fresh observer SNAP-syncs and serves, QP:1236 never fires. */
    @Test
    @Timeout(value = 120)
    public void testControlNoFault() throws Exception {
        startQuorumWithData();
        mt[PARTICIPANTS].start();
        assertTrue(ClientBase.waitForServerUp(addr(PARTICIPANTS), CONNECTION_TIMEOUT), "observer up");
        writeSomeData(PARTICIPANTS, 1);
        report("control no fault");
        System.out.println("CR1| syncMode at epoch write=" + probe.syncModeAtEpochWrite);
        assertEquals("SNAP", probe.syncModeAtEpochWrite);
        assertEquals(0, probe.registerFires.get());
        System.out.println("CR1| RESULT control-no-fault: observer serves, no fire");
    }

    /** Control: the same fault, with syncMode reset per attempt. One fire, then the observer heals. */
    @Test
    @Timeout(value = 120)
    public void testControlSyncModeResetHeals() throws Exception {
        startQuorumWithData();
        probe.fault = Fault.THROW_ONCE;
        probe.controlResetSyncMode = true;
        mt[PARTICIPANTS].start();
        assertTrue(ClientBase.waitForServerUp(addr(PARTICIPANTS), CONNECTION_TIMEOUT), "observer heals");
        writeSomeData(PARTICIPANTS, 1);
        report("control syncMode reset");
        assertTrue(probe.faultFired.get());
        assertEquals(1, probe.registerFires.get());
        dumpDisk();
        System.out.println("CR1| RESULT control-sync-reset: one fire, then observer serves");
    }

    @AfterEach
    public void tearDownAll() throws InterruptedException {
        for (MainThread t : mt) {
            if (t != null) {
                t.shutdown();
            }
        }
    }
}
JAVA
cd "$SRC" || exit 2
timeout 590 mvn -B -o test -pl zookeeper-server -Dcheckstyle.skip=true -Dspotbugs.skip=true \
  -Dtest="BugCR1ObserverReloadLoopTest$FILTER" -DfailIfNoTests=false -Dsurefire.failIfNoSpecifiedTests=false \
  2>&1 | tail -40 | cut -c1-220
rc=${PIPESTATUS[0]}
echo "=== mvn rc=$rc"
echo "=== target statement and its line table"
sed -n 1236,1238p zookeeper-server/src/main/java/org/apache/zookeeper/server/quorum/QuorumPeer.java | cut -c1-90
javap -c -l -p -cp zookeeper-server/target/classes org.apache.zookeeper.server.quorum.QuorumPeer \
  | awk '/private void loadDataBase/{f=1} f' | grep -E 'new .*java/io/IOException|invokespecial.*java/io/IOException."<init>"|line 123[678]:' | head -5
R=zookeeper-server/target/surefire-reports
for f in "$R"/*BugCR1ObserverReloadLoopTest*-output.txt "$R"/*BugCR1ObserverReloadLoopTest.txt; do
  [ -f "$f" ] || continue
  echo "=== $f"
  case "$f" in
    *-output.txt)
      grep -A9 'CR1|' "$f" | grep -E 'CR1\||^java.io.IOException: The current|^    at ' | sed -E 's#/[^ :]*/target/surefire/#<tmp>/#g' | cut -c1-200
      echo "log count of QP:1236 message: $(grep -c 'Unable to load database on disk' "$f")"
      ;;
    *) cat "$f" | cut -c1-200 | head -30 ;;
  esac
done
exit $rc
