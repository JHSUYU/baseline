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
package org.apache.solr.cloud.api.collections;

import java.io.IOException;
import java.lang.invoke.MethodHandles;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import org.apache.commons.io.FileUtils;
import org.apache.solr.SolrTestCaseJ4.SuppressSSL;
import org.apache.solr.client.solrj.SolrClient;
import org.apache.solr.client.solrj.embedded.JettySolrRunner;
import org.apache.solr.client.solrj.impl.HttpSolrClient;
import org.apache.solr.client.solrj.request.CollectionAdminRequest;
import org.apache.solr.client.solrj.request.CoreAdminRequest;
import org.apache.solr.cloud.SolrCloudTestCase;
import org.apache.solr.common.cloud.DocCollection;
import org.apache.solr.common.cloud.Replica;
import org.apache.solr.common.util.ExecutorUtil;
import org.apache.solr.common.util.SolrNamedThreadFactory;
import org.apache.solr.core.SolrCore;
import org.apache.solr.handler.component.ResponseBuilder;
import org.apache.solr.handler.component.SearchComponent;
import org.apache.solr.util.plugin.SolrCoreAware;
import org.junit.BeforeClass;
import org.junit.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * A core RELOAD (core admin API) racing with a DELETEREPLICA of the same replica.
 * The reload builds the new SolrCore (slow plugin initialisation is simulated by a
 * SearchComponent that waits on a latch in inform()), meanwhile DELETEREPLICA unloads
 * the old core and removes the replica from the cluster state. When the reload resumes it
 * reads the collection state, the replica is gone and the assert in
 * CoreContainer.reload(String, UUID) fails.
 */
@SuppressSSL(bugUrl = "https://issues.apache.org/jira/browse/SOLR-5776")
public class CollectionReloadDeleteReplicaRaceTest extends SolrCloudTestCase {

  private static final Logger log = LoggerFactory.getLogger(MethodHandles.lookup().lookupClass());

  /** set by the test when the next reload should be held */
  static volatile boolean blockReload = false;
  static volatile CountDownLatch reloadReached = new CountDownLatch(1);
  static volatile CountDownLatch releaseReload = new CountDownLatch(1);

  /** A component with (simulated) slow initialisation, e.g. loading a big model/dictionary. */
  public static class SlowInitComponent extends SearchComponent implements SolrCoreAware {
    @Override
    public void inform(SolrCore core) {
      if (blockReload && core.isReloaded()) {
        log.info("SlowInitComponent: reload of {} is initialising, holding it", core.getName());
        reloadReached.countDown();
        try {
          releaseReload.await(60, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
          Thread.currentThread().interrupt();
        }
        log.info("SlowInitComponent: reload of {} continues", core.getName());
      }
    }

    @Override
    public void prepare(ResponseBuilder rb) throws IOException {
    }

    @Override
    public void process(ResponseBuilder rb) throws IOException {
    }

    @Override
    public String getDescription() {
      return "slow init component";
    }
  }

  @BeforeClass
  public static void setupCluster() throws Exception {
    Path conf = createTempDir("slowconf");
    FileUtils.copyDirectory(configset("cloud-minimal").toFile(), conf.toFile());
    Path solrconfig = conf.resolve("solrconfig.xml");
    String xml = new String(Files.readAllBytes(solrconfig), StandardCharsets.UTF_8);
    xml = xml.replace("</config>",
        "  <searchComponent name=\"slowInit\" class=\"" + SlowInitComponent.class.getName() + "\"/>\n</config>");
    Files.write(solrconfig, xml.getBytes(StandardCharsets.UTF_8));

    configureCluster(2)
        .addConfig("conf", conf)
        .configure();
  }

  @Test
  public void testCoreReloadRacingWithDeleteReplica() throws Exception {
    final String collection = "c8n_1x2";
    CollectionAdminRequest.createCollection(collection, "conf", 1, 2)
        .process(cluster.getSolrClient());
    cluster.waitForActiveCollection(collection, 1, 2);

    // pick a non-leader replica to delete
    Replica leader = cluster.getSolrClient().getZkStateReader().getLeaderRetry(collection, "shard1", DEFAULT_TIMEOUT);
    DocCollection coll = getCollectionState(collection);
    Replica victim = null;
    for (Replica r : coll.getReplicas()) {
      if (!r.getName().equals(leader.getName())) victim = r;
    }
    assertNotNull(victim);
    final Replica target = victim;
    JettySolrRunner jetty = cluster.getReplicaJetty(target);
    log.info("Reloading core {} on {} while deleting replica {}", target.getCoreName(), jetty.getNodeName(), target.getName());

    ExecutorService executor = ExecutorUtil.newMDCAwareCachedThreadPool(new SolrNamedThreadFactory("reloadRace"));
    try {
      blockReload = true;
      // 1. core admin RELOAD of the replica's core (e.g. issued by an operator / tool)
      Future<Throwable> reloadFuture = executor.submit(() -> {
        try (SolrClient client = new HttpSolrClient.Builder(jetty.getBaseUrl().toString()).build()) {
          CoreAdminRequest.reloadCore(target.getCoreName(), client);
          return null;
        } catch (Throwable t) {
          return t;
        }
      });
      assertTrue("reload did not start", reloadReached.await(60, TimeUnit.SECONDS));
      blockReload = false;

      // 2. while the new core is being initialised, the replica is deleted
      CollectionAdminRequest.deleteReplica(collection, "shard1", target.getName())
          .process(cluster.getSolrClient());
      waitForState("replica not removed", collection, (n, c) -> c != null && c.getReplica(target.getName()) == null);
      // make sure the node that does the reload has seen the new state
      jetty.getCoreContainer().getZkController().getZkStateReader().waitForState(collection, 30, TimeUnit.SECONDS,
          (n, c) -> c != null && c.getReplica(target.getName()) == null);

      // 3. the reload finishes initialising the new core
      releaseReload.countDown();
      Throwable t = reloadFuture.get(120, TimeUnit.SECONDS);
      if (t != null) {
        log.error("RELOAD failed", t);
        assertFalse("reload failed with AssertionError in CoreContainer.reload: " + t.getMessage(),
            String.valueOf(t.getMessage()).contains("java.lang.AssertionError"));
      }
    } finally {
      releaseReload.countDown();
      ExecutorUtil.shutdownAndAwaitTermination(executor);
    }
  }
}
