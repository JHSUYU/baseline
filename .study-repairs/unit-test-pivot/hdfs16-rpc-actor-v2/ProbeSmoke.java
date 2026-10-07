import java.io.EOFException;
import org.apache.hadoop.hdfs.hdfs16independent.Probe;
import org.apache.hadoop.hdfs.protocol.DatanodeID;
import org.apache.hadoop.hdfs.security.token.block.ExportedBlockKeys;
import org.apache.hadoop.hdfs.server.common.HdfsServerConstants.NodeType;
import org.apache.hadoop.hdfs.server.common.StorageInfo;
import org.apache.hadoop.hdfs.server.protocol.DatanodeRegistration;
import org.apache.hadoop.hdfs.server.protocol.NamespaceInfo;

/** No-cluster smoke for sender UUID/BP binding and strict actor ordinals. */
public final class ProbeSmoke {
  private static DatanodeRegistration registration(String uuid, String bp) {
    DatanodeID id = new DatanodeID("127.0.0.1", "localhost", uuid,
        50010, 50020, 50030, 50040);
    DatanodeRegistration registration = new DatanodeRegistration(id,
        new StorageInfo(NodeType.DATA_NODE), new ExportedBlockKeys(), "3.4.3");
    NamespaceInfo namespace = new NamespaceInfo();
    namespace.setBlockPoolID(bp);
    registration.setNamespaceInfo(namespace);
    return registration;
  }

  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("plan trace");
    System.setProperty("hdfs16.independent.fault.plan", args[0]);
    System.setProperty("hdfs16.independent.trace", args[1]);
    Probe.registerNnPort(19001);
    Probe.rpcResponse(19001); // No sender actor: fail closed.
    String firstPrior = Probe.bindDatanodeRpc(registration("dn-one", "bp-one"));
    try {
      Probe.rpcResponse(19001); // Per-actor ordinal 1.
      Probe.rpcResponse(19002); // Unknown NN peer: fail closed.
      try {
        Probe.rpcResponse(19001); // Exact actor/ordinal 2: one EOF.
        throw new AssertionError("planned EOF not injected");
      } catch (EOFException expected) {
        // Exact selected fault.
      }
    } finally {
      Probe.restoreDatanodeRpc(firstPrior);
    }
    String secondPrior = Probe.bindDatanodeRpc(registration("dn-two", "bp-one"));
    try {
      Probe.rpcResponse(19001); // Different actor starts at ordinal 1.
    } finally {
      Probe.restoreDatanodeRpc(secondPrior);
    }
    Probe.rpcResponse(19001); // Restored scope: fail closed again.
    Probe.guard(true, 7, 1001, 1002, true);
    System.out.println("HDFS-16 sender actor smoke PASS");
  }
}
