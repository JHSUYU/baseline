/**
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
package org.apache.hadoop.hdfs;

import static org.junit.Assert.assertTrue;

import java.io.File;
import java.util.List;
import java.util.Map;

import com.sun.jdi.Bootstrap;
import com.sun.jdi.Location;
import com.sun.jdi.ReferenceType;
import com.sun.jdi.ThreadReference;
import com.sun.jdi.VirtualMachine;
import com.sun.jdi.connect.AttachingConnector;
import com.sun.jdi.connect.Connector;
import com.sun.jdi.event.BreakpointEvent;
import com.sun.jdi.event.Event;
import com.sun.jdi.event.EventSet;
import com.sun.jdi.request.BreakpointRequest;
import com.sun.jdi.request.EventRequest;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hdfs.server.common.HdfsServerConstants.StartupOption;
import org.apache.hadoop.hdfs.server.common.Storage;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.junit.BeforeClass;
import org.junit.Test;

/**
 * MC-1 reproduction: variant of TestAdhocWorkload7 (NN -upgrade, one DN with
 * two storage directories holding pre-upgrade block pool storage).
 *
 * The target is the IOException thrown at BlockPoolSliceStorage.java:422.
 * The race: DataStorage.loadBlockPoolSliceStorage (DataStorage.java:452-466)
 * submits volume 1's upgrade callable (BPSS:493-500) to the executor and then
 * runs volume 2's doTransition on the startup thread. The callable writes the
 * shared fields this.layoutVersion (BPSS:510) and this.cTime (BPSS:513) of the
 * single per-block-pool BlockPoolSliceStorage object, which volume 2's
 * doTransition re-reads at BPSS:405-406 and BPSS:415-416.
 *
 * level0: workload run as written, repeated; no timing help.
 * level1: same workload; a JDWP debugger attached to this JVM is used only as
 *   a scheduler (breakpoints that hold and release threads). No source code,
 *   no field value and no on-disk state is touched by the test. The schedule:
 *     1. hold volume 1's callable at BPSS:510 (before it writes LV/cTime);
 *     2. let the startup thread run volume 2's doTransition up to BPSS:409
 *        (it has evaluated BPSS:405-406 with cTime = C0 read from disk);
 *     3. release the callable; wait until it reaches BPSS:518 (after 510/513);
 *     4. release volume 2, which now evaluates BPSS:415-416 with cTime = C1.
 */
public class TestBugMC1StartupUpgradeRace {

  private static final String BPSS =
      "org.apache.hadoop.hdfs.server.datanode.BlockPoolSliceStorage";
  // The target statement is the multi-line `throw new IOException(...)` at
  // BPSS:422-425. javac's line table maps its `new` (bci 409) to line 422 and
  // the IOException.<init> call to line 425, so the stack frame of the thrown
  // exception reads ":425" (verified with javap by the runner). No other throw
  // exists on lines 422-425.
  private static final java.util.regex.Pattern TARGET_FRAME =
      java.util.regex.Pattern.compile(
          "BlockPoolSliceStorage\\.doTransition\\(BlockPoolSliceStorage"
          + "\\.java:42[2-5]\\)");
  private static final String TARGET_MSG = "is newer than the namespace state";

  private static boolean targetFired(String out) {
    return out.contains(TARGET_MSG) && TARGET_FRAME.matcher(out).find();
  }

  @BeforeClass
  public static void initialize() throws Exception {
    UpgradeUtilities.initialize();
  }

  /** One run of the workload. Returns the captured Storage log. */
  private String runWorkloadOnce(Runnable beforeDataNodeStart,
      String label) throws Exception {
    final int numDirs = 2;
    Configuration conf = new HdfsConfiguration();
    conf = UpgradeUtilities.initializeStorageStateConf(numDirs, conf);
    String[] nameNodeDirs =
        conf.getStrings(DFSConfigKeys.DFS_NAMENODE_NAME_DIR_KEY);
    String[] dataNodeDirs =
        conf.getStrings(DFSConfigKeys.DFS_DATANODE_DATA_DIR_KEY);
    conf.setBoolean(DFSConfigKeys.DFS_DATANODE_DUPLICATE_REPLICA_DELETION,
        false);

    UpgradeUtilities.createNameNodeStorageDirs(nameNodeDirs, "current");
    MiniDFSCluster cluster = new MiniDFSCluster.Builder(conf).numDataNodes(0)
        .format(false)
        .manageDataDfsDirs(false)
        .manageNameDfsDirs(false)
        .startupOption(StartupOption.UPGRADE)
        .build();
    LogCapturer logs = LogCapturer.captureLogs(Storage.LOG);
    try {
      UpgradeUtilities.createDataNodeStorageDirs(dataNodeDirs, "current");
      if (beforeDataNodeStart != null) {
        beforeDataNodeStart.run();
      }
      cluster.startDataNodes(conf, 1, false, StartupOption.REGULAR, null);
      String bpid = UpgradeUtilities.getCurrentBlockPoolID(null);
      System.out.println("[MC-1][" + label + "] isBPServiceAlive="
          + cluster.getDataNodes().get(0).isBPServiceAlive(bpid));
      for (String baseDir : dataNodeDirs) {
        File previous = new File(baseDir, "current/" + bpid + "/previous");
        System.out.println("[MC-1][" + label + "] " + baseDir
            + " bp previous/ exists=" + previous.isDirectory());
      }
      return logs.getOutput();
    } finally {
      logs.stopCapturing();
      cluster.shutdown();
      UpgradeUtilities.createEmptyDirs(nameNodeDirs);
      UpgradeUtilities.createEmptyDirs(dataNodeDirs);
    }
  }

