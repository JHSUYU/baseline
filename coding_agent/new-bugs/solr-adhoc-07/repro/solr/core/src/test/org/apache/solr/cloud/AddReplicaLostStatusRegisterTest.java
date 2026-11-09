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

import javax.servlet.Filter;
import javax.servlet.FilterChain;
import javax.servlet.FilterConfig;
import javax.servlet.ReadListener;
import javax.servlet.ServletException;
import javax.servlet.ServletInputStream;
import javax.servlet.ServletRequest;
import javax.servlet.ServletResponse;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletRequestWrapper;
import javax.servlet.http.HttpServletResponse;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.lang.invoke.MethodHandles;
import java.nio.charset.StandardCharsets;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import java.util.stream.Collectors;

import org.apache.logging.log4j.core.LogEvent;
import org.apache.logging.log4j.core.LoggerContext;
import org.apache.logging.log4j.core.filter.AbstractFilter;
import org.apache.solr.client.solrj.embedded.JettySolrRunner;
import org.apache.solr.client.solrj.request.CollectionAdminRequest;
import org.apache.solr.client.solrj.response.RequestStatusState;
import org.apache.solr.common.SolrException;
import org.apache.solr.common.cloud.DocCollection;
import org.apache.solr.common.cloud.Replica;
import org.apache.solr.common.util.SuppressForbidden;
import org.apache.solr.core.CoreContainer;
import org.apache.solr.core.ZkContainer;
import org.junit.After;
import org.junit.BeforeClass;
import org.junit.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Extends the setup of {@link AddReplicaTest}. An async ADDREPLICA creates a replica on a node; while the new core
 * is still being created/registered on that node, one REQUESTSTATUS poll the Overseer sends to the node fails
 * (a lost / failed HTTP request). The Overseer treats the failed poll as "the core creation failed", finishes the
 * ADDREPLICA as FAILED and releases the collection lock, although the core creation is still running. The client
 * then cleans up the replica of the failed operation with DELETEREPLICA; the core is unloaded while
 * {@link ZkController#register} is still running for it, and register() throws
 * "SolrCore is no longer available to register" (ZkController.java:1326).
 */
@SuppressForbidden(reason = "uses log4j2 classes directly to capture the exception logged by ZkContainer.registerInZk")
public class AddReplicaLostStatusRegisterTest extends SolrCloudTestCase {
  private static final Logger log = LoggerFactory.getLogger(MethodHandles.lookup().lookupClass());

  /** port of the node whose REQUESTSTATUS poll is to be failed; -1 = disarmed */
  static volatile int failPort = -1;
  /** released once the target core reached registration in ZK */
  static volatile CountDownLatch registrationStarted = new CountDownLatch(1);
  static final AtomicBoolean failedOnce = new AtomicBoolean(false);

  /**
   * Fault injection: fails (HTTP 503) the first CoreAdmin REQUESTSTATUS call to the armed node that arrives
   * once the new core is being registered, i.e. a single lost / failed status poll.
   */
  public static class FailRequestStatusFilter implements Filter {
    @Override
    public void init(FilterConfig filterConfig) {}

    @Override
    public void destroy() {}

    @Override
    public void doFilter(ServletRequest request, ServletResponse response, FilterChain chain) throws IOException, ServletException {
      if (failPort > 0 && !failedOnce.get() && request instanceof HttpServletRequest
          && request.getLocalPort() == failPort) {
        HttpServletRequest req = (HttpServletRequest) request;
        if (req.getRequestURI() != null && req.getRequestURI().contains("/admin/cores")) {
          String qs = req.getQueryString() == null ? "" : req.getQueryString();
          byte[] body = readAll(req.getInputStream());
          String all = qs + "&" + new String(body, StandardCharsets.UTF_8);
          if (all.contains("REQUESTSTATUS") && registrationStarted.getCount() == 0 && failedOnce.compareAndSet(false, true)) {
            log.info("FAULT INJECTION: failing REQUESTSTATUS request on port {}: {}", failPort, all);
            ((HttpServletResponse) response).sendError(503, "injected fault: REQUESTSTATUS request lost");
            return;
          }
          chain.doFilter(new BufferedRequest(req, body), response);
          return;
        }
      }
      chain.doFilter(request, response);
    }

    private static byte[] readAll(InputStream in) throws IOException {
      ByteArrayOutputStream out = new ByteArrayOutputStream();
      byte[] buf = new byte[8192];
      int n;
      while ((n = in.read(buf)) != -1) out.write(buf, 0, n);
      return out.toByteArray();
    }
  }

  static class BufferedRequest extends HttpServletRequestWrapper {
    private final byte[] body;

    BufferedRequest(HttpServletRequest req, byte[] body) {
      super(req);
      this.body = body;
    }

    @Override
    public ServletInputStream getInputStream() {
      final ByteArrayInputStream in = new ByteArrayInputStream(body);
      return new ServletInputStream() {
        @Override
        public boolean isFinished() { return in.available() == 0; }
        @Override
        public boolean isReady() { return true; }
        @Override
        public void setReadListener(ReadListener readListener) { throw new UnsupportedOperationException(); }
        @Override
        public int read() { return in.read(); }
        @Override
        public int read(byte[] b, int off, int len) { return in.read(b, off, len); }
      };
    }
  }

  /** captures the exception that ZkContainer.registerInZk logs when ZkController.register throws */
  static class CaptureRegisterFailure extends AbstractFilter {
    final AtomicReference<Throwable> captured = new AtomicReference<>();
    final CountDownLatch latch = new CountDownLatch(1);

    @Override
    public Result filter(LogEvent event) {
      Throwable t = event.getThrown();
      if (t instanceof SolrException && t.getMessage() != null
          && t.getMessage().contains("SolrCore is no longer available to register")) {
        for (StackTraceElement el : t.getStackTrace()) {
          if (el.getClassName().equals(ZkController.class.getName()) && el.getMethodName().equals("register")) {
            if (captured.compareAndSet(null, t)) latch.countDown();
            break;
          }
        }
      }
      return Result.NEUTRAL;
    }
  }

  @BeforeClass
  public static void setupCluster() throws Exception {
    configureCluster(3)
        .addConfig("conf1", TEST_PATH().resolve("configsets").resolve("cloud-minimal").resolve("conf"))
        .withJettyConfig(b -> b.withFilter(FailRequestStatusFilter.class, "/*"))
        .configure();
  }

  @After
  public void cleanup() {
    failPort = -1;
    ZkContainer.testing_beforeRegisterInZk = null;
  }

  @Test
  public void testLostRequestStatusDuringAddReplica() throws Exception {
    String collection = "addReplicaLostStatus";
    CollectionAdminRequest.Create create = CollectionAdminRequest.createCollection(collection, "conf1", 1, 2);
    create.setMaxShardsPerNode(1);
    cluster.getSolrClient().request(create);
    cluster.waitForActiveCollection(collection, 1, 2);

    DocCollection coll = getCollectionState(collection);
    Set<String> usedNodes = coll.getReplicas().stream().map(Replica::getNodeName).collect(Collectors.toSet());
    Set<String> existingCores = coll.getReplicas().stream().map(Replica::getCoreName).collect(Collectors.toSet());
    JettySolrRunner target = cluster.getJettySolrRunners().stream()
        .filter(j -> !usedNodes.contains(j.getNodeName())).findFirst().get();
    final CoreContainer targetCc = target.getCoreContainer();
    log.info("ADDREPLICA to target={}", target.getNodeName());

    CaptureRegisterFailure capture = new CaptureRegisterFailure();
    LoggerContext ctx = LoggerContext.getContext(false);
    ctx.getConfiguration().getRootLogger().addFilter(capture);

    // ordering latch: the new core on the target is registered in ZK only once the client's cleanup has started
    // to unload it, i.e. the core creation is slower than the Overseer's status polling
    AtomicBoolean hookFired = new AtomicBoolean(false);
    ZkContainer.testing_beforeRegisterInZk = cd -> {
      if (cd.getCloudDescriptor() == null || !collection.equals(cd.getCloudDescriptor().getCollectionName())
          || existingCores.contains(cd.getName()) || targetCc.getCoreDescriptor(cd.getName()) != cd
          || !hookFired.compareAndSet(false, true)) {
        return false;
      }
      log.info("Core {} on target reached registerInZk", cd.getName());
      registrationStarted.countDown();
      long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(60);
      while (targetCc.getCoreDescriptor(cd.getName()) != null && System.nanoTime() < deadline) {
        try {
          Thread.sleep(5);
        } catch (InterruptedException e) {
          Thread.currentThread().interrupt();
          return false;
        }
      }
      log.info("Core {} is being unloaded by DELETEREPLICA, continuing with register()", cd.getName());
      return true;
    };
    failPort = target.getLocalPort();

    try {
      RequestStatusState state = CollectionAdminRequest.addReplicaToShard(collection, "shard1")
          .setNode(target.getNodeName())
          .processAndWait("add_lost_status", cluster.getSolrClient(), 120);
      log.info("ADDREPLICA finished with state {}", state);
      assertTrue("the REQUESTSTATUS fault was not injected", failedOnce.get());
      assertEquals(RequestStatusState.FAILED, state);

      // the client cleans up after the failed ADDREPLICA: remove the replica it left on the target node
      DocCollection after = getCollectionState(collection);
      Replica leftover = after.getReplicas().stream()
          .filter(r -> r.getNodeName().equals(target.getNodeName())).findFirst().orElse(null);
      assertNotNull("failed ADDREPLICA left no replica in the cluster state", leftover);
      log.info("Cleaning up replica {} left by the failed ADDREPLICA", leftover);
      CollectionAdminRequest.deleteReplica(collection, "shard1", leftover.getName()).process(cluster.getSolrClient());

      boolean seen = capture.latch.await(60, TimeUnit.SECONDS);
      if (seen) {
        Throwable t = capture.captured.get();
        log.error("ZkController.register failed for the core created by ADDREPLICA", t);
        throw new AssertionError("ad hoc check in ZkController.register failed: the core of a replica whose ADDREPLICA"
            + " was reported FAILED (lost REQUESTSTATUS) was still registering when it was removed", t);
      }
    } finally {
      ctx.getConfiguration().getRootLogger().removeFilter(capture);
      failPort = -1;
      ZkContainer.testing_beforeRegisterInZk = null;
    }
  }
}
