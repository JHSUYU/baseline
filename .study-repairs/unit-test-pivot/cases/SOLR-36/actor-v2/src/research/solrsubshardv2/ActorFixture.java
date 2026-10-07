package org.apache.solr.research.solrsubshardv2;

import org.apache.zookeeper.KeeperException;
import research.solrsubshardv2.Probe;

/** Same I/O signature on two clients; only the planned client may fault. */
public final class ActorFixture {
  private ActorFixture() {}

  private static void fire(Object client) throws KeeperException {
    Probe.nativeEntry(client, "/collections/collection1/state.json",
        "lambda$getData$6(Ljava/lang/String;)V");
  }

  public static void main(String[] ignored) throws Exception {
    Probe.initialize();
    Object shard1 = new Object();
    Object shard2 = new Object();
    Probe.bindServerClient(shard1, "node-one", "/tmp/run/shard1");
    Probe.bindServerClient(shard2, "node-two", "/tmp/run/shard2");
    fire(shard2);
    try {
      fire(shard1);
    } catch (KeeperException.ConnectionLossException expected) {
      System.out.println("ACTOR_V2_EXPECTED_CONNECTIONLOSS");
    }
    Probe.close();
  }
}
