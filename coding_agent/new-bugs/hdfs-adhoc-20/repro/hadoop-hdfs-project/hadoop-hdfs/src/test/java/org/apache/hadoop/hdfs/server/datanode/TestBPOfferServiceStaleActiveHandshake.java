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
package org.apache.hadoop.hdfs.server.datanode;

import static org.junit.jupiter.api.Assertions.fail;

import java.net.InetSocketAddress;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.permission.FsPermission;
import org.apache.hadoop.hdfs.DFSConfigKeys;
import org.apache.hadoop.hdfs.HdfsConfiguration;
import org.apache.hadoop.hdfs.MiniDFSCluster;
import org.apache.hadoop.hdfs.MiniDFSNNTopology;
import org.apache.hadoop.hdfs.client.HdfsClientConfigKeys;
import org.apache.hadoop.hdfs.server.namenode.NameNode;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.util.ExitUtil;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.junit.jupiter.api.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Reproduces a failure of the ad hoc check
 * {@code assert txid >= lastActiveClaimTxId} in
 * {@link BPOfferService#updateActorStatesFromHeartbeat}.
 *
 * The handshake path ({@link BPOfferService#verifyAndSetNamespaceInfo})
 * acknowledges an NN as ACTIVE without comparing its txid against the most
 * recent active claim. A stale active NN (split-brain: it lost leadership but
 * still believes it is active) that handshakes while the DN knows no active NN
 * is therefore accepted, and its first heartbeat (with an older txid) trips
 * the assertion and kills the BPServiceActor thread.
 */
public class TestBPOfferServiceStaleActiveHandshake {
  private static final Logger LOG =
      LoggerFactory.getLogger(TestBPOfferServiceStaleActiveHandshake.class);
  private static final String NS = "minidfs-ns";

  private static void bumpTxid(NameNode nn, String prefix, int n)
      throws Exception {
    for (int i = 0; i < n; i++) {
      nn.getRpcServer().mkdirs(prefix + i, FsPermission.getDefault(), true);
    }
  }

  private static long txid(NameNode nn) {
    return nn.getFSImage().getCorrectLastAppliedOrWrittenTxId();
  }

  @Test
  public void testStaleActiveAcceptedDuringHandshake() throws Exception {
    Configuration conf = new HdfsConfiguration();
    conf.set(HdfsClientConfigKeys.DFS_CLIENT_DATANODE_RESTART_TIMEOUT_KEY, "15");
    conf.setLong(DFSConfigKeys.DFS_HEARTBEAT_INTERVAL_KEY, 1L);
    LogCapturer logs = LogCapturer.captureLogs(BPServiceActor.LOG);
    MiniDFSCluster cluster = null;
    try {
      cluster = new MiniDFSCluster.Builder(conf)
          .nnTopology(MiniDFSNNTopology.simpleHATopology())
          .numDataNodes(0)
          .build();
      cluster.waitActive();
      NameNode nn0 = cluster.getNameNode(0);   // "nn1" in the nameservice
      NameNode nn1 = cluster.getNameNode(1);   // "nn2" in the nameservice

      // 1. nn0 is the active NN and writes some edits.
      cluster.transitionToActive(0);
      bumpTxid(nn0, "/a", 3);

      // 2. Split-brain: nn1 is elected active (e.g. nn0 was paused / lost its
      //    ZK session) while nn0 has not yet noticed and still reports ACTIVE.
      //    nn1 catches up all edits and writes more, so its txid is higher.
      cluster.transitionToActive(1);
      bumpTxid(nn1, "/b", 5);
      LOG.info("txid nn0 (stale active) = {}, nn1 (new active) = {}",
          txid(nn0), txid(nn1));

      // 3. A DN configured only with nn1 ("nn2") starts and learns that nn1
      //    is active at the higher txid.
      Configuration dnConf = new HdfsConfiguration(conf);
      dnConf.set(DFSConfigKeys.DFS_HA_NAMENODES_KEY_PREFIX + "." + NS, "nn2");
      cluster.startDataNodes(dnConf, 1, true, null, null, null, null);
      cluster.waitActive(1);
      final DataNode dn = cluster.getDataNodes().get(0);
      final BPOfferService bpos = dn.getAllBpOs().get(0);
      final InetSocketAddress nn1Addr = nn1.getServiceRpcAddress();
      GenericTestUtils.waitFor(() -> bpos.getBPServiceActors().size() == 1
          && bpos.getActiveNN() != null, 100, 30000);
      DataNodeTestUtils.triggerHeartbeat(dn);
      DataNodeTestUtils.triggerHeartbeat(dn);
      LOG.info("DN acknowledged {} as active", nn1Addr);

      // 4. nn1 steps down to standby (e.g. its ZKFC loses the ZK session);
      //    the DN learns it via heartbeat and now knows no active NN.
      cluster.transitionToStandby(1);
      DataNodeTestUtils.triggerHeartbeat(dn);
      GenericTestUtils.waitFor(() -> bpos.getActiveNN() == null, 100, 30000);

      // 5. The operator adds the other NN ("nn1") to the DN configuration and
      //    runs -refreshNamenodes. The new actor handshakes with nn0, which
      //    still claims ACTIVE (with its old txid). The handshake accepts it
      //    without a txid check; the next heartbeat hits the assertion.
      Configuration bothConf = new HdfsConfiguration(conf);
      bothConf.set(DFSConfigKeys.DFS_HA_NAMENODES_KEY_PREFIX + "." + NS,
          "nn1,nn2");
      dn.refreshNamenodes(bothConf);

      try {
        GenericTestUtils.waitFor(
            () -> logs.getOutput().contains("Unexpected exception in block pool"),
            100, 30000);
      } catch (java.util.concurrent.TimeoutException te) {
        LOG.info("No actor failure observed");
        return;
      }
      String out = logs.getOutput();
      int idx = out.indexOf("Unexpected exception in block pool");
      String trace = out.substring(idx, Math.min(out.length(), idx + 3000));
      LOG.error("BPServiceActor died:\n{}", trace);
      fail("BPServiceActor for the stale active NN died with an assertion "
          + "failure in BPOfferService.updateActorStatesFromHeartbeat:\n"
          + trace);
    } finally {
      logs.stopCapturing();
      if (cluster != null) {
        try {
          cluster.shutdown();
        } catch (ExitUtil.ExitException e) {
          // The stale active NN cannot finalize its (already recovered) edit
          // log segment on shutdown; that is the fencing, not the bug.
          LOG.info("Ignoring exit of stale active NN during shutdown", e);
          ExitUtil.resetFirstExitException();
        }
      }
    }
  }
}
