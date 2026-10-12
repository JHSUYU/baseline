package org.apache.hadoop.hdfs.server.datanode;

/** Test-only shape of Hadoop's DataXceiver to DataNode ownership. */
public class DataXceiver {
    private final BPServiceActor.MockDataNode datanode;

    public DataXceiver(String dataDirectories) {
        datanode = new BPServiceActor.MockDataNode(dataDirectories);
    }
}
