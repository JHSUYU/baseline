package org.apache.hadoop.hdfs;

import java.io.IOException;
import java.util.Arrays;
import java.util.List;
import java.util.function.Supplier;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.FSDataOutputStream;
import org.apache.hadoop.fs.FileChecksum;
import org.apache.hadoop.fs.FileSystem;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.hdfs.client.HdfsClientConfigKeys;
import org.apache.hadoop.hdfs.protocol.ErasureCodingPolicy;
import org.apache.hadoop.hdfs.protocol.SystemErasureCodingPolicies;
import org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager;
import org.apache.hadoop.hdfs.security.token.block.DataEncryptionKey;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.test.GenericTestUtils;
import org.junit.Assert;
import org.junit.Test;

/**
 * Case-local XOR-2-1 adaptation of the 3.4.3
 * TestEncryptedTransfer#testFileChecksumWithInvalidEncryptionKey workload.
 * The original uses a replicated file; this variant exercises the striped
 * checksum branch and keeps the real NN/DN encryption-key expiration setup.
 */
public class StripedChecksumStaleKeyControl {
  @Test(timeout = 180000)
  public void stripedChecksumAfterEncryptionKeyExpires() throws Exception {
    System.out.println("CONTROL checksum_class_origin=" + Class.forName(
        "org.apache.hadoop.hdfs.FileChecksumHelper$StripedFileNonStripedChecksumComputer")
        .getProtectionDomain().getCodeSource().getLocation());
    Configuration conf = new Configuration();
    conf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, true);
    conf.setBoolean(DFSConfigKeys.DFS_BLOCK_ACCESS_TOKEN_ENABLE_KEY, true);
    MiniDFSCluster cluster = new MiniDFSCluster.Builder(conf)
        .numDataNodes(3).build();
    DistributedFileSystem dfs = null;
    try {
      cluster.waitActive();
      Configuration clientConf = new Configuration(conf);
      clientConf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, false);
      clientConf.unset(DFSConfigKeys.DFS_DATA_ENCRYPTION_ALGORITHM_KEY);
      dfs = (DistributedFileSystem) FileSystem.get(clientConf);
      ErasureCodingPolicy policy = SystemErasureCodingPolicies.getByID(
          SystemErasureCodingPolicies.XOR_2_1_POLICY_ID);
      dfs.enableErasureCodingPolicy(policy.getName());
      Path directory = new Path("/ec");
      dfs.mkdirs(directory);
      dfs.setErasureCodingPolicy(directory, policy.getName());
      Path file = new Path(directory, "stale-key-checksum");
      byte[] data = new byte[policy.getCellSize() * policy.getNumDataUnits()];
      Arrays.fill(data, (byte) 'a');
      try (FSDataOutputStream out = dfs.create(file)) {
        out.write(data);
      }
      FileChecksum expected = dfs.getFileChecksum(file);
      System.out.println("CONTROL healthy_checksum=" + expected);

      DFSClient client = DFSClientAdapter.getDFSClient(dfs);
      DataEncryptionKey cached = client.getEncryptionKey();
      Assert.assertNotNull("healthy checksum should cache a DEK", cached);
      System.out.println("CONTROL cached_key_id=" + cached.keyId);
      BlockTokenSecretManager btsm = cluster.getNamesystem()
          .getBlockManager().getBlockTokenSecretManager();
      btsm.setKeyUpdateIntervalForTesting(2000);
      btsm.setTokenLifetime(2000);
      btsm.clearAllKeysForTesting();
      List<DataNode> dataNodes = cluster.getDataNodes();
      for (DataNode dn : dataNodes) {
        GenericTestUtils.waitFor(new Supplier<Boolean>() {
          @Override public Boolean get() {
            return !dn.getBlockPoolTokenSecretManager()
                .get(cached.blockPoolId).hasKey(cached.keyId);
          }
        }, 100, 30000);
        System.out.println("CONTROL dn_identity=" + dn.getDatanodeId()
            + " managerIdentity=" + System.identityHashCode(
                dn.getBlockPoolTokenSecretManager().get(cached.blockPoolId))
            + " cachedKeyId=" + cached.keyId + " keyPresent=false");
      }
      System.out.println("CONTROL stale_key_absent_on_all_dns=true");
      System.setProperty("hdfs54.faultPhase", "postExpiry");
      System.out.println("CONTROL phase=postExpiry");
      boolean fixed = Boolean.getBoolean("hdfs17897.expectFixed");
      try {
        FileChecksum actual = dfs.getFileChecksum(file);
        System.out.println("CONTROL post_expiry_checksum=" + actual);
        if (!fixed) {
          Assert.fail("unfixed 3.4.3 unexpectedly recovered stale key");
        }
        Assert.assertEquals(expected, actual);
        System.out.println("CONTROL outcome=fixed_recovered");
      } catch (IOException error) {
        System.out.println("CONTROL post_expiry_exception="
            + error.getClass().getName() + ":" + error.getMessage());
        if (fixed) throw error;
        Assert.assertTrue("failure must be striped checksum exhaustion",
            error.getMessage().contains("Fail to get block checksum"));
        // The same client should still fail because its stale key was not cleared.
        try {
          dfs.getFileChecksum(file);
          Assert.fail("unfixed client unexpectedly recovered on retry");
        } catch (IOException repeat) {
          Assert.assertTrue(repeat.getMessage()
              .contains("Fail to get block checksum"));
          System.out.println("CONTROL repeated_failure="
              + repeat.getClass().getName());
        }
        System.out.println("CONTROL outcome=known_bug_reproduced");
        throw new AssertionError("HDFS-17897: original striped checksum failed after stale DEK rejection", error);
      }
    } finally {
      if (dfs != null) dfs.close();
      cluster.shutdown();
    }
  }
}
