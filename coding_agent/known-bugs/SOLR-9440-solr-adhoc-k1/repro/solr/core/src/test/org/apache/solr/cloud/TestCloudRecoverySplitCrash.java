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
import java.util.concurrent.TimeUnit;

import org.apache.solr.client.solrj.embedded.JettySolrRunner;
import org.apache.solr.client.solrj.impl.CloudSolrClient;
import org.apache.solr.client.solrj.request.CollectionAdminRequest;
import org.apache.solr.client.solrj.response.RequestStatusState;
import org.apache.solr.common.cloud.DocCollection;
import org.apache.solr.common.cloud.Replica;
import org.apache.solr.common.cloud.Slice;
import org.apache.solr.common.cloud.ZkStateReader;
import org.apache.solr.util.TestInjection;
import org.apache.solr.util.TimeOut;
import org.junit.After;
import org.junit.BeforeClass;
import org.junit.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Same cluster setup as {@link TestCloudRecovery} (2 nodes, cloud-minimal config, tlog kept),
 * but the node hosting the parent shard leader crashes/restarts while a SPLITSHARD is in progress.
 * After the node is back and every replica is live and active, the sub-shards created by the
 * aborted split stay in CONSTRUCTION forever and waitForRecoveriesToFinish fails.
 */
public class TestCloudRecoverySplitCrash extends SolrCloudTestCase {
  private static final Logger log = LoggerFactory.getLogger(MethodHandles.lookup().lookupClass());

  private static final String COLLECTION = "splitcrash";

  @BeforeClass
  public static void setupCluster() throws Exception {
    System.setProperty("solr.directoryFactory", "solr.StandardDirectoryFactory");
    System.setProperty("solr.ulog.numRecordsToKeep", "1000");

    configureCluster(2)
        .addConfig("config", TEST_PATH().resolve("configsets").resolve("cloud-minimal").resolve("conf"))
        .configure();
  }

  @After
  public void resetInjection() {
    TestInjection.reset();
  }

  @Test
  public void parentLeaderNodeRestartDuringSplitTest() throws Exception {
    CloudSolrClient cloudClient = cluster.getSolrClient();
    ZkStateReader zkStateReader = cloudClient.getZkStateReader();

    // place the shard on the node that is NOT the overseer, so that the overseer survives the crash
    // and the SPLITSHARD task is finished (as failed) instead of being re-run by a new overseer
    String overseerNode = OverseerTaskProcessor.getLeaderNode(zkStateReader.getZkClient());
    JettySolrRunner dataNode = null;
    for (JettySolrRunner j : cluster.getJettySolrRunners()) {
      if (!j.getNodeName().equals(overseerNode)) {
        dataNode = j;
      }
    }
    assertNotNull("no non-overseer node found", dataNode);
    log.info("overseer={} dataNode={}", overseerNode, dataNode.getNodeName());

    CollectionAdminRequest.createCollection(COLLECTION, "config", 1, 1)
        .setCreateNodeSet(dataNode.getNodeName())
        .setMaxShardsPerNode(1)
        .process(cloudClient);
    AbstractDistribZkTestBase.waitForRecoveriesToFinish(COLLECTION, zkStateReader, false, true, 30);

    for (int i = 0; i < 20; i++) {
      cloudClient.add(COLLECTION, sdoc("id", String.valueOf(i)));
    }
    cloudClient.commit(COLLECTION);

    // sub-shard core creation is slow (e.g. a busy node); fault-injection hook already used by other cloud tests
    TestInjection.randomDelayInCoreCreation = "true:100";
    TestInjection.randomDelayMaxInCoreCreationInSec = 10;

    // 1. a client asks to split shard1
    String asyncId = CollectionAdminRequest.splitShard(COLLECTION).setShardName("shard1").processAsync(cloudClient);

    // 2. the overseer has created the sub-shard shard1_0 in CONSTRUCTION state
    waitForState("sub-shard shard1_0 never appeared", COLLECTION, (liveNodes, coll) -> {
      Slice s = coll == null ? null : coll.getSlice("shard1_0");
      return s != null && s.getState() == Slice.State.CONSTRUCTION;
    });
    log.info("sub-shard created in CONSTRUCTION; stopping node {} hosting the parent shard leader", dataNode.getNodeName());

    // 3. the node hosting the parent shard leader (and the new sub-shard leaders) goes down
    ChaosMonkey.stop(dataNode);

    // 4. the split fails
    RequestStatusState state = null;
    TimeOut timeOut = new TimeOut(180, TimeUnit.SECONDS);
    while (!timeOut.hasTimedOut()) {
      state = CollectionAdminRequest.requestStatus(asyncId).process(cloudClient).getRequestStatus();
      if (state == RequestStatusState.COMPLETED || state == RequestStatusState.FAILED) break;
      Thread.sleep(500);
    }
    log.info("SPLITSHARD request status: {}", state);
    assertEquals("SPLITSHARD was expected to fail because the parent leader node went down", RequestStatusState.FAILED, state);
    TestInjection.reset();

    // 5. the node comes back; the parent shard leader is live and active again
    ChaosMonkey.start(dataNode);
    waitForState("parent shard1 did not come back", COLLECTION, (liveNodes, coll) -> {
      if (coll == null) return false;
      Slice s = coll.getSlice("shard1");
      if (s == null || s.getState() != Slice.State.ACTIVE) return false;
      Replica leader = s.getLeader();
      return leader != null && leader.getState() == Replica.State.ACTIVE && liveNodes.contains(leader.getNodeName());
    });
    assertEquals(20, cloudClient.query(COLLECTION, params("q", "*:*")).getResults().getNumFound());

    DocCollection coll = zkStateReader.getClusterState().getCollection(COLLECTION);
    for (Slice s : coll.getSlices()) {
      log.info("slice {} state={} replicas={}", s.getName(), s.getState(), s.getReplicas());
    }

    // 6. all nodes are up, nothing is recovering any more -- but the aborted split's sub-shards are never cleaned up
    AbstractDistribZkTestBase.waitForRecoveriesToFinish(COLLECTION, zkStateReader, false, true, 60);
  }
}
