package org.apache.hadoop.hdfs.server.datanode;

/** Test-only shape of Hadoop's package-private BPServiceActor/DataNode chain. */
public class BPServiceActor {
    private final MockDataNode dn;

    public BPServiceActor(String dataDirectories) {
        dn = new MockDataNode(dataDirectories);
    }

    public void selectedIo() {
        Sink.write();
    }

    public static class MockDataNode {
        private final MockConfiguration conf;

        public MockDataNode(String dataDirectories) {
            conf = new MockConfiguration(dataDirectories);
        }

        public MockConfiguration getConf() { return conf; }
    }

    public static class MockConfiguration {
        private final String dataDirectories;

        public MockConfiguration(String dataDirectories) {
            this.dataDirectories = dataDirectories;
        }

        public String get(String key) {
            return "dfs.datanode.data.dir".equals(key) ? dataDirectories : null;
        }
    }

    public static class Sink {
        public static void write() {}
    }
}
