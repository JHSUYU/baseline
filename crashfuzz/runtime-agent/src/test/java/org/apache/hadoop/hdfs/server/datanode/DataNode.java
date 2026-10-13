package org.apache.hadoop.hdfs.server.datanode;

/** Test-only shape of DataNode's outbound replication task. */
public class DataNode {
    private final BPServiceActor.MockConfiguration conf;

    public DataNode(String dataDirectories) {
        conf = new BPServiceActor.MockConfiguration(dataDirectories);
    }

    public BPServiceActor.MockConfiguration getConf() { return conf; }

    public class DataTransfer implements Runnable {
        @Override public void run() {}
    }
}
