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

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.FileSystem;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.hdfs.server.common.HdfsServerConstants.StartupOption;
import org.apache.hadoop.hdfs.server.common.Storage;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.hdfs.server.namenode.NameNode;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * A DataNode that is down while the cluster is rolled back keeps its
 * un-finalized upgrade (previous = pre-upgrade state, current = upgraded
 * state). When it comes back during the next upgrade, BlockPoolSliceStorage
 * #doUpgrade silently deletes the old "previous" snapshot and turns the
 * rolled-back upgraded state into the new "previous". A subsequent rollback
 * of the cluster then fails on that DataNode in
 * BlockPoolSliceStorage#doRollback with InconsistentFSStateException.
 */
public class TestDFSRollbackAfterMissedRollback {
  private static final Logger LOG =
      LoggerFactory.getLogger(TestDFSRollbackAfterMissedRollback.class);

  private MiniDFSCluster cluster;

  @AfterEach
  public void tearDown() {
    if (cluster != null) {
      cluster.shutdown();
      cluster = null;
    }
  }

  private MiniDFSCluster build(Configuration conf, int numDns,
      StartupOption nnOpt, StartupOption dnOpt) throws Exception {
    return new MiniDFSCluster.Builder(conf).numDataNodes(numDns)
        .format(false).startupOption(nnOpt).dnStartupOption(dnOpt).build();
  }

  @Test
  public void testRollbackAfterDataNodeMissedPreviousRollback()
      throws Exception {
    Configuration conf = new HdfsConfiguration();
    conf.setInt(DFSConfigKeys.DFS_REPLICATION_KEY, 2);

    // 0. Fresh cluster with two DataNodes; write some data.
    cluster = new MiniDFSCluster.Builder(conf).numDataNodes(2).build();
    cluster.waitActive();
    FileSystem fs = cluster.getFileSystem();
    DFSTestUtil.createFile(fs, new Path("/before"), 1024, (short) 2, 0L);
    String bpid = cluster.getNamesystem().getBlockPoolId();
    long cTime0 = cluster.getNamesystem().getFSImage().getStorage().getCTime();
    cluster.shutdown();

    // 1. Upgrade #1: NN -upgrade (cTime C1), both DNs upgrade their
    //    block pool storage (previous = C0, current = C1).
    Thread.sleep(10);
    cluster = build(conf, 2, StartupOption.UPGRADE, StartupOption.REGULAR);
    cluster.waitActive();
    long cTime1 = cluster.getNamesystem().getFSImage().getStorage().getCTime();
    LOG.info("cTime0 = {}, cTime1 = {}", cTime0, cTime1);
    DFSTestUtil.createFile(cluster.getFileSystem(), new Path("/during1"),
        1024, (short) 2, 0L);
    cluster.shutdown();

    // 2. The admin rolls the cluster back. DN1 is down (crashed) at this
    //    time, so only DN0 is started with -rollback. DN1 keeps
    //    previous = C0, current = C1.
    NameNode.doRollback(conf, false);
    cluster = build(conf, 1, StartupOption.REGULAR, StartupOption.ROLLBACK);
    cluster.waitActive();
    cluster.shutdown();

    // 3. Upgrade #2: NN -upgrade (cTime C2 > C1). DN1 comes back (regular
    //    start). Its current cTime C1 < C2, so it "upgrades": the C0
    //    snapshot is deleted and the rolled-back C1 state becomes previous.
    Thread.sleep(10);
    cluster = build(conf, 2, StartupOption.UPGRADE, StartupOption.REGULAR);
    cluster.waitActive();
    long cTime2 = cluster.getNamesystem().getFSImage().getStorage().getCTime();
    LOG.info("cTime2 = {}", cTime2);
    cluster.shutdown();

    // 4. The admin rolls back upgrade #2: NN goes back to C0 and all DNs are
    //    started with -rollback.
    // BlockPoolSliceStorage logs through Storage.LOG.
    LogCapturer logs = LogCapturer.captureLogs(Storage.LOG);
    try {
      NameNode.doRollback(conf, false);
      cluster = build(conf, 0, StartupOption.REGULAR, StartupOption.ROLLBACK);
      cluster.waitActive();
      cluster.startDataNodes(conf, 2, false, StartupOption.ROLLBACK, null);
      final DataNode dn1 = cluster.getDataNodes().get(1);
      GenericTestUtils.waitFor(() -> logs.getOutput().contains(
          "InconsistentFSStateException"), 100, 60000);
      GenericTestUtils.waitFor(() -> !dn1.isBPServiceAlive(bpid), 100, 60000);
    } finally {
      logs.stopCapturing();
    }
    String out = logs.getOutput();
    System.out.println("==== captured BlockPoolSliceStorage log ====");
    System.out.println(out);
    assertTrue(out.contains("Cannot rollback to a newer state"), out);
    assertTrue(out.contains("InconsistentFSStateException"), out);
    // The multi-line 'throw new InconsistentFSStateException(...)' of the
    // check (lines 621-626) is reported at its last line by javac.
    assertTrue(out.contains("at org.apache.hadoop.hdfs.server.datanode."
        + "BlockPoolSliceStorage.doRollback(BlockPoolSliceStorage.java:"), out);
    assertFalse(cluster.getDataNodes().get(1).isBPServiceAlive(bpid));
  }
}
