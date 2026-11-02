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
package org.apache.solr.handler;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import org.apache.lucene.util.LuceneTestCase;
import org.apache.solr.client.solrj.SolrQuery;
import org.apache.solr.client.solrj.impl.CloudSolrClient;
import org.apache.solr.client.solrj.impl.HttpSolrClient;
import org.apache.solr.client.solrj.request.CollectionAdminRequest;
import org.apache.solr.client.solrj.request.QueryRequest;
import org.apache.solr.cloud.SolrCloudTestCase;
import org.apache.solr.common.SolrInputDocument;
import org.apache.solr.common.cloud.Replica;
import org.apache.solr.common.params.ModifiableSolrParams;
import org.apache.solr.common.util.TimeSource;
import org.apache.solr.util.TimeOut;
import org.junit.BeforeClass;
import org.junit.Test;

/**
 * A PULL replica fetches the leader's index while the leader indexes and commits.
 *
 * <p>Two nodes, configset {@code adhoc-workload-22}. A collection with one shard and its NRT
 * leader on node 0; a PULL replica added on node 1, whose periodic replication is stopped. The
 * leader indexes 20 documents and commits. The PULL replica is told to fetch the leader's index
 * ({@code /replication?command=fetchindex}), with {@link IndexFetcher#testWait} holding the fetch
 * (up to 60 s). Once the fetch is held, the leader indexes 20 more documents and commits; then the
 * fetch resumes. The test waits up to 60 s for the PULL replica to hold the first 20 documents.</p>
 */
@LuceneTestCase.Slow
public class TestAdhocWorkload22 extends SolrCloudTestCase {
  private static final String COLLECTION = "adhocWorkload22";
  private static final int COMMITS = 1;
  private static final int DOCS_PER_COMMIT = 20;

  @BeforeClass
  public static void setupCluster() throws Exception {
    configureCluster(2)
        .addConfig("conf", configset("adhoc-workload-22"))
        .configure();
  }

  @Test
  public void run() throws Exception {
    CloudSolrClient client = cluster.getSolrClient();
    // The leader alone on the first node, the PULL replica added on the other one.
    CollectionAdminRequest.createCollection(COLLECTION, "conf", 1, 1)
        .setCreateNodeSet(cluster.getJettySolrRunner(0).getNodeName())
        .process(client);
    cluster.waitForActiveCollection(COLLECTION, 1, 1);
    CollectionAdminRequest.addReplicaToShard(COLLECTION, "shard1", Replica.Type.PULL)
        .setNode(cluster.getJettySolrRunner(1).getNodeName()).process(client);
    cluster.waitForActiveCollection(COLLECTION, 1, 2);
    Replica leader = getCollectionState(COLLECTION).getSlice("shard1").getLeader();
    Replica pull = getCollectionState(COLLECTION).getSlice("shard1")
        .getReplicas(r -> r.getType() == Replica.Type.PULL).get(0);
    // The PULL replica fetches only when this test asks it to: its periodic replication is stopped.
    cluster.getJettySolrRunner(1).getCoreContainer().getZkController()
        .stopReplicationFromLeader(pull.getCoreName());
    String leaderUrl = leader.getCoreUrl().replaceAll("/+$", "");

    try (HttpSolrClient follower = getHttpSolrClient(pull.getCoreUrl())) {
      int id = 0;
      for (int commit = 0; commit < COMMITS; commit++) {
        id = index(client, id);
        client.commit(COLLECTION);
      }
      final int firstDocs = id;

      CountDownLatch held = new CountDownLatch(1);
      CountDownLatch resume = new CountDownLatch(1);
      IndexFetcher.testWait = () -> {
        held.countDown();
        try {
          resume.await(60, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
          Thread.currentThread().interrupt();
        }
        return true;
      };
      try {
        replication(follower, "fetchindex", leaderUrl);
        assertTrue("the follower's fetch was held", held.await(60, TimeUnit.SECONDS));
        // The leader indexes and commits again while the fetch is held.
        index(client, id);
        client.commit(COLLECTION);
      } finally {
        IndexFetcher.testWait = () -> true;
        resume.countDown();
      }

      SolrQuery all = new SolrQuery("*:*");
      all.set("distrib", false);
      TimeOut fetched = new TimeOut(60, TimeUnit.SECONDS, TimeSource.NANO_TIME);
      long found = -1;
      while (!fetched.hasTimedOut()) {
        found = follower.query(all).getResults().getNumFound();
        if (found == firstDocs) break;
        Thread.sleep(200);
      }
      assertEquals("the follower holds the first commit's documents", firstDocs, found);
    }
  }

  private static int index(CloudSolrClient client, int id) throws Exception {
    List<SolrInputDocument> docs = new ArrayList<>(DOCS_PER_COMMIT);
    for (int doc = 0; doc < DOCS_PER_COMMIT; doc++) {
      docs.add(new SolrInputDocument("id", Integer.toString(id++)));
    }
    client.add(COLLECTION, docs);
    return id;
  }

  private static void replication(HttpSolrClient core, String command, String leaderUrl)
      throws Exception {
    ModifiableSolrParams params = new ModifiableSolrParams();
    params.set("command", command);
    params.set(ReplicationHandler.LEADER_URL, leaderUrl);
    QueryRequest request = new QueryRequest(params);
    request.setPath("/replication");
    request.process(core);
  }
}
