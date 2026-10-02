package org.greygraph.baseline;

import java.net.URI;
import org.apache.hadoop.fs.StorageType;
import org.apache.hadoop.hdfs.DFSClient;
import org.apache.hadoop.hdfs.HdfsConfiguration;
import org.apache.hadoop.hdfs.protocol.DatanodeInfo;
import org.apache.hadoop.hdfs.protocol.LocatedBlock;
import org.apache.hadoop.hdfs.protocol.LocatedBlocks;

/** Report one replica of an isolated probe file through the public DFSClient API. */
public final class ReportOneBadBlock {
  public static void main(String[] args) throws Exception {
    HdfsConfiguration conf = new HdfsConfiguration();
    try (DFSClient client = new DFSClient(URI.create(conf.get("fs.defaultFS")), conf)) {
      LocatedBlocks blocks = client.getLocatedBlocks(args[0], 0);
      LocatedBlock original = blocks.getLocatedBlocks().get(0);
      DatanodeInfo[] locations = {original.getLocations()[0]};
      String[] allIds = original.getStorageIDs();
      StorageType[] allTypes = original.getStorageTypes();
      String[] ids = allIds == null ? null : new String[]{allIds[0]};
      StorageType[] types = allTypes == null ? null : new StorageType[]{allTypes[0]};
      LocatedBlock oneReplica = new LocatedBlock(
          original.getBlock(), locations, ids, types);
      client.reportBadBlocks(new LocatedBlock[]{oneReplica});
      System.out.println("reported one probe replica for block "
          + original.getBlock());
    }
  }
}
