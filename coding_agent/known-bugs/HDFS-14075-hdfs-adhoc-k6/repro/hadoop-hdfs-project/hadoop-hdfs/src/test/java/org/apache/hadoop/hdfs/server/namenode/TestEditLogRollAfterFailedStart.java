package org.apache.hadoop.hdfs.server.namenode;

import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.FileUtil;
import org.apache.hadoop.hdfs.DFSConfigKeys;
import org.apache.hadoop.hdfs.HdfsConfiguration;
import org.apache.hadoop.hdfs.MiniDFSCluster;
import org.apache.hadoop.hdfs.server.common.Storage.StorageDirectory;
import org.apache.hadoop.hdfs.server.namenode.NNStorage.NameNodeDirType;
import org.apache.hadoop.hdfs.server.protocol.NamenodeProtocols;
import org.junit.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * A roll of the edit log whose second half (starting the new segment) fails
 * because the edits directories transiently cannot create the new
 * in-progress file leaves FSEditLog in BETWEEN_LOG_SEGMENTS while the
 * NameNode keeps running. The next rollEditLog() (e.g. the periodic one
 * from the SecondaryNameNode / Standby, after the disk recovered) fails the
 * ad hoc check in FSEditLog.endCurrentLogSegment with IllegalStateException.
 */
public class TestEditLogRollAfterFailedStart {
  private static final Logger LOG =
      LoggerFactory.getLogger(TestEditLogRollAfterFailedStart.class);

  @Test(timeout = 120000)
  public void testRollAfterFailedSegmentStart() throws Exception {
    Configuration conf = new HdfsConfiguration();
    // allow failed storage to be restored once the disk is healthy again
    conf.setBoolean(DFSConfigKeys.DFS_NAMENODE_NAME_DIR_RESTORE_KEY, true);
    MiniDFSCluster cluster =
        new MiniDFSCluster.Builder(conf).numDataNodes(1).build();
    List<File> obstructions = new ArrayList<File>();
    try {
      cluster.waitActive();
      NamenodeProtocols nn = cluster.getNameNode().getRpcServer();
      FSNamesystem fsn = cluster.getNamesystem();
      FSImage fsimage = fsn.getFSImage();
      FSEditLog editLog = fsn.getEditLog();

      // A normal roll works.
      nn.rollEditLog();
      assertTrue(editLog.isSegmentOpen());

      // Next roll: OP_END_LOG_SEGMENT takes lastWritten+1, the new segment
      // starts at lastWritten+2. Simulate a disk fault on every edits dir:
      // the new in-progress file cannot be created there.
      long nextSegment = editLog.getLastWrittenTxId() + 2;
      for (StorageDirectory sd :
          fsimage.getStorage().dirIterable(NameNodeDirType.EDITS)) {
        File f = NNStorage.getInProgressEditsFile(sd, nextSegment);
        assertTrue(f.mkdirs());
        obstructions.add(f);
      }

      try {
        nn.rollEditLog();
        fail("roll should have failed to start the new segment");
      } catch (IOException e) {
        LOG.info("First roll failed as injected: " + e);
      }
      LOG.info("NameNode still running; edit log segment open = "
          + editLog.isSegmentOpen());

      // Disk recovers.
      for (File f : obstructions) {
        FileUtil.fullyDelete(f);
      }

      // The next periodic roll (from SNN / standby) now hits the check.
      try {
        nn.rollEditLog();
        fail("expected IllegalStateException");
      } catch (IllegalStateException ise) {
        LOG.error("Second roll failed the ad hoc check", ise);
        ise.printStackTrace(System.out);
        throw ise;
      }
    } finally {
      for (File f : obstructions) {
        FileUtil.fullyDelete(f);
      }
      cluster.shutdown();
    }
  }
}
