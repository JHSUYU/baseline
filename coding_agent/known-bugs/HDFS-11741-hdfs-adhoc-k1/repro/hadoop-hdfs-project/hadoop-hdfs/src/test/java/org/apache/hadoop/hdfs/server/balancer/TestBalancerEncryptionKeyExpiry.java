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

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import java.net.URI;
import java.util.Collection;
import java.util.List;

import com.google.common.base.Supplier;
import org.apache.commons.logging.Log;
import org.apache.commons.logging.LogFactory;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.hdfs.DFSConfigKeys;
import org.apache.hadoop.hdfs.DFSTestUtil;
import org.apache.hadoop.hdfs.DFSUtil;
import org.apache.hadoop.hdfs.HdfsConfiguration;
import org.apache.hadoop.hdfs.MiniDFSCluster;
import org.apache.hadoop.hdfs.protocol.ClientProtocol;
import org.apache.hadoop.hdfs.NameNodeProxies;
import org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager;
import org.apache.hadoop.hdfs.security.token.block.DataEncryptionKey;
import org.apache.hadoop.hdfs.server.balancer.Balancer.Result;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.io.IOUtils;
import org.junit.After;
import org.junit.Test;

/**
 * A long-running balancer with encrypted data transfer caches the
 * DataEncryptionKey it gets from its KeyManager forever. Once the block key
 * that this DataEncryptionKey was derived from is rolled over and expires,
 * the datanodes drop that block key and every further block move of the
 * still-running balancer is rejected by
 * BlockTokenSecretManager#retrieveDataEncryptionKey with
 * InvalidEncryptionKeyException.
 */
public class TestBalancerEncryptionKeyExpiry {
  private static final Log LOG =
      LogFactory.getLog(TestBalancerEncryptionKeyExpiry.class);

  static {
    TestBalancer.initTestSetup();
  }

  private MiniDFSCluster cluster;

  @After
  public void shutdown() {
    if (cluster != null) {
      cluster.shutdown();
      cluster = null;
    }
  }

  @Test(timeout = 180000)
  public void testLongRunningEncryptedBalancer() throws Exception {
    final Configuration conf = new HdfsConfiguration();
    conf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, true);
    conf.setBoolean(DFSConfigKeys.DFS_BLOCK_ACCESS_TOKEN_ENABLE_KEY, true);
    TestBalancer.initConf(conf);
    // Move at most one block per datanode per iteration so that balancing
    // needs several iterations, i.e. the balancer is long running.
    conf.setLong(DFSConfigKeys.DFS_BALANCER_MAX_SIZE_TO_MOVE_KEY,
        TestBalancer.DEFAULT_BLOCK_SIZE);

    final long capacity = 10000L;
    cluster = new MiniDFSCluster.Builder(conf).numDataNodes(0).build();
    cluster.getConfiguration(0).setInt(DFSConfigKeys.DFS_REPLICATION_KEY, 1);
    conf.setInt(DFSConfigKeys.DFS_REPLICATION_KEY, 1);
    cluster.startDataNodes(conf, 1, true, null, new String[] {"/rack0"},
        null, new long[] {capacity}, false);
    cluster.waitActive();

    // Short block key rolling interval and token lifetime (same knobs as in
    // TestEncryptedTransfer#testLongLivedClient), so that block keys roll over
    // and expire within seconds instead of the default tens of minutes.
    BlockTokenSecretManager nnBtsm = cluster.getNamesystem()
        .getBlockManager().getBlockTokenSecretManager();
    nnBtsm.setKeyUpdateIntervalForTesting(2 * 1000);
    nnBtsm.setTokenLifetime(2 * 1000);

    // 30% full, single replica.
    final long totalUsedSpace = capacity * 3 / 10;
    TestBalancer.createFile(cluster, new Path("/tmp.txt"), totalUsedSpace,
        (short) 1, 0);

    // Add an empty datanode; the cluster is now unbalanced.
    cluster.startDataNodes(conf, 1, true, null, new String[] {"/rack0"},
        null, new long[] {capacity});
    cluster.waitActive();
    final long totalCapacity = 2 * capacity;
    ClientProtocol client = NameNodeProxies.createProxy(conf,
        cluster.getFileSystem(0).getUri(), ClientProtocol.class).getProxy();
    TestBalancer.waitForHeartBeat(totalUsedSpace, totalCapacity, client,
        cluster);

    // Run the balancer exactly like Balancer#run does: one NameNodeConnector
    // (and hence one KeyManager) for the whole run, a new Balancer per
    // iteration.
    Collection<URI> namenodes = DFSUtil.getInternalNsRpcUris(conf);
    BalancerParameters p = BalancerParameters.DEFAULT;
    List<NameNodeConnector> connectors =
        NameNodeConnector.newNameNodeConnectors(namenodes,
            Balancer.class.getSimpleName(), Balancer.BALANCER_ID_PATH, conf,
            p.getMaxIdleIteration());
    try {
      assertEquals(1, connectors.size());
      final NameNodeConnector nnc = connectors.get(0);

      // Iteration 0: moves a block, the KeyManager creates and caches the
      // data encryption key.
      Balancer b = new Balancer(nnc, p, conf);
      Result r = b.runOneIteration();
      r.print(0, System.out);
      b.resetData(conf);
      assertEquals(ExitStatus.IN_PROGRESS, r.exitStatus);
      assertTrue(nnc.getBytesMoved().get() > 0);

      final DataEncryptionKey dek =
          nnc.getKeyManager().newDataEncryptionKey();
      LOG.info("Balancer is using data encryption key with keyId="
          + dek.keyId);

      // The balancer keeps running. Meanwhile the NN rolls its block keys,
      // and the block key behind the balancer's encryption key expires and
      // is dropped by the datanodes on their next key update.
      for (final DataNode dn : cluster.getDataNodes()) {
        GenericTestUtils.waitFor(new Supplier<Boolean>() {
          @Override
          public Boolean get() {
            return !dn.getBlockPoolTokenSecretManager()
                .get(dek.blockPoolId).hasKey(dek.keyId);
          }
        }, 100, 60 * 1000);
      }
      LOG.info("Block key " + dek.keyId + " expired on all datanodes.");

      // Next iterations of the same balancer run.
      long movedBefore = nnc.getBytesMoved().get();
      int exitStatus = ExitStatus.IN_PROGRESS.getExitCode();
      for (int iteration = 1; iteration < 4; iteration++) {
        b = new Balancer(nnc, p, conf);
        r = b.runOneIteration();
        r.print(iteration, System.out);
        b.resetData(conf);
        exitStatus = r.exitStatus.getExitCode();
        if (r.exitStatus != ExitStatus.IN_PROGRESS) {
          break;
        }
        Thread.sleep(2000);
      }
      long movedAfter = nnc.getBytesMoved().get();
      LOG.info("bytes moved before key expiry=" + movedBefore
          + ", after=" + movedAfter + ", exit status=" + exitStatus);
      // A correct balancer keeps moving blocks after a block key rollover.
      assertTrue("Balancer could not move any block after its data "
          + "encryption key's block key expired (see "
          + "InvalidEncryptionKeyException in the datanode logs)",
          movedAfter > movedBefore);
    } finally {
      for (NameNodeConnector nnc : connectors) {
        IOUtils.cleanup(LOG, nnc);
      }
    }
  }
}
