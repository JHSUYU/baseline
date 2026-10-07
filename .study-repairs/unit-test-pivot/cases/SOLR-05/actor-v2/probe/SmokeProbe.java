package baseline.solr05v2;

import org.apache.zookeeper.KeeperException;

/** No cluster: same API path on a wrong node or replica cannot consume a fault. */
public final class SmokeProbe {
  private static final String PATH = "/collections/testAddMultipleReplicas/state.json";
  private static final String COLLECTION = "testAddMultipleReplicas";
  private static final String SHARD = "shard1";
  public static void main(String[] args) throws Exception {
    Object right = new Object(), otherNode = new Object();
    Object rightReader = new Object(), otherReader = new Object();
    String node1 = "127.0.0.1:12345_solr", node2 = "127.0.0.1:23456_solr";
    FeedbackProbe.registerNode(right, rightReader, node1);
    FeedbackProbe.registerNode(otherNode, otherReader, node2);
    FeedbackProbe.registerJettyRole("node1", node1);
    FeedbackProbe.registerJettyRole("node2", node2);
    for (int round = 0; round < 2; round++) {
      FeedbackProbe.enterRegister(otherNode, otherReader, node2,
          COLLECTION, SHARD, "core_node1", "coreA");
      FeedbackProbe.io("GET_DATA", PATH, otherNode);
      FeedbackProbe.exitRegister(otherNode, "coreA");
      FeedbackProbe.enterRegister(right, rightReader, node1,
          COLLECTION, SHARD, "core_node2", "coreB");
      FeedbackProbe.io("GET_DATA", PATH, right);
      FeedbackProbe.exitRegister(right, "coreB");
      FeedbackProbe.enterRegister(right, rightReader, node1,
          COLLECTION, SHARD, "core_node1", "coreA");
      try {
        FeedbackProbe.io("GET_DATA", PATH, right);
        throw new AssertionError("Selected actor/replica was not injected");
      } catch (KeeperException.ConnectionLossException expected) {
        // Only exact receiver and register context consume the selector.
      }
      if (round == 1)
        FeedbackProbe.targetCheck(false, COLLECTION, SHARD, "core_node1",
            "coreA", right, rightReader, node1);
      FeedbackProbe.exitRegister(right, "coreA");
    }
    try {
      FeedbackProbe.enterRegister(right, otherReader, node1,
          COLLECTION, SHARD, "core_node1", "coreA");
      throw new AssertionError("Wrong ZkStateReader accepted");
    } catch (IllegalStateException expected) {
      // Actual reader object identity is required.
    }
    System.out.println("SOLR05_V2_SMOKE_PASS");
  }
}
