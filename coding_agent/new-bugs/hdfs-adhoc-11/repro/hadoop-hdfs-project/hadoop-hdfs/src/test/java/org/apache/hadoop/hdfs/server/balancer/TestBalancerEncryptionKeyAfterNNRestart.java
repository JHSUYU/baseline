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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.net.URI;
import java.util.Collection;
import java.util.List;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.CommonConfigurationKeysPublic;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.hdfs.DFSConfigKeys;
import org.apache.hadoop.hdfs.DFSUtil;
import org.apache.hadoop.hdfs.HdfsConfiguration;
import org.apache.hadoop.hdfs.MiniDFSCluster;
import org.apache.hadoop.hdfs.NameNodeProxies;
import org.apache.hadoop.hdfs.protocol.ClientProtocol;
import org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException;
import org.apache.hadoop.hdfs.security.token.block.DataEncryptionKey;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.slf4j.LoggerFactory;

/**
 * A Balancer run (one doBalance() round, which may consist of many
 * iterations and last for hours) caches the DataEncryptionKey it derived
 * from the NameNode's block key for the whole token lifetime. Block keys of
 * the NameNode are not persisted, so after a NameNode restart every DataNode
 * that registers afterwards (a newly added DataNode -- the typical reason to
 * run the balancer -- or a restarted one) only knows the new block keys and
 * rejects the Balancer's still-unexpired encryption key in
 * BlockTokenSecretManager#retrieveDataEncryptionKey. The Balancer never
 * refreshes the key, so all moves to that DataNode fail.
 */
public class TestBalancerEncryptionKeyAfterNNRestart {

  private static final long CAPACITY = 1000L;
  private static final String RACK = "/rack0";

  @Test
  @Timeout(value = 180)
  public void testBalancerMoveFailsAfterNameNodeRestart() throws Exception {
    Configuration conf = new HdfsConfiguration();
    TestBalancer.initConf(conf);
    conf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, true);
    conf.setBoolean(DFSConfigKeys.DFS_BLOCK_ACCESS_TOKEN_ENABLE_KEY, true);
    // Idle IPC connections are dropped quickly so that the balancer does not
    // reuse a connection to the NameNode instance that was restarted (in a
    // real deployment a NN restart takes much longer than the default 10s).
    conf.setInt(
        CommonConfigurationKeysPublic.IPC_CLIENT_CONNECTION_MAXIDLETIME_KEY,
        500);

