package org.apache.solr.cloud;

/*
 * Specula MC-1 reproduction (solr-adhoc-k3), Level 0: public APIs only.
 *
 * Variant of MigrateRouteKeyTest (same module, same base class and setup).
 * The single difference: before the target collection is created, the cluster is
 * switched to legacyCloud=false through the public CLUSTERPROP Collections API,
 * exactly as ShardSplitTest / CollectionsAPIDistributedZkTest do.  Then the
 * workload's MIGRATE (split.key=a/1!) is invoked unchanged.
 *
 * Expected (buggy) outcome: the Overseer's migrateKey sends a CoreAdmin CREATE for
 * split_shard1_temp_shard1_shard1_replica2 without coreNodeName; the target
 * node's CoreAdminHandler.handleCreateAction throws
 * SolrException("non legacy mode coreNodeName missing ...") at line 563 and MIGRATE fails.
 * The test then prints the state left behind: the routing rule on the source slice,
 * the temp collection, and the target leader's UpdateLog state.
 *
 * Copy to solr/core/src/test/org/apache/solr/cloud/SpeculaReproMC1MigrateRouteKeyTest.java
 */

import org.apache.solr.client.solrj.SolrQuery;
import org.apache.solr.client.solrj.embedded.JettySolrRunner;
import org.apache.solr.client.solrj.impl.CloudSolrServer;
import org.apache.solr.client.solrj.impl.HttpSolrServer;
import org.apache.solr.common.SolrInputDocument;
import org.apache.solr.common.cloud.ClusterState;
import org.apache.solr.common.cloud.Replica;
import org.apache.solr.common.cloud.RoutingRule;
import org.apache.solr.common.cloud.Slice;
import org.apache.solr.common.cloud.ZkNodeProps;
import org.apache.solr.common.cloud.ZkStateReader;
import org.apache.solr.core.CoreContainer;
import org.apache.solr.core.SolrCore;
import org.apache.solr.servlet.SolrDispatchFilter;
import org.apache.solr.update.UpdateLog;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.apache.solr.cloud.OverseerCollectionProcessor.MAX_SHARDS_PER_NODE;
import static org.apache.solr.cloud.OverseerCollectionProcessor.NUM_SLICES;
import static org.apache.solr.cloud.OverseerCollectionProcessor.REPLICATION_FACTOR;

public class SpeculaReproMC1MigrateRouteKeyTest extends MigrateRouteKeyTest {

  private static void p(String s) { System.out.println("[MC-1] " + s); System.out.flush(); }

