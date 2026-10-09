package research.solrsubshard;

import java.util.Properties;

/** Exercises the same pure predicates used by the runtime HTTP fault gate. */
public final class RoleIdentitySmoke {
  private static void check(boolean condition, String message) {
    if (!condition) throw new AssertionError(message);
  }

  public static void main(String[] args) {
    check(Probe.liveLeaderMatches("core_node4", "core_node4", "jetty4", "jetty4",
                                  1, true, true), "core_node4 current leader");
    check(Probe.liveLeaderMatches("core_node3", "core_node3", "jetty3", "jetty3",
                                  1, true, true), "role follows current core_node3 leader");
    check(!Probe.liveLeaderMatches("core_node4", "core_node3", "jetty4", "jetty3",
                                   1, true, true), "wrong replica must fail closed");
    check(!Probe.liveLeaderMatches("core_node4", "core_node4", "jetty3", "jetty4",
                                   1, true, true), "wrong physical sender must fail closed");
    check(!Probe.liveLeaderMatches("core_node4", "core_node4", "jetty4", "jetty4",
                                   2, true, true), "ambiguous leaders must fail closed");
    check(!Probe.liveLeaderMatches("core_node4", "core_node4", "jetty4", "jetty4",
                                   1, false, true), "nonleader descriptor must fail closed");
    check(!Probe.liveLeaderMatches("core_node4", "core_node4", "jetty4", "jetty4",
                                   1, true, false), "inactive leader must fail closed");

    Properties plan = new Properties();
    String prefix = "step.1.";
    plan.setProperty(prefix + "marker", "FAULT:HTTP:parentForwardAdd");
    plan.setProperty(prefix + "siteId", "submit#L309");
    plan.setProperty(prefix + "senderKey", "SOLR/PARENT_LEADER/collection1/shard1");
    plan.setProperty(prefix + "sourceKey",
                     "SOLR/SUBSHARD/collection1/shard1_0/core_node11");
    plan.setProperty(prefix + "resource",
                     "/update/Add/collection1/shard1_0/core_node11");
    plan.setProperty(prefix + "hitOrdinal", "16");
    check(Probe.exactPointMatches(plan, prefix, "FAULT:HTTP:parentForwardAdd",
                                  "submit#L309",
                                  "SOLR/SUBSHARD/collection1/shard1_0/core_node11",
                                  "SOLR/PARENT_LEADER/collection1/shard1",
                                  "/update/Add/collection1/shard1_0/core_node11", 16),
          "exact child request should match");
    check(!Probe.exactPointMatches(plan, prefix, "FAULT:HTTP:parentForwardAdd",
                                   "submit#L309",
                                   "SOLR/SUBSHARD/collection1/shard1_1/core_node12",
                                   "SOLR/PARENT_LEADER/collection1/shard1",
                                   "/update/Add/collection1/shard1_1/core_node12", 16),
          "wrong child replica must not consume plan");
    check(!Probe.exactPointMatches(plan, prefix, "FAULT:HTTP:parentForwardDeleteById",
                                   "submit#L309",
                                   "SOLR/SUBSHARD/collection1/shard1_0/core_node11",
                                   "SOLR/PARENT_LEADER/collection1/shard1",
                                   "/update/DeleteById/collection1/shard1_0/core_node11", 16),
          "wrong command must not consume plan");
    System.out.println("role identity smoke: wrong leader/node/child/command rejected");
  }
}