    LogCapturer dnLogs = LogCapturer.captureLogs(
        LoggerFactory.getLogger(DataNode.class));
    MiniDFSCluster cluster = new MiniDFSCluster.Builder(conf)
        .numDataNodes(1).racks(new String[] {RACK})
        .simulatedCapacities(new long[] {CAPACITY}).build();
    List<NameNodeConnector> connectors = null;
    try {
      cluster.waitActive();
      // 1. Fill DN0 to 60% with single-replica blocks.
      final long used = CAPACITY * 6 / 10;
      TestBalancer.createFile(cluster, new Path("/data"), used, (short) 1, 0);
      ClientProtocol client = NameNodeProxies.createProxy(conf,
          cluster.getFileSystem(0).getUri(), ClientProtocol.class).getProxy();

      // 2. Add an empty DN1 and start a balancer round.
      cluster.startDataNodes(conf, 1, true, null, new String[] {RACK}, null,
          new long[] {CAPACITY});
      cluster.waitActive();
      TestBalancer.waitForHeartBeat(used, 2 * CAPACITY, client, cluster);

      Collection<URI> namenodes = DFSUtil.getInternalNsRpcUris(conf);
      connectors = NameNodeConnector.newNameNodeConnectors(namenodes,
          Balancer.class.getSimpleName(), Balancer.BALANCER_ID_PATH, conf,
          BalancerParameters.DEFAULT.getMaxIdleIteration());
      NameNodeConnector nnc = connectors.get(0);
      Balancer balancer = new Balancer(nnc, BalancerParameters.DEFAULT, conf);

      Balancer.Result r1 = balancer.runOneIteration();
      System.out.println("Iteration 1: " + r1.getExitStatus() + " moved "
          + r1.getBytesAlreadyMoved() + " bytes / " + r1.getBlocksMoved()
          + " blocks");
      assertTrue(r1.getBlocksMoved() > 0,
          "first iteration should move blocks (and create the cached key)");
      DataEncryptionKey keyBefore = nnc.getKeyManager().newDataEncryptionKey();
      System.out.println("Balancer encryption key id before NN restart: "
          + keyBefore.keyId);

      // 3. The NameNode restarts (crash / maintenance) while the balancer
      //    round is still in progress. It generates fresh block keys.
      cluster.restartNameNode(true);
      cluster.waitActive();
      Thread.sleep(2000);

      // 4. A new DataNode is added (or a DataNode restarts). It registers
      //    with the restarted NN and only receives the new block keys.
      cluster.startDataNodes(conf, 1, true, null, new String[] {RACK}, null,
          new long[] {CAPACITY});
      cluster.waitActive();
      TestBalancer.waitForHeartBeat(used, 3 * CAPACITY, client, cluster);
      DataNode newDn = cluster.getDataNodes().get(2);

      // 5. The balancer round continues with its next iteration. Its
      //    encryption key is not expired, so it keeps using it.
      DataEncryptionKey keyAfter = nnc.getKeyManager().newDataEncryptionKey();
      System.out.println("Balancer encryption key id after NN restart: "
          + keyAfter.keyId + ", expiry " + keyAfter.expiryDate);
      assertEquals(keyBefore.keyId, keyAfter.keyId);

      // Exactly like Balancer#doBalance: same NameNodeConnector (and thus the
      // same KeyManager), new Balancer object per iteration.
      balancer.resetData(conf);
      balancer = new Balancer(nnc, BalancerParameters.DEFAULT, conf);
      Balancer.Result r2 = balancer.runOneIteration();
      System.out.println("Iteration 2: " + r2.getExitStatus() + " moved "
          + r2.getBytesAlreadyMoved() + " bytes / " + r2.getBlocksMoved()
          + " blocks");

      String logs = dnLogs.getOutput();
      // The frame of the check: the "throw new InvalidEncryptionKeyException"
      // statement that starts at BlockTokenSecretManager.java:559 spans lines
      // 559-561; javac attributes the constructor call to its last line.
      String frame = "BlockTokenSecretManager.retrieveDataEncryptionKey("
          + "BlockTokenSecretManager.java:";
      int idx = logs.indexOf(frame);
      assertTrue(idx >= 0,
          "expected the new DataNode to reject the balancer's encryption key");
      int causeIdx = logs.lastIndexOf("Caused by: "
          + InvalidEncryptionKeyException.class.getName(), idx);
      System.out.println("==== new DataNode rejects the balancer's key ====\n"
          + logs.substring(causeIdx, logs.indexOf('\n',
              logs.indexOf('\n', idx) + 1)));
      assertTrue(logs.contains("required block key (keyID=" + keyBefore.keyId
          + ") doesn't exist"));
      assertTrue(keyAfter.expiryDate > System.currentTimeMillis()
          + 60 * 60 * 1000L, "the rejected key is valid for hours");
      // Nothing could be moved to the new DataNode (the counters of the
      // result are cumulative over the iterations of the round).
      assertEquals(r1.getBlocksMoved(), r2.getBlocksMoved());
      assertEquals(0L, newDn.getFSDataset()
          .getBlockReports(cluster.getNamesystem().getBlockPoolId())
          .values().iterator().next().getNumberOfBlocks());
    } finally {
      dnLogs.stopCapturing();
      if (connectors != null) {
        for (NameNodeConnector c : connectors) {
          c.close();
        }
      }
      cluster.shutdown();
    }
  }
}
