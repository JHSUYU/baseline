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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.FSDataOutputStream;
import org.apache.hadoop.fs.FileSystem;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.hdfs.client.HdfsClientConfigKeys;
import org.apache.hadoop.hdfs.protocol.HdfsConstants;
import org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager;
import org.apache.hadoop.hdfs.server.blockmanagement.BlockManager;
import org.apache.hadoop.hdfs.server.blockmanagement.DatanodeDescriptor;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.hdfs.server.datanode.DataNodeTestUtils;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.event.Level;

/**
 * Encrypted data transfer + block tokens + "overwrite downstream derived QOP".
 *
 * The NameNode rolls its block key (as its HeartbeatManager does every
 * dfs.block.access.key.update.interval). Before the DataNodes have received
 * the resulting KeyUpdateCommand in a heartbeat response (heartbeats delayed
 * / response lost), a client writes a file with replication 3. The first DN
 * of the pipeline re-signs the (valid) client token with its own *current*
 * block key while keeping the token's keyId, so the second DN rejects it in
 * BlockTokenSecretManager.checkAccess with "doesn't have the correct token
 * password".
 */
public class TestEncryptedTransferKeyRollDownstreamQOP {
  private static final Logger LOG =
      LoggerFactory.getLogger(TestEncryptedTransferKeyRollDownstreamQOP.class);

  private MiniDFSCluster cluster;
  private FileSystem fs;

  @AfterEach
  public void teardown() throws IOException {
    if (fs != null) {
      fs.close();
    }
    if (cluster != null) {
      cluster.shutdown();
    }
  }

  private static FileSystem getFileSystem(Configuration conf)
      throws IOException {
    Configuration localConf = new Configuration(conf);
    localConf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, false);
    localConf.unset(DFSConfigKeys.DFS_DATA_ENCRYPTION_ALGORITHM_KEY);
    return FileSystem.get(localConf);
  }

  @Test
  public void testWriteAfterBlockKeyRollBeforeDNKeyUpdate() throws Exception {
    Configuration conf = new Configuration();
    conf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, true);
    conf.setBoolean(DFSConfigKeys.DFS_BLOCK_ACCESS_TOKEN_ENABLE_KEY, true);
    conf.setBoolean(
        DFSConfigKeys.DFS_ENCRYPT_DATA_OVERWRITE_DOWNSTREAM_DERIVED_QOP_KEY,
        true);
    // Do not replace DNs on pipeline failure, so the write simply proceeds
    // with fewer replicas instead of retrying forever.
    conf.setBoolean(HdfsClientConfigKeys.BlockWrite.ReplaceDatanodeOnFailure
        .ENABLE_KEY, false);

    cluster = new MiniDFSCluster.Builder(conf).numDataNodes(3).build();
    cluster.waitActive();
    fs = getFileSystem(conf);

    // Sanity: with consistent keys a 3-replica write works.
    DFSTestUtil.createFile(fs, new Path("/before-roll"), 1024, (short) 3, 0L);
    DFSTestUtil.waitReplication(fs, new Path("/before-roll"), (short) 3);

    BlockManager bm = cluster.getNamesystem().getBlockManager();
    BlockTokenSecretManager nnSm = bm.getBlockTokenSecretManager();
    int oldKeyId = nnSm.getCurrentKey().getKeyId();

    // DN heartbeats are delayed (or their responses lost): DNs do not
    // receive the KeyUpdateCommand right after the NN rolls its key.
    for (DataNode dn : cluster.getDataNodes()) {
      DataNodeTestUtils.setHeartbeatsDisabledForTests(dn, true);
    }

    // The NN's periodic block key update (what HeartbeatManager.Monitor does
    // once keyUpdateInterval has elapsed): roll the key and mark all DNs as
    // needing a key update in their next heartbeat.
    assertTrue(nnSm.updateKeys(Long.MAX_VALUE));
    for (DatanodeDescriptor d :
        bm.getDatanodeManager().getDatanodeListForReport(
            HdfsConstants.DatanodeReportType.LIVE)) {
      d.setNeedKeyUpdate(true);
    }
    int newKeyId = nnSm.getCurrentKey().getKeyId();
    assertNotEquals(oldKeyId, newKeyId);
    for (DataNode dn : cluster.getDataNodes()) {
      String bpid = cluster.getNamesystem().getBlockPoolId();
      // DN still uses the old current key, but already knows the new one
      // (it was the NN's "nextKey" exported earlier).
      assertEquals(oldKeyId, dn.getBlockPoolTokenSecretManager().get(bpid)
          .getCurrentKey().getKeyId());
      assertTrue(dn.getBlockPoolTokenSecretManager().get(bpid)
          .hasKey(newKeyId));
    }

    LogCapturer dnLogs = LogCapturer.captureLogs(
        LoggerFactory.getLogger(DataNode.class));
    // DataXceiver logs the InvalidToken stack trace only at TRACE.
    GenericTestUtils.setLogLevel(DataNode.LOG, Level.TRACE);
    Path p = new Path("/after-roll");
    try (FSDataOutputStream out = fs.create(p, (short) 3)) {
      out.write(new byte[1024]);
      out.hflush();
    } catch (IOException e) {
      LOG.info("Write failed", e);
    } finally {
      dnLogs.stopCapturing();
      GenericTestUtils.setLogLevel(DataNode.LOG, Level.INFO);
    }
    String logs = dnLogs.getOutput();
    assertTrue(logs.contains("doesn't have the correct token password"),
        "expected downstream DN to reject the re-signed block token");
    assertTrue(logs.contains("BlockTokenSecretManager.checkAccess("
        + "BlockTokenSecretManager.java:418)"));
  }
}
