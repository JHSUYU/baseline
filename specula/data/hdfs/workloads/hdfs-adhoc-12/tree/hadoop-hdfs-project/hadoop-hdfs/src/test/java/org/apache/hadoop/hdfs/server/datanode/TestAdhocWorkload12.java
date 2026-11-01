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

import java.io.IOException;
import java.net.InetSocketAddress;
import java.util.List;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.FSDataOutputStream;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.fs.StorageType;
import org.apache.hadoop.fs.permission.FsPermission;
import org.apache.hadoop.hdfs.DFSConfigKeys;
import org.apache.hadoop.hdfs.DFSTestUtil;
import org.apache.hadoop.hdfs.DistributedFileSystem;
import org.apache.hadoop.hdfs.HdfsConfiguration;
import org.apache.hadoop.hdfs.MiniDFSCluster;
import org.apache.hadoop.hdfs.protocol.DatanodeInfo;
import org.apache.hadoop.hdfs.protocol.DatanodeInfo.DatanodeInfoBuilder;
import org.apache.hadoop.hdfs.protocol.ExtendedBlock;
import org.apache.hadoop.hdfs.protocol.LocatedBlock;
import org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager;
import org.apache.hadoop.hdfs.server.protocol.DatanodeCommand;
import org.apache.hadoop.hdfs.server.protocol.HeartbeatResponse;
import org.apache.hadoop.test.GenericTestUtils;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Block replication between two DataNodes with block access tokens on and
 * data-transfer encryption off: the NameNode rotates its block keys twice,
 * each DataNode takes the new keys over a heartbeat, and the first DataNode
 * then replicates a block to the second.
 */
public class TestAdhocWorkload12 {
  private static final int WAIT_MS = 60 * 1000;

  @Test
  @Timeout(120)
  public void run() throws Exception {
    Configuration conf = new HdfsConfiguration();
    conf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, false);
    conf.setBoolean(DFSConfigKeys.DFS_BLOCK_ACCESS_TOKEN_ENABLE_KEY, true);
    conf.setInt(
        DFSConfigKeys.DFS_CLIENT_BLOCK_WRITE_LOCATEFOLLOWINGBLOCK_RETRIES_KEY,
        12);
    conf.setInt(DFSConfigKeys.DFS_CLIENT_SOCKET_TIMEOUT_KEY, 10 * 60 * 1000);
    conf.setInt(DFSConfigKeys.DFS_NAMENODE_HEARTBEAT_RECHECK_INTERVAL_KEY,
        10 * 60 * 1000);
    conf.setLong(DFSConfigKeys.DFS_BLOCK_ACCESS_KEY_UPDATE_INTERVAL_KEY, 60);
    conf.setLong(DFSConfigKeys.DFS_BLOCK_ACCESS_TOKEN_LIFETIME_KEY, 1);
    try (MiniDFSCluster cluster = new MiniDFSCluster.Builder(conf)
        .numDataNodes(2).build();
         DistributedFileSystem fs = cluster.getFileSystem()) {
      cluster.waitActive();
      Path path = new Path("/adhoc-workload-12");
      // One replica, placed on the first DataNode.
      try (FSDataOutputStream out = fs.create(path,
          FsPermission.getFileDefault(), true, 4096, (short) 1,
          fs.getDefaultBlockSize(path), null,
          new InetSocketAddress[] {
              cluster.getDataNodes().get(0).getXferAddress()})) {
        out.write(1);
      }

      LocatedBlock located = DFSTestUtil.getAllBlocks(fs, path).get(0);
      ExtendedBlock block = located.getBlock();
      List<DataNode> nodes = cluster.getDataNodes();
      DataNode source = find(nodes, located.getLocations()[0]);
      assertEquals(nodes.get(0), source,
          "the block must be on the first DataNode");
      DataNode target = nodes.get(0) == source ? nodes.get(1) : nodes.get(0);

      BlockTokenSecretManager master = cluster.getNamesystem()
          .getBlockManager().getBlockTokenSecretManager();
      int initialKeyId = currentKeyId(master);
      // The NameNode rotates its block keys twice.  An explicit rotation
      // marks no DataNode for a key update, so mark the two DataNodes.
      for (int rotation = 0; rotation < 2; rotation++) {
        master.updateKeys(Long.MAX_VALUE);
      }
      assertTrue(currentKeyId(master) == initialKeyId + 2,
          "the NameNode must have rotated twice");
      int currentKeyId = currentKeyId(master);
      for (DataNode node : new DataNode[]{target, source}) {
        cluster.getNamesystem().getBlockManager().getDatanodeManager()
            .getDatanode(node.getDatanodeId()).setNeedKeyUpdate(true);
      }

      // The second DataNode, then the first, takes the new keys over a
      // heartbeat of its own.
      BlockTokenSecretManager targetKeys = target
          .getBlockPoolTokenSecretManager().get(block.getBlockPoolId());
      BlockTokenSecretManager sourceKeys = source
          .getBlockPoolTokenSecretManager().get(block.getBlockPoolId());
      if (refreshKeysFromNameNode(target)) {
        GenericTestUtils.waitFor(
            () -> currentKeyId(targetKeys) == currentKeyId, 100, WAIT_MS);
      }
      if (refreshKeysFromNameNode(source)) {
        GenericTestUtils.waitFor(
            () -> currentKeyId(sourceKeys) == currentKeyId, 100, WAIT_MS);
      }
      assertTrue(currentKeyId(sourceKeys) == currentKeyId,
          "the first DataNode must hold the NameNode's current key");
      assertTrue(targetKeys.hasKey(currentKeyId),
          "the second DataNode must hold the NameNode's current key");

      // The first DataNode replicates the block to the second.
      source.transferBlock(block,
          new DatanodeInfo[]{new DatanodeInfoBuilder()
              .setNodeID(target.getDatanodeId()).build()},
          new StorageType[]{StorageType.DISK}, new String[0]);
      GenericTestUtils.waitFor(
          () -> target.getFSDataset().isValidBlock(block), 20, WAIT_MS);
      assertTrue(target.getFSDataset().isValidBlock(block));
    }
  }

  private static int currentKeyId(BlockTokenSecretManager manager) {
    synchronized (manager) {
      return manager.getCurrentKey().getKeyId();
    }
  }

  /**
   * One heartbeat of the DataNode's first actor; the commands of its
   * response are processed before this returns.
   *
   * @return false when the heartbeat failed, so the caller does not wait
   *         for keys that will not arrive
   */
  private static boolean refreshKeysFromNameNode(DataNode datanode)
      throws IOException {
    BPOfferService service = datanode.getAllBpOs().get(0);
    BPServiceActor actor = service.getBPServiceActors().get(0);
    try {
      HeartbeatResponse response = actor.sendHeartBeat(false);
      DatanodeCommand[] commands = response.getCommands();
      if (commands != null) {
        for (DatanodeCommand command : commands) {
          service.processCommandFromActor(command, actor);
        }
      }
      return true;
    } catch (IOException transport) {
      return false;
    }
  }

  private static DataNode find(List<DataNode> nodes, DatanodeInfo location) {
    return nodes.stream().filter(node -> node.getDatanodeUuid()
        .equals(location.getDatanodeUuid())).findFirst()
        .orElseThrow(IllegalStateException::new);
  }
}
