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

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.lang.invoke.MethodHandles;
import java.net.Socket;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.concurrent.TimeUnit;
import java.util.function.Predicate;

import org.apache.solr.SolrTestCaseJ4;
import org.apache.solr.client.solrj.embedded.JettySolrRunner;
import org.apache.solr.client.solrj.impl.CloudSolrClient;
import org.apache.solr.client.solrj.request.CollectionAdminRequest;
import org.apache.solr.common.cloud.Aliases;
import org.apache.solr.common.cloud.DocCollection;
import org.apache.solr.common.cloud.Replica;
import org.apache.solr.util.DateMathParser;
import org.apache.solr.util.TimeOut;
import org.apache.solr.common.util.TimeSource;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import static org.apache.solr.client.solrj.RoutedAliasTypes.TIME;

/**
 * An update request (here: a streaming/chunked JSON update from a slow client) builds its
 * RoutedAlias when the update chain is created. While the body is still arriving, an admin replaces
 * the time routed alias by a plain alias of the same name (DELETEALIAS + CREATEALIAS). The first
 * document then makes TimeRoutedAlias.validateRouteValue "fix" the date-math router.start and write
 * it (asynchronously) onto whatever the alias currently is -- the plain alias -- leaving a plain
 * alias with properties {router.start=...} but no router.name. The next document needs a new
 * collection; MAINTAINROUTEDALIAS then hits the ad hoc check in MaintainRoutedAliasCmd (ra == null).
 */
@SolrTestCaseJ4.SuppressSSL
public class TimeRoutedAliasReplacedByPlainAliasTest extends RoutedAliasUpdateProcessorTest {
  private static final Logger log = LoggerFactory.getLogger(MethodHandles.lookup().lookupClass());

  private static final String alias = "myalias";
  private static final String timeField = "timestamp_dt";
  private CloudSolrClient solrClient;

  @Before
  public void doBefore() throws Exception {
    configureCluster(2).configure();
    solrClient = getCloudSolrClient(cluster);
  }

  @After
  public void doAfter() throws Exception {
    if (null != solrClient) {
      solrClient.close();
    }
    shutdownCluster();
  }

