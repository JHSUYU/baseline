package org.apache.hadoop.hdfs.server.datanode;

import java.util.ArrayList;

/** Test-only duplicate-name fixture for MiniDFSCluster frame computation. */
public final class DataNode {
  public Object choose(boolean self) {
    Object value;
    if (self) value = this;
    else value = new ArrayList<Object>();
    return value;
  }
}
