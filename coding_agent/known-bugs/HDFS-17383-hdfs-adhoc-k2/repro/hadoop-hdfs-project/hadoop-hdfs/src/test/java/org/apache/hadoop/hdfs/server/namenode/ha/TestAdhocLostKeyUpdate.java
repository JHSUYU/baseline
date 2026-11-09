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
package org.apache.hadoop.hdfs.server.namenode.ha;

import static org.junit.Assert.fail;

import java.io.IOException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.FileSystem;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.hdfs.DFSConfigKeys;
import org.apache.hadoop.hdfs.DFSTestUtil;
import org.apache.hadoop.hdfs.HdfsConfiguration;
import org.apache.hadoop.hdfs.MiniDFSCluster;
import org.apache.hadoop.hdfs.MiniDFSNNTopology;
import org.apache.hadoop.hdfs.protocol.DatanodeInfo;
import org.apache.hadoop.hdfs.protocol.ExtendedBlock;
import org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.hdfs.server.datanode.InternalDataNodeTestUtils;
import org.apache.hadoop.hdfs.server.namenode.NameNode;
import org.apache.hadoop.hdfs.server.protocol.DatanodeCommand;
import org.apache.hadoop.hdfs.server.protocol.DatanodeProtocol;
import org.apache.hadoop.hdfs.server.protocol.HeartbeatResponse;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.junit.Test;
import org.mockito.Mockito;
import org.mockito.invocation.InvocationOnMock;
import org.mockito.stubbing.Answer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.event.Level;

/**
 * Same HA workload as {@link TestAdhocWorkload2} (block tokens enabled, write a
 * file with one replica, raise replication so that a DN-to-DN copy is
 * scheduled), but the heartbeat responses that carry a KeyUpdateCommand to the
 * replication target DataNode are lost on the network after the NameNode has
 * produced them.
 *
 * The NameNode clears DatanodeDescriptor#needKeyUpdate as soon as it puts the
 * KeyUpdateCommand into a heartbeat response, without any acknowledgement. A
 * lost response therefore means the DataNode never learns the rolled keys,
 * although it keeps heart-beating successfully. After two key rolls the
 * current block key of the NameNodes is unknown to that DataNode and it
 * rejects valid block tokens with InvalidToken at
 * BlockTokenSecretManager.retrievePassword (key == null).
 */
public class TestAdhocLostKeyUpdate {
  private static final Logger LOG =
      LoggerFactory.getLogger(TestAdhocLostKeyUpdate.class);

  private static final Path FILE = new Path("/adhoc-lost-key-update");
  private static final long FILE_LEN = 4096;

  private static int currentKeyId(MiniDFSCluster cluster, int nn) {
    return cluster.getNamesystem(nn).getBlockManager().getBlockKeys()
        .getCurrentKey().getKeyId();
  }

  /** Lose (after the NN processed it) every heartbeat response carrying a
   *  KeyUpdateCommand while {@code lose} is set. */
  private static void loseKeyUpdateResponses(DataNode dn, NameNode nn,
      final AtomicBoolean lose, final AtomicInteger lost) throws IOException {
    DatanodeProtocolClientSideTranslatorPB spy =
        InternalDataNodeTestUtils.spyOnBposToNN(dn, nn);
    Mockito.doAnswer(new Answer<HeartbeatResponse>() {
      @Override
      public HeartbeatResponse answer(InvocationOnMock inv) throws Throwable {
        HeartbeatResponse resp = (HeartbeatResponse) inv.callRealMethod();
        if (lose.get() && resp.getCommands() != null) {
          for (DatanodeCommand c : resp.getCommands()) {
            if (c.getAction() == DatanodeProtocol.DNA_ACCESSKEYUPDATE) {
              lost.incrementAndGet();
              LOG.info("Injected fault: heartbeat response with "
                  + "KeyUpdateCommand from {} to {} is lost",
                  nn.getNameNodeAddress(), dn.getDisplayName());
              throw new IOException("Injected: heartbeat response lost");
            }
          }
        }
        return resp;
      }
    }).when(spy).sendHeartbeat(Mockito.any(), Mockito.any(),
        Mockito.anyLong(), Mockito.anyLong(), Mockito.anyInt(),
        Mockito.anyInt(), Mockito.anyInt(), Mockito.any(),
        Mockito.anyBoolean(), Mockito.any(), Mockito.any());
  }

