package org.apache.hadoop.hdfs.hdfs39independent;

import java.io.EOFException;
import java.util.ArrayList;
import java.util.List;
import org.apache.hadoop.hdfs.protocol.DatanodeID;
import org.apache.hadoop.hdfs.security.token.block.ExportedBlockKeys;
import org.apache.hadoop.hdfs.server.common.HdfsServerConstants.NodeType;
import org.apache.hadoop.hdfs.server.common.StorageInfo;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.hdfs.server.protocol.DatanodeRegistration;
import org.apache.hadoop.hdfs.server.protocol.NamespaceInfo;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/** No-cluster actor/peer/target check for the isolated HDFS-39 probe. */
public final class ProbeSmoke {
  private static DatanodeRegistration registration(String uuid, String bp) {
    DatanodeID id = new DatanodeID("127.0.0.1", "localhost", uuid,
        50010, 50020, 50030, 50040);
    DatanodeRegistration value = new DatanodeRegistration(id,
        new StorageInfo(NodeType.DATA_NODE), new ExportedBlockKeys(), "3.4.3");
    NamespaceInfo namespace = new NamespaceInfo();
    namespace.setBlockPoolID(bp);
    value.setNamespaceInfo(namespace);
    return value;
  }

  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("plan trace");
    System.setProperty("hdfs39.independent.fault.plan", args[0]);
    System.setProperty("hdfs39.independent.trace", args[1]);
    List<DataNode> nodes = new ArrayList<DataNode>();
    for (int i = 0; i < 4; i++) {
      DataNode node = mock(DataNode.class);
      when(node.getDatanodeUuid()).thenReturn("uuid-" + i);
      nodes.add(node);
    }
    Probe.registerCluster(nodes, 19001, "bp-one");
    String api = "DatanodeProtocolClientSideTranslatorPB.blockReceivedAndDeleted";
    Probe.rpcIoWithApi("RPC_SEND", 19001, api); // No bound sender.
    Probe.Source prior = Probe.requestSource(registration("uuid-0", "bp-one"));
    String oldContext = Probe.requestContext("blockReceivedAndDeleted:blocks=[7]");
    try {
      Probe.rpcIoWithApi("RPC_SEND", 19001, api); // dn0 ordinal 1.
    } finally {
      Probe.restoreRequestContext(oldContext);
      Probe.restoreRequestSource(prior);
    }
    prior = Probe.requestSource(registration("uuid-1", "bp-one"));
    oldContext = Probe.requestContext("blockReceivedAndDeleted:blocks=[7]");
    try {
      Probe.rpcIoWithApi("RPC_SEND", 19002, api); // Unknown NN peer.
      try {
        Probe.rpcIoWithApi("RPC_SEND", 19001, api); // dn1 ordinal 1.
        throw new AssertionError("planned EOF not injected");
      } catch (EOFException expected) {
        // Exact actor fault.
      }
    } finally {
      Probe.restoreRequestContext(oldContext);
      Probe.restoreRequestSource(prior);
    }
    prior = Probe.requestSource(registration("uuid-2", "wrong-pool"));
    try {
      Probe.rpcIoWithApi("RPC_SEND", 19001, api); // Wrong BP: fail closed.
    } finally {
      Probe.restoreRequestSource(prior);
    }
    prior = Probe.requestSource(registration("uuid-3", "bp-one"));
    try {
      Probe.rpcIoWithApi("RPC_SEND", 19001, api); // No block list: fail closed.
    } finally {
      Probe.restoreRequestSource(prior);
    }
    Probe.guard(true, "/testMultipleAppend/foo", 7, "COMMITTED");
    System.out.println("HDFS-39 DN actor smoke PASS");
  }
}