  @Test
  public void testStaleRoutedAliasWritesStartOntoPlainAlias() throws Exception {
    String configName = getSaferTestName();
    createConfigSet(configName);

    // TRA whose start is date math (resolved lazily on the first document), 1 day intervals,
    // allowing docs up to 2 days in the future
    CollectionAdminRequest.createTimeRoutedAlias(alias, "NOW/DAY", "+1DAY", timeField,
        CollectionAdminRequest.createCollection("_unused_", configName, 1, 1))
        .setMaxFutureMs(2 * 24 * 3600 * 1000)
        .process(solrClient);

    final Instant today = DateMathParser.parseMath(new java.util.Date(), "NOW/DAY").toInstant();
    final String firstCol = alias + TIME.getSeparatorPrefix()
        + java.time.format.DateTimeFormatter.ISO_LOCAL_DATE.withZone(java.time.ZoneOffset.UTC).format(today);
    cluster.waitForActiveCollection(firstCol, 1, 1);
    waitAllNodes("routed alias visible", a -> a.isRoutedAlias(alias));
    log.info("Aliases after TRA creation: {}", aliasesOf(cluster.getJettySolrRunner(0)));

    DocCollection coll = cluster.getSolrClient().getZkStateReader().getClusterState().getCollection(firstCol);
    Replica replica = coll.getReplicas().get(0);
    URL baseUrl = new URL(replica.getBaseUrl());

    // 1. a (slow) client starts a streaming update to the TRA's collection; only "[" is sent so far.
    try (Socket socket = new Socket(baseUrl.getHost(), baseUrl.getPort())) {
      socket.setSoTimeout(120_000);
      OutputStream out = socket.getOutputStream();
      String head = "POST " + baseUrl.getPath() + "/" + firstCol + "/update?wt=json HTTP/1.1\r\n"
          + "Host: " + baseUrl.getHost() + ":" + baseUrl.getPort() + "\r\n"
          + "Content-Type: application/json\r\n"
          + "Transfer-Encoding: chunked\r\n"
          + "Connection: close\r\n\r\n";
      out.write(head.getBytes(StandardCharsets.UTF_8));
      out.flush();
      // Jetty dispatches once some content is available: send just the opening of the JSON array
      writeChunk(out, "[");
      // the update chain (and its RoutedAlias, built from the routed alias props) is created
      // before the body is read
      Thread.sleep(3000);

      // 2. meanwhile an admin replaces the routed alias with a plain alias of the same name
      CollectionAdminRequest.deleteAlias(alias).process(solrClient);
      CollectionAdminRequest.createAlias(alias, firstCol).process(solrClient);
      waitAllNodes("plain alias visible", a -> !a.isRoutedAlias(alias)
          && a.getCollectionAliasProperties(alias).isEmpty()
          && a.getCollectionAliasListMap().containsKey(alias));
      log.info("Aliases after replacing with plain alias: {}", aliasesOf(cluster.getJettySolrRunner(0)));

      // 3. the first document arrives (belongs to the existing collection)
      String doc1 = "{\"id\":\"1\",\"" + timeField + "\":\"" + Instant.now() + "\"},";
      writeChunk(out, doc1);
      // the stale RoutedAlias resolves router.start and writes it onto the (now plain) alias
      waitAllNodes("router.start written onto plain alias",
          a -> a.getCollectionAliasProperties(alias).containsKey("router.start"));
      log.info("Aliases after first doc: {}", aliasesOf(cluster.getJettySolrRunner(0)));

      // 4. the second document needs the next (not yet existing) collection -> MAINTAINROUTEDALIAS
      String doc2 = "{\"id\":\"2\",\"" + timeField + "\":\"" + Instant.now().plus(1, ChronoUnit.DAYS) + "\"}]";
      writeChunk(out, doc2);
      out.write("0\r\n\r\n".getBytes(StandardCharsets.UTF_8));
      out.flush();

      String response = readAll(socket.getInputStream());
      log.info("Streaming update response:\n{}", response);
      assertTrue("expected the update to fail in MaintainRoutedAliasCmd: " + response,
          response.contains("MaintainRoutedAlias called on non-routed alias"));
    }
    log.info("Final aliases: {}", aliasesOf(cluster.getJettySolrRunner(0)));
  }

  private static void writeChunk(OutputStream out, String data) throws Exception {
    byte[] bytes = data.getBytes(StandardCharsets.UTF_8);
    out.write((Integer.toHexString(bytes.length) + "\r\n").getBytes(StandardCharsets.UTF_8));
    out.write(bytes);
    out.write("\r\n".getBytes(StandardCharsets.UTF_8));
    out.flush();
  }

  private static String readAll(InputStream in) throws Exception {
    ByteArrayOutputStream bos = new ByteArrayOutputStream();
    byte[] buf = new byte[8192];
    int n;
    while ((n = in.read(buf)) != -1) {
      bos.write(buf, 0, n);
    }
    return new String(bos.toByteArray(), StandardCharsets.UTF_8);
  }

  private static Aliases aliasesOf(JettySolrRunner jetty) {
    return jetty.getCoreContainer().getZkController().getZkStateReader().getAliases();
  }

  private void waitAllNodes(String what, Predicate<Aliases> p) throws Exception {
    TimeOut timeOut = new TimeOut(30, TimeUnit.SECONDS, TimeSource.NANO_TIME);
    while (true) {
      boolean ok = true;
      for (JettySolrRunner jetty : cluster.getJettySolrRunners()) {
        if (!p.test(aliasesOf(jetty))) {
          ok = false;
          break;
        }
      }
      if (ok) return;
      if (timeOut.hasTimedOut()) {
        fail("Timed out waiting for: " + what + "; aliases=" + aliasesOf(cluster.getJettySolrRunner(0)));
      }
      Thread.sleep(100);
    }
  }

  @Override
  public String getAlias() {
    return alias;
  }

  @Override
  public CloudSolrClient getSolrClient() {
    return solrClient;
  }
}
