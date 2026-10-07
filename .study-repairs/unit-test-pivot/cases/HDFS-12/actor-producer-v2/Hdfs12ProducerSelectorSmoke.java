/** Offline fail-closed checks for the exact HDFS-12 producer fault selector. */
public final class Hdfs12ProducerSelectorSmoke {
  private static void expect(boolean actual, boolean wanted, String label) {
    if (actual != wanted) throw new AssertionError(label + " expected=" + wanted);
  }

  public static void main(String[] args) {
    String marker = "FAULT:HDFS_KEY_UPDATE:RPC_RESPONSE";
    String site = "BPServiceActor.offerService#keyUpdateResponse/NN0";
    String actor = "episode=2/dn=1/dirs=dfs/data/data1";
    String[] plan = {marker, site, actor, "BP0", "2", "SocketTimeoutException", "8171"};
    expect(HdfsKeyActorProbe.matchesFaultPlan(plan, marker, site, actor, "BP0", 2, 8171),
        true, "exact raw key and actor");
    expect(HdfsKeyActorProbe.matchesFaultPlan(plan, marker, site,
        "episode=2/dn=2/dirs=dfs/data/data2", "BP0", 2, 8171), false, "other DN");
    expect(HdfsKeyActorProbe.matchesFaultPlan(plan, marker, site,
        "episode=3/dn=1/dirs=dfs/data/data1", "BP0", 2, 8171), false, "other cluster");
    expect(HdfsKeyActorProbe.matchesFaultPlan(plan, marker, site, actor, "BP1", 2, 8171),
        false, "other block pool");
    expect(HdfsKeyActorProbe.matchesFaultPlan(plan, marker, site, actor, "BP0", 3, 8171),
        false, "other ordinal");
    expect(HdfsKeyActorProbe.matchesFaultPlan(plan, marker, site, actor, "BP0", 2, 8172),
        false, "other raw key ID");
    expect(HdfsKeyActorProbe.matchesFaultPlan(plan, marker,
        "BPServiceActor.offerService#keyUpdateResponse/NN1", actor, "BP0", 2, 8171),
        false, "other NameNode");
    plan[6] = "*";
    expect(HdfsKeyActorProbe.matchesFaultPlan(plan, marker, site, actor, "BP0", 2, 8171),
        true, "wildcard current key");
    expect(HdfsKeyActorProbe.matchesFaultPlan(plan, marker, site, actor, "BP0", 2, -1),
        false, "wildcard cannot match missing key");
    plan[6] = "-";
    expect(HdfsKeyActorProbe.matchesFaultPlan(plan, marker, site, actor, "BP0", 2, 8171),
        false, "SASL selector cannot match producer key");
    expect(HdfsKeyActorProbe.matchesFaultPlan(plan, marker, site, actor, "BP0", 2, -1),
        true, "SASL selector uses absent-key sentinel");
    System.out.println("HDFS-12 producer selector smoke: 11 checks passed");
  }
}