  @Test(timeout = 600000)
  public void run() throws Exception {
    Configuration conf = new HdfsConfiguration();
    conf.setBoolean(DFSConfigKeys.DFS_BLOCK_ACCESS_TOKEN_ENABLE_KEY, true);
    conf.setInt(DFSConfigKeys.DFS_HEARTBEAT_INTERVAL_KEY, 1);
    conf.setInt(DFSConfigKeys.DFS_NAMENODE_REDUNDANCY_INTERVAL_SECONDS_KEY, 1);
    // Roll block keys every minute (the smallest configurable interval).
    conf.setLong(DFSConfigKeys.DFS_BLOCK_ACCESS_KEY_UPDATE_INTERVAL_KEY, 1);
    MiniDFSCluster cluster = new MiniDFSCluster.Builder(conf)
        .nnTopology(MiniDFSNNTopology.simpleHATopology())
        .numDataNodes(2)
        .build();
    try {
      cluster.waitActive();
      cluster.transitionToActive(0);
      cluster.waitActive();

      FileSystem fs = HATestUtil.configureFailoverFs(cluster, conf);
      DFSTestUtil.createFile(fs, FILE, FILE_LEN, (short) 1, 0L);
      DFSTestUtil.waitReplication(fs, FILE, (short) 1);

      // The replication target is the DN that does not hold the replica.
      ExtendedBlock blk = DFSTestUtil.getFirstBlock(fs, FILE);
      DatanodeInfo src = DFSTestUtil.getAllBlocks(fs, FILE).get(0)
          .getLocations()[0];
      DataNode target = null;
      for (DataNode dn : cluster.getDataNodes()) {
        if (!dn.getDatanodeUuid().equals(src.getDatanodeUuid())) {
          target = dn;
        }
      }
      LOG.info("Block {} on {}, replication target {}", blk, src,
          target.getDisplayName());

      // Network fault: heartbeat responses with key updates to the target
      // are lost (from either NameNode).
      AtomicBoolean lose = new AtomicBoolean(true);
      AtomicInteger lost = new AtomicInteger();
      loseKeyUpdateResponses(target, cluster.getNameNode(0), lose, lost);
      loseKeyUpdateResponses(target, cluster.getNameNode(1), lose, lost);

      // Wait for two key rolls on both NameNodes.
      final int k0 = currentKeyId(cluster, 0);
      final int k1 = currentKeyId(cluster, 1);
      final MiniDFSCluster c = cluster;
      GenericTestUtils.waitFor(() -> currentKeyId(c, 0) >= k0 + 2
          && currentKeyId(c, 1) >= k1 + 2, 1000, 300000);
      // Let the rolled keys of the second roll reach the target (and be lost).
      GenericTestUtils.waitFor(() -> lost.get() >= 4, 500, 60000);
      lose.set(false); // the network is fine again
      LOG.info("Lost {} key-update heartbeat responses; NN0 key {} -> {}, "
          + "NN1 key {} -> {}", lost.get(), k0, currentKeyId(cluster, 0),
          k1, currentKeyId(cluster, 1));

      // InvalidToken is logged with its stack trace at TRACE level.
      GenericTestUtils.setLogLevel(DataNode.LOG, Level.TRACE);
      LogCapturer logs = LogCapturer.captureLogs(DataNode.LOG);

      // The workload: raise replication -> DN-to-DN copy to the target.
      fs.setReplication(FILE, (short) 2);
      try {
        GenericTestUtils.waitFor(() -> logs.getOutput().contains(
            "since the required block key"), 500, 30000);
      } catch (Exception e) {
        // no failure observed
      }
      GenericTestUtils.setLogLevel(DataNode.LOG, Level.INFO);
      logs.stopCapturing();
      String out = logs.getOutput();
      if (out.contains("since the required block key")) {
        int i = out.indexOf("InvalidToken");
        fail("Target DataNode rejected a valid block token although it has "
            + "been heart-beating to both NameNodes all the time:\n"
            + out.substring(Math.max(0, i - 2000),
                Math.min(out.length(), i + 4000)));
      }
      DFSTestUtil.waitReplication(fs, FILE, (short) 2);
      fs.close();
    } finally {
      cluster.shutdown();
    }
  }
}
