package baseline.solr19v2;

import org.apache.solr.common.params.ModifiableSolrParams;
import org.apache.zookeeper.KeeperException;

/** Small identity-injection check; this does not launch or replace a cluster JUnit. */
public final class SmokeV2 {
  public static void main(String[] args) throws Exception {
    if (args.length != 1) throw new IllegalArgumentException("JETTY, OWNER, or PRODUCER");
    String core = "testAddMultipleReplicas_shard1_replica_n1";
    Object owner = new Object();
    Object producer = new Object();
    ActorProbe.bindZkClient(owner, "127.0.0.1:10001_solr", "zk");
    ActorProbe.bindZkClient(producer, "127.0.0.1:10002_solr", "zk");
    ModifiableSolrParams params = new ModifiableSolrParams();
    params.set("name", core);
    params.set("coreNodeName", "core_node2");
    ActorProbe.sender("ADD_REPLICA", params, "127.0.0.1:10001_solr",
        "http://127.0.0.1:10001/solr", producer);
    String path = "/collections/testAddMultipleReplicas/state.json";
    Object wrong = args[0].equals("PRODUCER") ? owner : producer;
    Object right = args[0].equals("PRODUCER") ? producer : owner;
    ActorProbe.io("GET_DATA", path, "zk", wrong);
    try {
      ActorProbe.io("GET_DATA", path, "zk", right);
      throw new AssertionError("exact actor selector failed to inject");
    } catch (KeeperException.ConnectionLossException expected) {
      System.out.println("SMOKE_OK " + args[0]);
    }
  }
}
