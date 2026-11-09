package org.apache.solr.cloud;

/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import org.apache.solr.client.solrj.SolrQuery;
import org.apache.solr.client.solrj.impl.CloudSolrServer;
import org.apache.solr.common.SolrInputDocument;
import org.apache.solr.common.cloud.ZkNodeProps;
import org.apache.solr.common.cloud.ZkStateReader;

import java.io.PrintWriter;
import java.io.StringWriter;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.apache.solr.cloud.OverseerCollectionProcessor.MAX_SHARDS_PER_NODE;
import static org.apache.solr.cloud.OverseerCollectionProcessor.NUM_SLICES;
import static org.apache.solr.cloud.OverseerCollectionProcessor.REPLICATION_FACTOR;

/**
 * Same setup as {@link MigrateRouteKeyTest}, but the cluster is switched to the
 * non-legacy ("ZK is the truth", legacyCloud=false) mode via the CLUSTERPROP API
 * before the MIGRATE call. MIGRATE then fails because the Overseer asks the target
 * leader node to CREATE the temporary collection's second replica without a
 * coreNodeName (and without registering it in clusterstate first), which the
 * ad hoc check in CoreAdminHandler.handleCreateAction rejects.
 */
public class MigrateRouteKeyNonLegacyTest extends MigrateRouteKeyTest {

  @Override
  public void doTest() throws Exception {
    waitForThingsToLevelOut(15);

    CloudSolrServer client = createCloudClient(null);
    try {
      assertTrue("cluster property not set",
          CollectionsAPIDistributedZkTest.setClusterProp(client, ZkStateReader.LEGACY_CLOUD, "false"));

      del("*:*");
      commit();
      for (int id = 0; id < 26 * 3; id++) {
        String shardKey = "" + (char) ('a' + (id % 26));
        String key = shardKey;
        if ("a".equals(shardKey)) key += "/1";
        SolrInputDocument doc = new SolrInputDocument();
        doc.addField("id", key + "!" + id);
        doc.addField("n_ti", id);
        cloudClient.add(doc);
      }
      cloudClient.commit();

      String targetCollection = "migrate_nonlegacy_targetCollection";
      HashMap<String, List<Integer>> collectionInfos = new HashMap<>();
      Map<String, Object> props = ZkNodeProps.makeMap(
          REPLICATION_FACTOR, 1,
          MAX_SHARDS_PER_NODE, 5,
          NUM_SLICES, 1);
      createCollection(collectionInfos, targetCollection, props, client);
      checkForCollection(targetCollection, collectionInfos.get(targetCollection), null);
      waitForRecoveriesToFinish(targetCollection, false);

      Exception failure = null;
      try {
        invokeMigrateApi(AbstractDistribZkTestBase.DEFAULT_COLLECTION, "a/1!", targetCollection);
      } catch (Exception e) {
        failure = e;
      }
      assertNotNull("MIGRATE unexpectedly succeeded in legacyCloud=false mode", failure);
      StringWriter sw = new StringWriter();
      failure.printStackTrace(new PrintWriter(sw));
      log.error("MIGRATE failed in legacyCloud=false mode:\n" + sw);
      String msg = String.valueOf(failure.getMessage()) + sw;
      assertTrue("Unexpected failure: " + msg, msg.contains("MIGRATE failed to create replica of temporary collection in target leader node"));
      // The target node rejected the CREATE at CoreAdminHandler.handleCreateAction (see the
      // "non legacy mode coreNodeName missing" stack trace in the node log); rethrow so the test fails.
      throw failure;
    } finally {
      CollectionsAPIDistributedZkTest.setClusterProp(client, ZkStateReader.LEGACY_CLOUD, null);
      client.shutdown();
    }
  }
}