  @Test(timeout = 600000)
  public void level0BlackBox() throws Exception {
    int rounds = Integer.getInteger("mc1.level0.rounds", 10);
    int fired = 0;
    for (int i = 0; i < rounds; i++) {
      String out = runWorkloadOnce(null, "L0#" + i);
      if (targetFired(out)) {
        fired++;
      }
    }
    System.out.println("[MC-1][L0] target fired in " + fired + " of "
        + rounds + " rounds");
  }

  @Test(timeout = 300000)
  public void level1DebuggerSchedule() throws Exception {
    int port = Integer.getInteger("mc1.jdwp.port");
    Class.forName(BPSS);  // make sure the class is loaded before breakpoints
    final Scheduler sched = new Scheduler(port);
    String out;
    try {
      out = runWorkloadOnce(sched::start, "L1");
    } finally {
      sched.stop();
    }
    System.out.println("[MC-1][L1] schedule realized=" + sched.realized
        + " events=" + sched.trace);
    for (String line : out.split("\n")) {
      if (line.contains("Failed to add storage directory")
          || line.contains("is newer than the namespace state")
          || line.contains("BlockPoolSliceStorage.doTransition")
          || line.contains("BlockPoolSliceStorage.recoverTransitionRead")
          || line.contains("DataStorage.loadBlockPoolSliceStorage")
          || line.contains("Upgrade of block pool")) {
        System.out.println("[MC-1][L1][log] " + line);
      }
    }
    assertTrue("schedule not realized", sched.realized);
    assertTrue("target IOException at BPSS:422 not thrown", targetFired(out));
    System.out.println("[MC-1][L1] TARGET FIRED: IOException from "
        + "BlockPoolSliceStorage.doTransition, statement BPSS:422");
  }

  /** JDWP breakpoints used only to order threads; values are not touched. */
  static final class Scheduler {
    private final int port;
    private VirtualMachine vm;
    private Thread loop;
    volatile boolean realized = false;
    final StringBuffer trace = new StringBuffer();

    Scheduler(int port) {
      this.port = port;
    }

    void start() {
      try {
        AttachingConnector c = null;
        for (AttachingConnector a :
            Bootstrap.virtualMachineManager().attachingConnectors()) {
          if (a.name().equals("com.sun.jdi.SocketAttach")) {
            c = a;
          }
        }
        Map<String, Connector.Argument> args = c.defaultArguments();
        args.get("hostname").setValue("localhost");
        args.get("port").setValue(String.valueOf(port));
        vm = c.attach(args);
        ReferenceType bpss = vm.classesByName(BPSS).get(0);
        bp(bpss, 409);  // volume's doTransition, after BPSS:405-406
        bp(bpss, 510);  // callable, before this.layoutVersion = DNLV
        bp(bpss, 518);  // callable, after this.cTime = nsCTime (BPSS:513)
      } catch (Exception e) {
        throw new RuntimeException(e);
      }
      loop = new Thread(this::eventLoop, "mc1-jdi-scheduler");
      loop.setDaemon(true);
      loop.start();
    }

    private void bp(ReferenceType t, int line) throws Exception {
      List<Location> locs = t.locationsOfLine(line);
      BreakpointRequest r =
          vm.eventRequestManager().createBreakpointRequest(locs.get(0));
      r.setSuspendPolicy(EventRequest.SUSPEND_EVENT_THREAD);
      r.enable();
    }

    private void eventLoop() {
      int hits409 = 0;
      ThreadReference heldCallable = null;
      ThreadReference heldVolume2 = null;
      boolean callableReleased = false;
      try {
        while (true) {
          EventSet set = vm.eventQueue().remove(30000);
          if (set == null) {
            // safety: never leave a thread suspended
            if (heldCallable != null) { heldCallable.resume(); }
            if (heldVolume2 != null) { heldVolume2.resume(); }
            trace.append(" timeout-release");
            return;
          }
          for (Event ev : set) {
            if (!(ev instanceof BreakpointEvent)) {
              continue;
            }
            BreakpointEvent b = (BreakpointEvent) ev;
            ThreadReference th = b.thread();
            int line = b.location().lineNumber();
            trace.append(" ").append(th.name()).append("@").append(line);
            if (line == 409) {
              hits409++;
              if (hits409 == 2 && heldVolume2 == null && !callableReleased) {
                heldVolume2 = th;              // hold volume 2 inside window
                if (heldCallable != null) {
                  callableReleased = true;
                  heldCallable.resume();       // let callable write 510/513
                  heldCallable = null;
                }
              } else {
                th.resume();
              }
            } else if (line == 510) {
              if (heldVolume2 == null && !callableReleased) {
                heldCallable = th;             // hold callable before writes
              } else {
                callableReleased = true;
                th.resume();
              }
            } else if (line == 518) {
              th.resume();
              if (heldVolume2 != null) {
                realized = true;               // 510/513 done inside window
                heldVolume2.resume();
                heldVolume2 = null;
              }
            } else {
              th.resume();
            }
          }
        }
      } catch (InterruptedException e) {
        // stopping
      } catch (Exception e) {
        trace.append(" error=").append(e);
      }
    }

    void stop() {
      if (vm != null) {
        try {
          vm.dispose();
        } catch (Exception e) {
          // ignore
        }
      }
      if (loop != null) {
        loop.interrupt();
      }
    }
  }
}
