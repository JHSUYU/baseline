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

import org.apache.lucene.util.LuceneTestCase.Slow;
import org.apache.solr.client.solrj.impl.CloudSolrServer;
import org.apache.solr.client.solrj.impl.HttpSolrServer;
import org.apache.solr.common.cloud.ZkStateReader;

import static org.apache.solr.cloud.CollectionsAPIDistributedZkTest.setClusterProp;

/**
 * Same cluster as {@link ShardSplitTest}, but the cluster runs in the
 * non-legacy ("ZooKeeper is the truth", legacyCloud=false) mode, which is a
 * supported cluster property. SPLITSHARD then fails because the Overseer sends
 * the sub-shard CoreAdmin CREATE without a coreNodeName, which the ad hoc check
 * in CoreAdminHandler.handleCreateAction rejects.
 */
@Slow
public class ShardSplitNonLegacyCloudTest extends ShardSplitTest {

  @Override
  public void doTest() throws Exception {
    waitForThingsToLevelOut(15);

    CloudSolrServer client = createCloudClient(null);
    try {
      // an admin switches the cluster to non-legacy mode (a supported cluster property)
      assertTrue(setClusterProp(client, ZkStateReader.LEGACY_CLOUD, "false"));

      // a plain SPLITSHARD of shard1; this must succeed in a correctly coordinated cluster
      try {
        splitShard(AbstractDistribZkTestBase.DEFAULT_COLLECTION, SHARD1, null, null);
      } catch (HttpSolrServer.RemoteSolrException e) {
        log.error("SPLITSHARD failed in non-legacy mode", e);
        throw new AssertionError("SPLITSHARD failed with legacyCloud=false: the Overseer sent the sub-shard "
            + "CoreAdmin CREATE without coreNodeName and CoreAdminHandler.handleCreateAction rejected it "
            + "(see 'non legacy mode coreNodeName missing' at CoreAdminHandler.java:560 in the log): "
            + e.getMessage(), e);
      }
    } finally {
      setClusterProp(client, ZkStateReader.LEGACY_CLOUD, null);
      client.shutdown();
    }
  }
}
