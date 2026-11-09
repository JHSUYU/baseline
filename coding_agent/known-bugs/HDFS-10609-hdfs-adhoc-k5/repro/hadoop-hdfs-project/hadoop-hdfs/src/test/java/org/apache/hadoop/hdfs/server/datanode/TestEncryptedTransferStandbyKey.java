package org.apache.hadoop.hdfs.server.datanode;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import java.io.IOException;
import java.io.OutputStream;
import java.util.List;

import org.apache.commons.logging.Log;
import org.apache.commons.logging.LogFactory;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.FSDataInputStream;
import org.apache.hadoop.fs.FileSystem;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.hdfs.DFSConfigKeys;
import org.apache.hadoop.hdfs.DFSTestUtil;
import org.apache.hadoop.hdfs.MiniDFSCluster;
import org.apache.hadoop.hdfs.MiniDFSNNTopology;
import org.apache.hadoop.hdfs.protocol.LocatedBlock;
import org.apache.hadoop.hdfs.server.namenode.ha.HATestUtil;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.junit.Test;

import com.google.common.base.Supplier;

/**
 * Encrypted data transfer in an HA cluster. A DataNode encrypts DN-to-DN
 * transfers (pipeline recovery / re-replication) with its "current" block key,
 * which is whatever key set it received last -- possibly from the STANDBY NN.
 * A DataNode that (re)started while the standby NN was down only knows the
 * active NN's keys, so it rejects such transfers with
 * InvalidEncryptionKeyException.
 */
public class TestEncryptedTransferStandbyKey {
  private static final Log LOG =
      LogFactory.getLog(TestEncryptedTransferStandbyKey.class);
  private static final String PLAIN_TEXT = "this is very secret plain text";
  private static final Path TEST_PATH = new Path("/non-encrypted-file");

  private static int currentKeyId(DataNode dn, String bpid) {
    return dn.blockPoolTokenSecretManager.generateDataEncryptionKey(bpid)
        .keyId;
  }

  @Test(timeout = 120000)
  public void testEncryptedAppendRequiringBlockTransferAfterStandbyCrash()
      throws Exception {
    Configuration conf = new Configuration();
    conf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, true);
    conf.setBoolean(DFSConfigKeys.DFS_BLOCK_ACCESS_TOKEN_ENABLE_KEY, true);
    MiniDFSCluster cluster = null;
    LogCapturer dnLogs = LogCapturer.captureLogs(DataNode.LOG);
    try {
      cluster = new MiniDFSCluster.Builder(conf)
          .nnTopology(MiniDFSNNTopology.simpleHATopology())
          .numDataNodes(3).build();
      cluster.waitActive();
      cluster.transitionToActive(0);
      final String bpid = cluster.getNamesystem(0).getBlockPoolId();

      FileSystem fs = HATestUtil.configureFailoverFs(cluster, conf);
      writeTestDataToFile(fs);
      assertEquals(PLAIN_TEXT, DFSTestUtil.readFile(fs, TEST_PATH));

      // 1. The standby NN (nn1) restarts. It generates a fresh key set and the
      //    DNs re-register with it, so each DN's current key is now nn1's.
      cluster.restartNameNode(1, true);
      final int standbyKeyId = cluster.getNamesystem(1).getBlockManager()
          .generateDataEncryptionKey().keyId;
      final int activeKeyId = cluster.getNamesystem(0).getBlockManager()
          .generateDataEncryptionKey().keyId;
      LOG.info("active NN current key=" + activeKeyId
          + ", standby NN current key=" + standbyKeyId);
      for (final DataNode dn : cluster.getDataNodes()) {
        GenericTestUtils.waitFor(new Supplier<Boolean>() {
          @Override
          public Boolean get() {
            return currentKeyId(dn, bpid) == standbyKeyId;
          }
        }, 100, 30000);
      }

      // 2. The standby NN crashes.
      cluster.shutdownNameNode(1);

      // 3. A new DN joins (or a DN restarts) while the standby is down: it
      //    registers only with the active NN and knows only its keys.
      cluster.startDataNodes(conf, 1, true, null, null);
      DataNode newDn = cluster.getDataNodes().get(3);
      LOG.info("new DN current key=" + currentKeyId(newDn, bpid));

      // 4. One replica holder dies; the append needs a replacement DN and a
      //    DN-to-DN block transfer from a surviving replica to the new DN.
      FSDataInputStream in = fs.open(TEST_PATH);
      List<LocatedBlock> locatedBlocks = DFSTestUtil.getAllBlocks(in);
      in.close();
      assertEquals(1, locatedBlocks.size());
      assertEquals(3, locatedBlocks.get(0).getLocations().length);
      DataNode dn = cluster.getDataNode(
          locatedBlocks.get(0).getLocations()[0].getIpcPort());
      dn.shutdown();

      IOException appendFailure = null;
      try {
        writeTestDataToFile(fs);
      } catch (IOException e) {
        appendFailure = e;
        LOG.info("append failed", e);
      }
      String logs = dnLogs.getOutput();
      assertTrue("expected InvalidEncryptionKeyException at the new DN",
          logs.contains("InvalidEncryptionKeyException")
          && logs.contains("BlockTokenSecretManager.retrieveDataEncryptionKey"));
      LOG.info("append failure: " + appendFailure);
      fs.close();
    } finally {
      dnLogs.stopCapturing();
      if (cluster != null) {
        cluster.shutdown();
      }
    }
  }

  private static void writeTestDataToFile(FileSystem fs) throws IOException {
    OutputStream out;
    if (!fs.exists(TEST_PATH)) {
      out = fs.create(TEST_PATH);
    } else {
      out = fs.append(TEST_PATH);
    }
    out.write(PLAIN_TEXT.getBytes());
    out.close();
  }
}
