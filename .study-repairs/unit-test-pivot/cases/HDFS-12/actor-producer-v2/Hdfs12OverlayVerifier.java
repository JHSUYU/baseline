/** Loads every woven Hadoop class under JVM verification without starting a cluster. */
public final class Hdfs12OverlayVerifier {
  public static void main(String[] args) throws Exception {
    String[] classes = {
        "org.apache.hadoop.hdfs.MiniDFSCluster",
        "org.apache.hadoop.hdfs.server.datanode.DataNode",
        "org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager",
        "org.apache.hadoop.hdfs.protocol.datatransfer.sasl.SaslDataTransferServer",
        "org.apache.hadoop.hdfs.server.datanode.BPServiceActor",
        "org.apache.hadoop.hdfs.server.datanode.BPOfferService"
    };
    for (String name : classes) {
      Class.forName(name, false, Hdfs12OverlayVerifier.class.getClassLoader());
      System.out.println("verified " + name);
    }
  }
}
