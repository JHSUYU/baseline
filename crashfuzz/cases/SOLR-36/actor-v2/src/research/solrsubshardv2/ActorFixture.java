package org.apache.solr.research.solrsubshardv2;

import org.apache.zookeeper.KeeperException;
import org.apache.solr.common.cloud.Slice;
import research.solrsubshardv2.Probe;

/** Same I/O signature on two clients; only the planned client may fault. */
public final class ActorFixture {
  private ActorFixture() {}

  private static void fire(Object client) throws KeeperException {
    Probe.nativeEntry(client, "/collections/collection1/state.json",
        "lambda$getData$6(Ljava/lang/String;)V");
  }

  public static void main(String[] args) throws Exception {
    Probe.initialize();
    Object shard1 = new Object();
    Object shard2 = new Object();
    Probe.bindServerClient(shard1, "node-one", "/tmp/run/shard1");
    Probe.bindServerClient(shard2, "node-two", "/tmp/run/shard2");
    Object firstHandle = new Object();
    Probe.bindFixtureSession(shard1, firstHandle, 101L, "zk1:2181", true);
    Probe.bindFixtureSession(shard2, new Object(), 202L, "zk2:2181", true);
    if (args.length > 0 && "wrong-target".equals(args[0])) {
      Probe.targetEnter("collection1", "shard1_0", "replica1", "node-one",
          shard2, "FROMLEADER");
      Probe.guard36(Slice.State.ACTIVE);
      Probe.close();
      return;
    }
    if (args.length > 0 && "wrong-session".equals(args[0])) {
      // Bind the first handle without consuming the selected I/O ordinal.
      Probe.targetEnter("collection1", "shard1_0", "replica1", "node-one",
          shard1, "FROMLEADER");
      Probe.bindFixtureSession(shard1, new Object(), 303L, "zk3:2181", true);
    }
    fire(shard2);
    try {
      fire(shard1);
    } catch (KeeperException.ConnectionLossException expected) {
      System.out.println("ACTOR_V2_EXPECTED_CONNECTIONLOSS");
    }
    Probe.close();
  }
}
