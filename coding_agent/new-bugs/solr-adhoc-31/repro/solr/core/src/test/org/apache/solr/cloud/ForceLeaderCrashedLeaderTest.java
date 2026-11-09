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
package org.apache.solr.cloud;

import java.lang.invoke.MethodHandles;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.TimeUnit;

import com.carrotsearch.randomizedtesting.annotations.Nightly;
import org.apache.solr.client.solrj.cloud.SocketProxy;
import org.apache.solr.client.solrj.embedded.JettySolrRunner;
import org.apache.solr.client.solrj.impl.CloudSolrClient;
import org.apache.solr.client.solrj.request.CollectionAdminRequest;
import org.apache.solr.common.SolrInputDocument;
import org.apache.solr.common.cloud.ClusterState;
import org.apache.solr.common.cloud.Replica;
import org.apache.solr.common.cloud.Replica.State;
import org.apache.solr.common.cloud.Slice;
import org.apache.solr.common.cloud.SolrZkClient;
import org.apache.solr.common.util.TimeSource;
import org.apache.solr.util.TimeOut;
import org.junit.AfterClass;
import org.junit.BeforeClass;
import org.junit.Ignore;
import org.junit.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Same setup as {@link ForceLeaderTest#testReplicasInLowerTerms()} (the non-leader replicas end up in a
 * lower term than the leader), but the leader node <em>crashes</em> instead of being shut down gracefully,
 * i.e. its ZooKeeper session goes away without the node publishing its replicas as DOWN.
 * <p>
 * For a collection with {@code perReplicaState=true} the crashed leader's per-replica state entry stays
 * {@code active + leader} forever: the "clear leader" message sent by the next election candidate
 * ({@link ShardLeaderElectionContext#runLeaderProcess}) is a no-op for PRS collections
 * ({@code SliceMutator.setShardLeader} only touches state.json, the PRS entries are only "touched").
 * Hence FORCELEADER, run while the shard is leaderless (the lower-term replicas wait leaderVoteWait), fails with
 * "The shard already has an active leader" although that leader's node is not live.
 * {@link #testForceLeaderAfterLeaderCrash()} is the same scenario with a regular collection, where the check passes.
 */
@Nightly
public class ForceLeaderCrashedLeaderTest extends HttpPartitionTest {
  private static final Logger log = LoggerFactory.getLogger(MethodHandles.lookup().lookupClass());

  @BeforeClass
  public static void beforeClassSetup() {
    System.setProperty("socketTimeout", "15000");
    System.setProperty("distribUpdateSoTimeout", "15000");
    System.setProperty("solr.httpclient.retries", "0");
    System.setProperty("solr.retries.on.forward", "0");
    System.setProperty("solr.retries.to.followers", "0");
    // production default of leaderVoteWait (CloudConfig.DEFAULT_LEADER_VOTE_WAIT); tests use 15s by default
    System.setProperty("leaderVoteWait", "180000");
  }

  @AfterClass
  public static void afterClassCleanup() {
    System.clearProperty("leaderVoteWait");
  }

  @Test
  @Override
  @Ignore
  public void test() throws Exception {
  }

  @Test
  @Slow
  public void testForceLeaderAfterLeaderCrashPerReplicaState() throws Exception {
    runScenario(true);
  }

  @Test
  @Slow
  public void testForceLeaderAfterLeaderCrash() throws Exception {
    runScenario(false);
  }

  private void runScenario(boolean perReplicaState) throws Exception {
    handle.put("maxScore", SKIPVAL);
    handle.put("timestamp", SKIPVAL);

    String coll = "forceleader_crashed_leader_" + (perReplicaState ? "prs" : "plain");
    CollectionAdminRequest.createCollection(coll, "conf1", 1, 3)
        .setMaxShardsPerNode(1)
        .setPerReplicaState(perReplicaState)
        .process(cloudClient);
    cloudClient.setDefaultCollection(coll);

    try {
      List<Replica> notLeaders = ensureAllReplicasAreActive(coll, SHARD1, 1, 3, maxWaitSecsToSeeAllActive);
      assertEquals(2, notLeaders.size());
      Replica leader = cloudClient.getZkStateReader().getLeaderRetry(coll, SHARD1);
      JettySolrRunner leaderJetty = getJettyOnPort(getReplicaPort(leader));

      // 1. doc 1 is indexed on all replicas
      sendDoc(1);

      // 2. HTTP partition between the leader and both followers
      SocketProxy[] nonLeaderProxies = new SocketProxy[notLeaders.size()];
      for (int i = 0; i < notLeaders.size(); i++) {
        nonLeaderProxies[i] = getProxyForReplica(notLeaders.get(i));
        nonLeaderProxies[i].close();
      }
      SocketProxy leaderProxy = getProxyForReplica(leader);
      leaderProxy.close();

      // 3. doc 2 is accepted by the leader only; the followers are put into a lower term and go DOWN
      sendDoc(2, null, leaderJetty);
      for (Replica replica : notLeaders) {
        waitForState(coll, replica.getName(), State.DOWN, 60000);
      }

      // 4. the leader node crashes: its ZK session disappears (live node + election node are removed)
      //    without the node getting the chance to publish its replicas as DOWN
      log.info("Crashing leader {} on node {}", leader.getName(), leader.getNodeName());
      SolrZkClient leaderZk = leaderJetty.getCoreContainer().getZkController().getZkClient();
      leaderZk.close();
      leaderJetty.stop();

      // 5. the partition heals, the followers are live but in a lower term
      for (SocketProxy proxy : nonLeaderProxies) proxy.reopen();

      // wait until the cluster has noticed the crash and the remaining replicas started an election
      TimeOut liveTimeout = new TimeOut(60, TimeUnit.SECONDS, TimeSource.NANO_TIME);
      while (cloudClient.getZkStateReader().getClusterState().getLiveNodes().contains(leader.getNodeName())) {
        assertFalse("crashed node still live", liveTimeout.hasTimedOut());
        Thread.sleep(200);
      }
      Thread.sleep(10000);

      cloudClient.getZkStateReader().forceUpdateCollection(coll);
      ClusterState clusterState = cloudClient.getZkStateReader().getClusterState();
      Slice slice = clusterState.getCollection(coll).getSlice(SHARD1);
      log.info("Before forcing leader: live nodes {} slice {}", clusterState.getLiveNodes(), slice);
      assertFalse("crashed leader node must not be live", clusterState.getLiveNodes().contains(leader.getNodeName()));
      Replica stateLeader = slice.getLeader();
      log.info("Leader according to cluster state: {} state={} nodeLive={} perReplicaStates={}",
          stateLeader == null ? null : stateLeader.getName(),
          stateLeader == null ? null : stateLeader.getState(),
          stateLeader == null ? null : clusterState.getLiveNodes().contains(stateLeader.getNodeName()),
          clusterState.getCollection(coll).getPerReplicaStates());

      // no replica on a live node is the leader: the shard is leaderless and cannot accept updates
      assertTrue("expected no leader on a live node, leader: " + stateLeader,
          stateLeader == null || !clusterState.getLiveNodes().contains(stateLeader.getNodeName()));

      // 6. the operator does what FORCELEADER is documented for: a leaderless shard
      log.info("Do force leader...");
      CollectionAdminRequest.ForceLeader forceLeader = CollectionAdminRequest.forceLeaderElection(coll, SHARD1);
      try (CloudSolrClient client = getCloudSolrClient(zkServer.getZkAddress(), random().nextBoolean(), 30000, 60000)) {
        client.request(forceLeader);
      }

      // (expected: the request is accepted; in a per-replica-state collection it is rejected by the
      //  "already has an active leader" check in CollectionsHandler.forceLeaderElection, see class javadoc)
    } finally {
      attemptCollectionDelete(cloudClient, coll);
    }
  }

  @Override
  protected int sendDoc(int docId) throws Exception {
    SolrInputDocument doc = new SolrInputDocument();
    doc.addField(id, String.valueOf(docId));
    doc.addField("a_t", "hello" + docId);
    return sendDocsWithRetry(Collections.singletonList(doc), 1, 5, 1);
  }
}