  @Override
  public void doTest() throws Exception {
    waitForThingsToLevelOut(15);

    // The only deviation from the workload: the supported CLUSTERPROP API.
    // Control run (-Dmc1.control=true): skip it, i.e. the original workload (legacy mode).
    final boolean control = Boolean.getBoolean("mc1.control");
    p("mode = " + (control ? "CONTROL (legacyCloud unset)" : "BUG (legacyCloud=false)"));
    if (!control) {
      CollectionsAPIDistributedZkTest.setClusterProp(cloudClient, ZkStateReader.LEGACY_CLOUD, "false");
    }
    p("clusterProps after CLUSTERPROP = " + cloudClient.getZkStateReader().getClusterProps());

    // ---- same as MigrateRouteKeyTest.multipleShardMigrateTest up to invokeMigrateApi ----
    del("*:*");
    commit();
    final String splitKey = "a";
    final int BIT_SEP = 1;
    for (int id = 0; id < 26 * 3; id++) {
      String shardKey = "" + (char) ('a' + (id % 26));
      String key = shardKey;
      if (splitKey.equals(shardKey)) key += "/" + BIT_SEP;
      SolrInputDocument doc = new SolrInputDocument();
      doc.addField("id", key + "!" + id);
      doc.addField("n_ti", id);
      cloudClient.add(doc);
    }
    commit();

    String targetCollection = "migrate_multipleshardtest_targetCollection";
    HashMap<String, List<Integer>> collectionInfos = new HashMap<>();
    CloudSolrServer client = createCloudClient(null);
    try {
      Map<String, Object> props = ZkNodeProps.makeMap(REPLICATION_FACTOR, 1, MAX_SHARDS_PER_NODE, 5, NUM_SLICES, 1);
      createCollection(collectionInfos, targetCollection, props, client);
    } finally {
      client.shutdown();
    }
    checkForCollection(targetCollection, collectionInfos.get(targetCollection), null);
    waitForRecoveriesToFinish(targetCollection, false);
    p("target collection created OK (createCollection passes coreNodeName in non-legacy mode)");

    Throwable migrateError = null;
    try {
      invokeMigrateApi(AbstractDistribZkTestBase.DEFAULT_COLLECTION, splitKey + "/" + BIT_SEP + "!", targetCollection);
    } catch (Throwable t) {
      migrateError = t;
    }
    p("MIGRATE result: " + (migrateError == null ? "SUCCESS" : "FAILED: " + migrateError));

    // ---- observe what MIGRATE left behind ----
    ZkStateReader zkr = cloudClient.getZkStateReader();
    zkr.updateClusterState(true);
    ClusterState cs = zkr.getClusterState();
    p("collections after MIGRATE: " + cs.getCollections());
    for (Slice s : cs.getSlices(AbstractDistribZkTestBase.DEFAULT_COLLECTION)) {
      Map<String, RoutingRule> rr = s.getRoutingRules();
      p("source " + s.getName() + " routingRules=" + (rr == null ? null : rr.keySet()));
    }
    Replica tl = zkr.getLeaderRetry(targetCollection, "shard1", 10000);
    String tlCore = tl.getStr(ZkStateReader.CORE_NAME_PROP);
    List<JettySolrRunner> all = new java.util.ArrayList<>(jettys);
    if (controlJetty != null) all.add(controlJetty);
    for (JettySolrRunner j : all) {
      CoreContainer cc = ((SolrDispatchFilter) j.getDispatchFilter().getFilter()).getCores();
      SolrCore core = cc.getCore(tlCore);
      if (core == null) continue;
      try {
        UpdateLog ulog = core.getUpdateHandler().getUpdateLog();
        p("target leader core " + tlCore + " on " + tl.getNodeName() + " UpdateLog state=" + ulog.getState());
      } finally {
        core.close();
      }
    }
    String url = CustomCollectionTest.getUrlFromZk(cs, targetCollection);
    HttpSolrServer collectionClient = new HttpSolrServer(url);
    p("target numFound(*:*) = " + collectionClient.query(new SolrQuery("*:*")).getResults().getNumFound());
    collectionClient.shutdown();

    if (control) {
      assertNull("control: MIGRATE should succeed in legacy mode", migrateError);
      p("CONTROL OK: MIGRATE succeeded in legacy mode");
      return;
    }
    // The client sees OCP's wrapper message (OCP:1904-1906); the root cause is the node-side
    // SolrException thrown at CoreAdminHandler.java:563 (see the server log in the captured output).
    assertNotNull("MC-1: expected MIGRATE to fail under legacyCloud=false", migrateError);
    assertTrue("MC-1: unexpected MIGRATE error: " + migrateError, String.valueOf(migrateError.getMessage())
        .contains("MIGRATE failed to create replica of temporary collection in target leader node."));
    p("BUG REPRODUCED: MIGRATE aborted at the temp replica2 CREATE (root cause: CoreAdminHandler.java:563)");

    // Persistence: wait past forward.timeout (45s) and look again.
    Thread.sleep(60000);
    zkr.updateClusterState(true);
    cs = zkr.getClusterState();
    p("after 60s: collections = " + cs.getCollections());
    for (Slice s : cs.getSlices(AbstractDistribZkTestBase.DEFAULT_COLLECTION)) {
      Map<String, RoutingRule> rr = s.getRoutingRules();
      p("after 60s: source " + s.getName() + " routingRules=" + (rr == null ? null : rr.keySet()));
    }
    for (JettySolrRunner j : all) {
      CoreContainer cc = ((SolrDispatchFilter) j.getDispatchFilter().getFilter()).getCores();
      SolrCore core = cc.getCore(tlCore);
      if (core == null) continue;
      try {
        p("after 60s: target leader core " + tlCore + " UpdateLog state=" + core.getUpdateHandler().getUpdateLog().getState());
      } finally {
        core.close();
      }
    }

    CollectionsAPIDistributedZkTest.setClusterProp(cloudClient, ZkStateReader.LEGACY_CLOUD, null);
  }
}
