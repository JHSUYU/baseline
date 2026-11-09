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
package org.apache.hadoop.hdfs.server.balancer;

import static org.junit.Assert.assertFalse;

import java.net.URI;
import java.util.Collection;

import org.apache.commons.logging.Log;
import org.apache.commons.logging.LogFactory;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.hdfs.DFSConfigKeys;
import org.apache.hadoop.hdfs.DFSUtil;
import org.apache.hadoop.hdfs.HdfsConfiguration;
import org.apache.hadoop.hdfs.MiniDFSCluster;
import org.apache.hadoop.hdfs.NameNodeProxies;
import org.apache.hadoop.hdfs.protocol.ClientProtocol;
import org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.junit.Test;

/**
 * A long-running Balancer against a cluster with encrypted data transfer.
 *
 * The Balancer's NameNodeConnector generates one DataEncryptionKey (from the
 * block key that is current at the first block move) and caches it for the
 * whole life of the Balancer, never checking its expiry date. The NameNode
 * keeps rolling block keys every keyUpdateInterval and the DataNodes drop the
 * block keys once they expire. When the balancer is still moving blocks after
 * that point, every replaceBlock request it sends is rejected by the DataNode
 * in BlockTokenSecretManager#retrieveDataEncryptionKey with
 * InvalidEncryptionKeyException, and the Balancer can make no more progress.
 *
 * Real deployments: keyUpdateInterval=10h, tokenLifetime=10h by default, and a
 * balancer throttled by dfs.datanode.balance.bandwidthPerSec routinely runs
 * for days on a large cluster. This test compresses those time scales: key
 * interval/lifetime 2s and balancer bandwidth 10 bytes/s.
 */
public class TestBalancerWithExpiredEncryptionKey {
  private static final Log LOG =
      LogFactory.getLog(TestBalancerWithExpiredEncryptionKey.class);

  private static final long CAPACITY = 2000L;
  private static final String RACK0 = "/rack0";

  @Test(timeout = 300000)
  public void testLongRunningBalancerWithEncryptedTransfer() throws Exception {
    Configuration conf = new HdfsConfiguration();
    TestBalancer.initConf(conf);
    conf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, true);
    conf.setBoolean(DFSConfigKeys.DFS_BLOCK_ACCESS_TOKEN_ENABLE_KEY, true);
    // Slow balancer traffic so that one balancer run outlives a block key.
    conf.setLong(DFSConfigKeys.DFS_DATANODE_BALANCE_BANDWIDTHPERSEC_KEY, 10L);

    MiniDFSCluster cluster = new MiniDFSCluster.Builder(conf)
        .numDataNodes(1)
        .racks(new String[] {RACK0})
        .simulatedCapacities(new long[] {CAPACITY})
        .build();
    LogCapturer dnLogs = LogCapturer.captureLogs(DataNode.LOG);
    try {
      cluster.waitActive();
      ClientProtocol client = NameNodeProxies.createProxy(conf,
          cluster.getFileSystem(0).getUri(), ClientProtocol.class).getProxy();

      // fill the only datanode to 60%
      long totalUsedSpace = CAPACITY * 6 / 10;
      TestBalancer.createFile(cluster, new Path("/tmp.txt"), totalUsedSpace,
          (short) 1, 0);
      // add an empty datanode
      cluster.startDataNodes(conf, 1, true, null, new String[] {RACK0},
          new long[] {CAPACITY});
      long totalCapacity = 2 * CAPACITY;
      TestBalancer.waitForHeartBeat(totalUsedSpace, totalCapacity, client,
          cluster);

      // The NN rolls block keys every 2s and the keys live 2s after retiring
      // (the same knobs TestEncryptedTransfer#testLongLivedClient uses).
      BlockTokenSecretManager btsm = cluster.getNamesystem().getBlockManager()
          .getBlockTokenSecretManager();
      btsm.setKeyUpdateIntervalForTesting(2 * 1000);
      btsm.setTokenLifetime(2 * 1000);

      Collection<URI> namenodes = DFSUtil.getNsServiceRpcUris(conf);
      final int r = Balancer.run(namenodes, Balancer.Parameters.DEFALUT, conf);
      LOG.info("Balancer returned " + r);

      String out = dnLogs.getOutput();
      int idx = out.indexOf("InvalidEncryptionKeyException");
      if (idx >= 0) {
        int start = out.lastIndexOf("DataXceiver error processing", idx);
        if (start < 0) {
          start = Math.max(0, idx - 2000);
        }
        String trace = out.substring(start, Math.min(out.length(), idx + 6000));
        LOG.error("DataNode rejected the balancer's encryption key:\n" + trace);
        assertFalse("Balancer's cached DataEncryptionKey was rejected by the "
            + "DataNode (balancer returned " + r + "):\n" + trace, true);
      }
    } finally {
      dnLogs.stopCapturing();
      cluster.shutdown();
    }
  }
}
