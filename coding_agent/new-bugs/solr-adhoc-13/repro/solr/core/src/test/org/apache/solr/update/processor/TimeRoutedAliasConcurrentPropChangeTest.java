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

package org.apache.solr.update.processor;

import java.lang.invoke.MethodHandles;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import org.apache.solr.client.solrj.impl.CloudSolrClient;
import org.apache.solr.client.solrj.request.CollectionAdminRequest;
import org.apache.solr.client.solrj.response.UpdateResponse;
import org.apache.solr.cloud.api.collections.TimeRoutedAlias;
import org.apache.solr.common.SolrInputDocument;
import org.apache.solr.common.util.ExecutorUtil;
import org.apache.solr.util.TestInjection;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import static org.apache.solr.client.solrj.RoutedAliasTypes.TIME;

/**
 * Reproduces a failure of the ad hoc check in RoutedAlias.doSynchronous ("After we attempted to create X it did
 * not exist") caused by a concurrent, legal ALIASPROP change of {@code router.interval} while an update batch
 * is being processed.
 *
 * The RoutedAliasUpdateProcessor builds its TimeRoutedAlias (interval, tz, ...) once per request, from the
 * node's alias properties at request start, and never refreshes it (contrary to the ref guide which states that
 * RAUP checks for changes to TRA properties as it sees each document). The Overseer's MaintainRoutedAliasCmd,
 * however, builds the TimeRoutedAlias from the *current* alias properties. The requester asks the Overseer to
 * create the collection computed with the old interval; the Overseer computes "the next collection" with the new
 * interval, creates a different collection and returns successfully; the requester then does not find its
 * target in the alias and throws.
 */
public class TimeRoutedAliasConcurrentPropChangeTest extends RoutedAliasUpdateProcessorTest {
  private static final Logger log = LoggerFactory.getLogger(MethodHandles.lookup().lookupClass());

  private static final String alias = "myalias";
  private static final String timeField = "timestamp_dt";
  private static final String TRA = TIME.getSeparatorPrefix();

  private CloudSolrClient solrClient;

  @Before
  public void doBefore() throws Exception {
    configureCluster(2).configure();
    solrClient = getCloudSolrClient(cluster);
  }

  @After
  public void doAfter() throws Exception {
    TestInjection.directUpdateLatch = null;
    if (null != solrClient) {
      solrClient.close();
    }
    shutdownCluster();
  }

  @Override
  public String getAlias() {
    return alias;
  }

  @Override
  public CloudSolrClient getSolrClient() {
    return solrClient;
  }

  private static SolrInputDocument doc(String id, String ts) {
    SolrInputDocument d = new SolrInputDocument();
    d.addField("id", id);
    d.addField(timeField, ts);
    return d;
  }

  private static boolean someThreadWaitsInDirectUpdateLatch() {
    for (Map.Entry<Thread, StackTraceElement[]> e : Thread.getAllStackTraces().entrySet()) {
      for (StackTraceElement f : e.getValue()) {
        if ("injectDirectUpdateLatch".equals(f.getMethodName())) {
          return true;
        }
      }
    }
    return false;
  }

  @Test
  public void testIntervalChangeDuringUpdateBatch() throws Exception {
    String configName = getSaferTestName();
    createConfigSet(configName);

    CollectionAdminRequest.createTimeRoutedAlias(alias, "2017-10-23T00:00:00Z", "+1DAY", timeField,
        CollectionAdminRequest.createCollection("_unused_", configName, 1, 1)
            .setMaxShardsPerNode(1))
        .process(solrClient);
    waitColAndAlias(alias, TRA, "2017-10-23", 1);

    // Pause the indexing of the first doc of the batch inside the update handler (after the
    // RoutedAliasUpdateProcessor of this request has been created with interval +1DAY).
    TestInjection.directUpdateLatch = new CountDownLatch(1);

    ExecutorService exec = ExecutorUtil.newMDCAwareCachedThreadPool("TRAConcurrentPropChange");
    Future<UpdateResponse> indexing;
    try {
      indexing = exec.submit(() -> solrClient.add(alias, Arrays.asList(
          doc("1", "2017-10-23T01:00:00Z"),   // goes to the existing 2017-10-23 collection
          doc("2", "2017-10-24T01:00:00Z")))); // requires synchronous creation of the next collection

      long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(30);
      while (!someThreadWaitsInDirectUpdateLatch()) {
        assertTrue("indexing never reached the update handler", System.nanoTime() < deadline);
        Thread.sleep(50);
      }
      log.info("Update batch is in flight; concurrently changing router.interval of {}", alias);

      // Concurrent, legal admin operation: change the TRA interval (documented as editable via ALIASPROP).
      CollectionAdminRequest.setAliasProperty(alias)
          .addProperty(TimeRoutedAlias.ROUTER_INTERVAL, "+1HOUR").process(solrClient);

      // let the batch continue
      TestInjection.directUpdateLatch.countDown();

      Throwable failure = null;
      try {
        UpdateResponse rsp = indexing.get(120, TimeUnit.SECONDS);
        log.info("update response {}", rsp);
      } catch (ExecutionException e) {
        failure = e.getCause();
        log.error("Update batch failed", failure);
      }

      List<String> cols = new CollectionAdminRequest.ListAliases().process(solrClient)
          .getAliasesAsLists().get(alias);
      log.info("Collections of alias {} after the failed batch: {}", alias, cols);

      assertNotNull("expected the update to fail because of the ad hoc check in RoutedAlias.doSynchronous", failure);
      assertTrue("unexpected failure: " + failure, String.valueOf(failure.getMessage())
          .contains("After we attempted to create " + alias + TRA + "2017-10-24 it did not exist"));
      // The Overseer created a collection nobody asked for, and the requested one does not exist.
      assertTrue(cols.toString(), cols.contains(alias + TRA + "2017-10-23_01"));
      assertFalse(cols.toString(), cols.contains(alias + TRA + "2017-10-24"));
    } finally {
      TestInjection.directUpdateLatch = null;
      ExecutorUtil.shutdownAndAwaitTermination(exec);
    }
  }
}
