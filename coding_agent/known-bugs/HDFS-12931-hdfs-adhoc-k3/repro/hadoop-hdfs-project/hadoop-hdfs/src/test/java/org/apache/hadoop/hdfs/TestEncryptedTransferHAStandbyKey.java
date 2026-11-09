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

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.util.List;

import com.google.common.base.Supplier;
import org.apache.commons.logging.Log;
import org.apache.commons.logging.LogFactory;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.hdfs.protocol.ExtendedBlock;
import org.apache.hadoop.hdfs.protocol.LocatedBlock;
import org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager;
import org.apache.hadoop.hdfs.security.token.block.DataEncryptionKey;
import org.apache.hadoop.hdfs.server.blockmanagement.DatanodeDescriptor;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.hdfs.server.datanode.DataNodeTestUtils;
import org.apache.hadoop.hdfs.server.namenode.ha.HATestUtil;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.junit.After;
import org.junit.Test;

/**
 * Encrypted data transfer in an HA cluster: a DataNode builds the data
 * encryption key for DN-to-DN transfers from its "currentKey", which is the
 * current block key of whichever NameNode (active OR standby) sent it keys
 * last. If that NameNode is down and the target DataNode (re)started while it
 * was down, the target DN never received that NameNode's block keys and
 * rejects the handshake in
 * BlockTokenSecretManager#retrieveDataEncryptionKey.
 */
public class TestEncryptedTransferHAStandbyKey {
  private static final Log LOG =
      LogFactory.getLog(TestEncryptedTransferHAStandbyKey.class);
  private static final Path PATH = new Path("/file-to-replicate");

  private MiniDFSCluster cluster;
  private DistributedFileSystem fs;

  @After
  public void teardown() throws Exception {
    if (fs != null) {
      fs.close();
    }
    if (cluster != null) {
      cluster.shutdown();
    }
  }

  @Test(timeout = 300000)
  public void testReplicationFailsAfterStandbyCrashAndDataNodeRestart()
      throws Exception {
    Configuration conf = new HdfsConfiguration();
    conf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, true);
    conf.setBoolean(DFSConfigKeys.DFS_BLOCK_ACCESS_TOKEN_ENABLE_KEY, true);
    conf.setInt(DFSConfigKeys.DFS_REPLICATION_KEY, 1);
    conf.setLong(DFSConfigKeys.DFS_HEARTBEAT_INTERVAL_KEY, 1);
    conf.setInt(DFSConfigKeys.DFS_NAMENODE_REDUNDANCY_INTERVAL_SECONDS_KEY, 1);

    cluster = new MiniDFSCluster.Builder(conf)
        .nnTopology(MiniDFSNNTopology.simpleHATopology())
        .numDataNodes(2)
        .build();
    cluster.waitActive();
    cluster.transitionToActive(0);
    fs = HATestUtil.configureFailoverFs(cluster, conf);

    // 1. Write a file with a single replica.
    DFSTestUtil.createFile(fs, PATH, 1024, (short) 1, 0L);
    LocatedBlock lb = DFSTestUtil.getAllBlocks(fs, PATH).get(0);
    ExtendedBlock block = lb.getBlock();
    final String bpid = block.getBlockPoolId();
    String srcXfer = lb.getLocations()[0].getXferAddr();
    int srcIdx = -1;
    List<DataNode> dns = cluster.getDataNodes();
    for (int i = 0; i < dns.size(); i++) {
      if (dns.get(i).getDatanodeId().getXferAddr().equals(srcXfer)) {
        srcIdx = i;
      }
    }
    assertTrue(srcIdx >= 0);
    final int dstIdx = 1 - srcIdx;
    DataNode srcDn = dns.get(srcIdx);
    LOG.info("Source DN " + srcDn + ", target DN " + dns.get(dstIdx));

    // 2. The standby NN (nn1) is restarted (e.g. routine maintenance). The
    //    DataNodes re-register with it and take its block keys; nn1's current
    //    key becomes their currentKey.
    cluster.restartNameNode(1);
    cluster.waitActive();

    BlockTokenSecretManager nn0Btsm = cluster.getNamesystem(0)
        .getBlockManager().getBlockTokenSecretManager();
    BlockTokenSecretManager nn1Btsm = cluster.getNamesystem(1)
        .getBlockManager().getBlockTokenSecretManager();
    DataEncryptionKey srcKey = srcDn.getBlockPoolTokenSecretManager()
        .generateDataEncryptionKey(bpid);
    LOG.info("Source DN generates data encryption keys with block key id "
        + srcKey.keyId + "; nn0 has it: " + nn0Btsm.hasKey(srcKey.keyId)
        + ", nn1 has it: " + nn1Btsm.hasKey(srcKey.keyId));
    assertTrue(nn1Btsm.hasKey(srcKey.keyId));
    assertFalse(nn0Btsm.hasKey(srcKey.keyId));

    // 3. The standby NN crashes (stays down).
    cluster.shutdownNameNode(1);

    // 4. The target DN restarts while nn1 is down: it registers only with the
    //    active nn0, so it only gets nn0's block keys.
    MiniDFSCluster.DataNodeProperties dstProps = cluster.stopDataNode(dstIdx);
    cluster.restartDataNode(dstProps, true);
    final DataNode newDst = cluster.getDataNodes().get(
        cluster.getDataNodes().size() - 1);
    GenericTestUtils.waitFor(new Supplier<Boolean>() {
      @Override
      public Boolean get() {
        return newDst.getBlockPoolTokenSecretManager()
            .isBlockPoolRegistered(bpid);
      }
    }, 100, 60000);
    final DatanodeDescriptor dstDesc = cluster.getNamesystem(0)
        .getBlockManager().getDatanodeManager()
        .getDatanode(newDst.getDatanodeId());
    final long restartTime = org.apache.hadoop.util.Time.monotonicNow();
    GenericTestUtils.waitFor(new Supplier<Boolean>() {
      @Override
      public Boolean get() {
        return dstDesc != null && dstDesc.isAlive()
            && dstDesc.getLastUpdateMonotonic() > restartTime;
      }
    }, 100, 60000);
    assertFalse(newDst.getBlockPoolTokenSecretManager().get(bpid)
        .hasKey(srcKey.keyId));

    // 5. Raise replication: active nn0 asks the source DN to copy the block
    //    to the restarted DN.
    LogCapturer logs = LogCapturer.captureLogs(DataNode.LOG);
    try {
      fs.setReplication(PATH, (short) 2);
      GenericTestUtils.waitFor(new Supplier<Boolean>() {
        @Override
        public Boolean get() {
          return logs.getOutput().contains("InvalidEncryptionKeyException");
        }
      }, 100, 60000);
      // wait some more: replication keeps failing.
      Thread.sleep(10000);
    } finally {
      logs.stopCapturing();
    }
    String out = logs.getOutput();
    System.out.println("==== DataNode logs ====\n" + out);
    // The check is the multi-line "throw new InvalidEncryptionKeyException("
    // statement starting at BlockTokenSecretManager.java:490; javac attributes
    // the constructor call to the statement's last line (492).
    GenericTestUtils.assertMatches(out,
        "InvalidEncryptionKeyException: Can't re-compute encryption key for "
            + "nonce, since the required block key \\(keyID=" + srcKey.keyId
            + "\\) doesn't exist");
    GenericTestUtils.assertMatches(out,
        "at org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager"
            + ".retrieveDataEncryptionKey\\(BlockTokenSecretManager.java:49[0-2]"
            + "\\)");
    assertEquals("Block still has only one replica", 1,
        DFSTestUtil.getAllBlocks(fs, PATH).get(0).getLocations().length);
  }
}
