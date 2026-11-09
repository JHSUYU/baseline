/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.apache.hadoop.hbase.security.token;

import static org.apache.hadoop.fs.CommonConfigurationKeysPublic.HADOOP_SECURITY_AUTHORIZATION;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.security.PrivilegedExceptionAction;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ConcurrentMap;
import java.util.concurrent.ExecutorService;

import org.apache.commons.logging.Log;
import org.apache.commons.logging.LogFactory;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hbase.ChoreService;
import org.apache.hadoop.hbase.ClusterId;
import org.apache.hadoop.hbase.CoordinatedStateManager;
import org.apache.hadoop.hbase.Coprocessor;
import org.apache.hadoop.hbase.HBaseTestingUtility;
import org.apache.hadoop.hbase.HConstants;
import org.apache.hadoop.hbase.HRegionInfo;
import org.apache.hadoop.hbase.Server;
import org.apache.hadoop.hbase.ServerName;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.ClusterConnection;
import org.apache.hadoop.hbase.client.Connection;
import org.apache.hadoop.hbase.client.ConnectionFactory;
import org.apache.hadoop.hbase.client.HTableInterface;
import org.apache.hadoop.hbase.coprocessor.RegionCoprocessorEnvironment;
import org.apache.hadoop.hbase.ipc.BlockingRpcCallback;
import org.apache.hadoop.hbase.ipc.FifoRpcScheduler;
import org.apache.hadoop.hbase.ipc.RpcClient;
import org.apache.hadoop.hbase.ipc.RpcClientFactory;
import org.apache.hadoop.hbase.ipc.RpcServer;
import org.apache.hadoop.hbase.ipc.RpcServer.BlockingServiceAndInterface;
import org.apache.hadoop.hbase.ipc.RpcServerInterface;
import org.apache.hadoop.hbase.ipc.ServerRpcController;
import org.apache.hadoop.hbase.protobuf.generated.AuthenticationProtos;
import org.apache.hadoop.hbase.regionserver.HRegion;
import org.apache.hadoop.hbase.regionserver.RegionServerServices;
import org.apache.hadoop.hbase.security.SecurityInfo;
import org.apache.hadoop.hbase.security.User;
import org.apache.hadoop.hbase.testclassification.MediumTests;
import org.apache.hadoop.hbase.testclassification.SecurityTests;
import org.apache.hadoop.hbase.util.Bytes;
import org.apache.hadoop.hbase.util.EnvironmentEdgeManager;
import org.apache.hadoop.hbase.util.Sleeper;
import org.apache.hadoop.hbase.util.Strings;
import org.apache.hadoop.hbase.util.Threads;
import org.apache.hadoop.hbase.util.Writables;
import org.apache.hadoop.hbase.zookeeper.MetaTableLocator;
import org.apache.hadoop.hbase.zookeeper.ZKClusterId;
import org.apache.hadoop.hbase.zookeeper.ZooKeeperWatcher;
import org.apache.hadoop.net.DNS;
import org.apache.hadoop.security.UserGroupInformation;
import org.apache.hadoop.security.authorize.PolicyProvider;
import org.apache.hadoop.security.authorize.Service;
import org.apache.hadoop.security.token.SecretManager;
import org.apache.hadoop.security.token.Token;
import org.apache.hadoop.security.token.TokenIdentifier;
import org.junit.AfterClass;
import org.junit.BeforeClass;
import org.junit.Test;
import org.junit.experimental.categories.Category;

import com.google.protobuf.BlockingRpcChannel;
import com.google.protobuf.BlockingService;
import com.google.protobuf.RpcController;
import com.google.protobuf.ServiceException;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.apache.hadoop.hbase.Abortable;
import org.apache.hadoop.hbase.HBaseConfiguration;
import org.apache.hadoop.hbase.zookeeper.ZKUtil;
import org.apache.hadoop.hbase.zookeeper.ZooKeeperListener;
import static org.junit.Assert.fail;

/**
 * Reproduces a failure of the "Unknown master key" check in
 * {@link AuthenticationTokenSecretManager#retrievePassword} on a follower region server
 * after the key-master role fails over: the new key master immediately rolls (and signs tokens
 * with) a new master key, while a follower whose ZooKeeper notifications are delayed does not
 * know that key yet and rejects perfectly valid tokens.
 */
@Category({SecurityTests.class, MediumTests.class})
public class TestTokenAuthenticationKeyLeaderFailover {
  static {
    System.setProperty("java.security.krb5.realm", "hbase");
    System.setProperty("java.security.krb5.kdc", "blah");
  }
  private static final Log LOG = LogFactory.getLog(TestTokenAuthenticationKeyLeaderFailover.class);

  public interface AuthenticationServiceSecurityInfo {}

  /**
   * Basic server process for RPC authentication testing
   */
  private static class TokenServer extends TokenProvider
  implements AuthenticationProtos.AuthenticationService.BlockingInterface, Runnable, Server {
    private static final Log LOG = LogFactory.getLog(TokenServer.class);
    private Configuration conf;
    private RpcServerInterface rpcServer;
    private InetSocketAddress isa;
    private ZooKeeperWatcher zookeeper;
    private Sleeper sleeper;
    private boolean started = false;
    private boolean aborted = false;
    private boolean stopped = false;
    private long startcode;

    public TokenServer(Configuration conf) throws IOException {
      this.conf = conf;
      this.startcode = EnvironmentEdgeManager.currentTime();
      // Server to handle client requests.
      String hostname =
        Strings.domainNamePointerToHostName(DNS.getDefaultHost("default", "default"));
      int port = 0;
      // Creation of an ISA will force a resolve.
      InetSocketAddress initialIsa = new InetSocketAddress(hostname, port);
      if (initialIsa.getAddress() == null) {
        throw new IllegalArgumentException("Failed resolve of " + initialIsa);
      }
      final List<BlockingServiceAndInterface> sai =
        new ArrayList<BlockingServiceAndInterface>(1);
      BlockingService service =
        AuthenticationProtos.AuthenticationService.newReflectiveBlockingService(this);
      sai.add(new BlockingServiceAndInterface(service,
        AuthenticationProtos.AuthenticationService.BlockingInterface.class));
      this.rpcServer =
        new RpcServer(this, "tokenServer", sai, initialIsa, conf, new FifoRpcScheduler(conf, 1));
      InetSocketAddress address = rpcServer.getListenerAddress();
      if (address == null) {
        throw new IOException("Listener channel is closed");
      }
      this.isa = address;
      this.sleeper = new Sleeper(1000, this);
    }

    @Override
    public Configuration getConfiguration() {
      return conf;
    }

    @Override
    public ClusterConnection getConnection() {
      return null;
    }

    @Override
    public MetaTableLocator getMetaTableLocator() {
      return null;
    }

    @Override
    public ZooKeeperWatcher getZooKeeper() {
      return zookeeper;
    }

    @Override
    public CoordinatedStateManager getCoordinatedStateManager() {
      return null;
    }

    @Override
    public boolean isAborted() {
      return aborted;
    }

    @Override
    public ServerName getServerName() {
      return ServerName.valueOf(isa.getHostName(), isa.getPort(), startcode);
    }

    @Override
    public void abort(String reason, Throwable error) {
      LOG.fatal("Aborting on: "+reason, error);
      this.aborted = true;
      this.stopped = true;
      sleeper.skipSleepCycle();
    }

    private void initialize() throws IOException {
      // ZK configuration must _not_ have hbase.security.authentication or it will require SASL auth
      Configuration zkConf = new Configuration(conf);
      zkConf.set(User.HBASE_SECURITY_CONF_KEY, "simple");
      this.zookeeper = new ZooKeeperWatcher(zkConf, TokenServer.class.getSimpleName(),
          this, true);
      this.rpcServer.start();

      // mock RegionServerServices to provide to coprocessor environment
      final RegionServerServices mockServices = TEST_UTIL.createMockRegionServerService(rpcServer);

      // mock up coprocessor environment
      super.start(new RegionCoprocessorEnvironment() {
        @Override
        public HRegion getRegion() { return null; }

        @Override
        public RegionServerServices getRegionServerServices() {
          return mockServices;
        }

        @Override
        public ConcurrentMap<String, Object> getSharedData() { return null; }

        @Override
        public int getVersion() { return 0; }

        @Override
        public String getHBaseVersion() { return null; }

        @Override
        public Coprocessor getInstance() { return null; }

        @Override
        public int getPriority() { return 0; }

        @Override
        public int getLoadSequence() { return 0; }

        @Override
        public Configuration getConfiguration() { return conf; }

        @Override
        public HTableInterface getTable(TableName tableName) throws IOException
          { return null; }

        @Override
        public HTableInterface getTable(TableName tableName, ExecutorService service)
            throws IOException {
          return null;
        }

        @Override
        public ClassLoader getClassLoader() {
          return Thread.currentThread().getContextClassLoader();
        }

        @Override
        public HRegionInfo getRegionInfo() {
          return null;
        }
      });

      started = true;
    }

    public void run() {
      try {
        initialize();
        while (!stopped) {
          this.sleeper.sleep();
        }
      } catch (Exception e) {
        abort(e.getMessage(), e);
      }
      this.rpcServer.stop();
    }

    public boolean isStarted() {
      return started;
    }

    @Override
    public void stop(String reason) {
      LOG.info("Stopping due to: "+reason);
      this.stopped = true;
      sleeper.skipSleepCycle();
    }

    @Override
    public boolean isStopped() {
      return stopped;
    }

    public InetSocketAddress getAddress() {
      return isa;
    }

    public SecretManager<? extends TokenIdentifier> getSecretManager() {
      return ((RpcServer)rpcServer).getSecretManager();
    }

    @Override
    public AuthenticationProtos.GetAuthenticationTokenResponse getAuthenticationToken(
        RpcController controller, AuthenticationProtos.GetAuthenticationTokenRequest request)
      throws ServiceException {
      LOG.debug("Authentication token request from " + RpcServer.getRequestUserName());
      // ignore passed in controller -- it's always null
      ServerRpcController serverController = new ServerRpcController();
      BlockingRpcCallback<AuthenticationProtos.GetAuthenticationTokenResponse> callback =
          new BlockingRpcCallback<AuthenticationProtos.GetAuthenticationTokenResponse>();
      getAuthenticationToken(serverController, request, callback);
      try {
        serverController.checkFailed();
        return callback.get();
      } catch (IOException ioe) {
        throw new ServiceException(ioe);
      }
    }

    @Override
    public AuthenticationProtos.WhoAmIResponse whoAmI(
        RpcController controller, AuthenticationProtos.WhoAmIRequest request)
      throws ServiceException {
      LOG.debug("whoAmI() request from " + RpcServer.getRequestUserName());
      // ignore passed in controller -- it's always null
      ServerRpcController serverController = new ServerRpcController();
      BlockingRpcCallback<AuthenticationProtos.WhoAmIResponse> callback =
          new BlockingRpcCallback<AuthenticationProtos.WhoAmIResponse>();
      whoAmI(serverController, request, callback);
      try {
        serverController.checkFailed();
        return callback.get();
      } catch (IOException ioe) {
        throw new ServiceException(ioe);
      }
    }

    @Override
    public ChoreService getChoreService() {
      return null;
    }
  }

  /**
   * Pass-through wrapper installed on the follower's RpcServer only to make the server-side
   * stack trace of the rejected token visible in the test output. All work is delegated to the
   * real AuthenticationTokenSecretManager created by the RpcServer.
   */
  private static class LoggingSecretManager extends SecretManager<AuthenticationTokenIdentifier> {
    private final AuthenticationTokenSecretManager delegate;
    final AtomicReference<InvalidToken> rejected = new AtomicReference<InvalidToken>();

    LoggingSecretManager(AuthenticationTokenSecretManager delegate) {
      this.delegate = delegate;
    }

    @Override
    protected byte[] createPassword(AuthenticationTokenIdentifier identifier) {
      return delegate.createPassword(identifier);
    }

    @Override
    public byte[] retrievePassword(AuthenticationTokenIdentifier identifier) throws InvalidToken {
      try {
        return delegate.retrievePassword(identifier);
      } catch (InvalidToken e) {
        LOG.error("Follower " + delegate.getName() + " rejected token " + identifier, e);
        rejected.compareAndSet(null, e);
        throw e;
      }
    }

    @Override
    public AuthenticationTokenIdentifier createIdentifier() {
      return delegate.createIdentifier();
    }
  }

  /**
   * Registered first on the follower's ZooKeeperWatcher: while armed, delivery of every
   * ZooKeeper notification under the token auth znode is delayed until released (models a
   * follower whose ZK watch events arrive late, e.g. its ZK client is briefly disconnected or
   * its single ZK event thread is busy).
   */
  private static class DelayingListener extends ZooKeeperListener {
    private final String root;
    final CountDownLatch release = new CountDownLatch(1);
    final CountDownLatch delayed = new CountDownLatch(1);

    DelayingListener(ZooKeeperWatcher w, String root) {
      super(w);
      this.root = root;
    }

    private void maybeDelay(String path) {
      if (path != null && path.startsWith(root) && release.getCount() > 0) {
        LOG.info("Delaying ZK notification for " + path + " on follower");
        delayed.countDown();
        try {
          release.await();
        } catch (InterruptedException e) {
          Thread.currentThread().interrupt();
        }
      }
    }

    @Override public void nodeCreated(String path) { maybeDelay(path); }
    @Override public void nodeDeleted(String path) { maybeDelay(path); }
    @Override public void nodeDataChanged(String path) { maybeDelay(path); }
    @Override public void nodeChildrenChanged(String path) { maybeDelay(path); }
  }

  private static class NoopAbortable implements Abortable {
    volatile boolean aborted;
    @Override public void abort(String why, Throwable e) {
      LOG.info("Abort: " + why, e);
      aborted = true;
    }
    @Override public boolean isAborted() { return aborted; }
  }

  private static HBaseTestingUtility TEST_UTIL;
  private static ClusterId clusterId = new ClusterId();

  private static AuthenticationTokenSecretManager startKeyManager(Configuration base, String name)
      throws Exception {
    Configuration c = HBaseConfiguration.create(base);
    ZooKeeperWatcher zk = new ZooKeeperWatcher(c, name, new NoopAbortable());
    // same defaults as RpcServer#createSecretManager uses (24h key roll, 7d token lifetime)
    AuthenticationTokenSecretManager mgr = new AuthenticationTokenSecretManager(c, zk,
        name, 24 * 60 * 60 * 1000L, 7 * 24 * 60 * 60 * 1000L);
    mgr.start();
    return mgr;
  }

  private static void waitFor(String what, long timeoutMs, java.util.concurrent.Callable<Boolean> c)
      throws Exception {
    long deadline = System.currentTimeMillis() + timeoutMs;
    while (!c.call()) {
      if (System.currentTimeMillis() > deadline) {
        fail("Timed out waiting for " + what);
      }
      Thread.sleep(50);
    }
  }

  @Test(timeout = 180000)
  public void testTokenRejectedByFollowerAfterKeyMasterFailover() throws Exception {
    TEST_UTIL = new HBaseTestingUtility();
    TEST_UTIL.startMiniZKCluster();
    try {
      SecurityInfo.addInfo(AuthenticationProtos.AuthenticationService.getDescriptor().getName(),
          new SecurityInfo("hbase.test.kerberos.principal",
              AuthenticationProtos.TokenIdentifier.Kind.HBASE_AUTH_TOKEN));
      // key managers of two other region servers (rs-A and rs-B); ZK conf without SASL
      final Configuration zkConf = new Configuration(TEST_UTIL.getConfiguration());
      final AuthenticationTokenSecretManager rsA = startKeyManager(zkConf, "rs-a.example.com,16020,1");
      waitFor("rs-A to become key master", 30000, new java.util.concurrent.Callable<Boolean>() {
        public Boolean call() { return rsA.isMaster() && rsA.getCurrentKey() != null; }
      });
      final AuthenticationTokenSecretManager rsB = startKeyManager(zkConf, "rs-b.example.com,16020,1");
      final int keyOfA = rsA.getCurrentKey().getKeyId();
      waitFor("rs-B to sync keys", 30000, new java.util.concurrent.Callable<Boolean>() {
        public Boolean call() {
          return rsB.getCurrentKey() != null && rsB.getCurrentKey().getKeyId() == keyOfA;
        }
      });
      assertFalse(rsB.isMaster());

      // rs-C: the secure RPC server (follower) the client will talk to
      Configuration conf = TEST_UTIL.getConfiguration();
      conf.set("hadoop.security.authentication", "kerberos");
      conf.set("hbase.security.authentication", "kerberos");
      conf.setBoolean(HADOOP_SECURITY_AUTHORIZATION, true);
      final TokenServer server = new TokenServer(conf);
      Thread serverThread = new Thread(server);
      Threads.setDaemonThreadRunning(serverThread, "TokenServer:" + server.getServerName());
      while (!server.isStarted() && !server.isStopped()) {
        Thread.sleep(10);
      }
      server.rpcServer.refreshAuthManager(new PolicyProvider() {
        @Override
        public Service[] getServices() {
          return new Service[] { new Service("security.client.protocol.acl",
              AuthenticationProtos.AuthenticationService.BlockingInterface.class) };
        }
      });
      ZKClusterId.setClusterId(server.getZooKeeper(), clusterId);
      final AuthenticationTokenSecretManager rsC =
          (AuthenticationTokenSecretManager) server.getSecretManager();
      waitFor("rs-C to sync keys", 30000, new java.util.concurrent.Callable<Boolean>() {
        public Boolean call() {
          return rsC.getCurrentKey() != null && rsC.getCurrentKey().getKeyId() == keyOfA;
        }
      });
      assertFalse(rsC.isMaster());
      LoggingSecretManager observed = new LoggingSecretManager(rsC);
      ((RpcServer) server.rpcServer).setSecretManager(observed);

      // sanity: a token signed by the current master key is accepted by rs-C
      assertEquals("TOKEN", whoAmI(server, rsA.generateToken("testuser")));

      // rs-C's ZK notifications for the tokenauth znodes are now delivered late
      String tokenAuthRoot = ZKUtil.joinZNode(server.getZooKeeper().baseZNode, "tokenauth");
      DelayingListener delay = new DelayingListener(server.getZooKeeper(), tokenAuthRoot);
      server.getZooKeeper().registerListenerFirst(delay);

      // rolling restart: rs-A (key master) is shut down; rs-B takes over key leadership
      LOG.info("Stopping key master rs-A");
      rsA.stop();
      waitFor("rs-B to become key master and roll a new key", 30000,
          new java.util.concurrent.Callable<Boolean>() {
        public Boolean call() {
          return rsB.isMaster() && rsB.getCurrentKey().getKeyId() > keyOfA;
        }
      });
      int newKey = rsB.getCurrentKey().getKeyId();
      LOG.info("New key master rs-B rolled key " + newKey + "; rs-C still has current key "
          + rsC.getCurrentKey().getKeyId());
      assertTrue("rs-C notifications should be pending", delay.delayed.await(30, TimeUnit.SECONDS));

      // client obtains a fresh token from the new key master and uses it against rs-C
      Token<AuthenticationTokenIdentifier> token = rsB.generateToken("testuser");
      Exception clientFailure = null;
      try {
        whoAmI(server, token);
      } catch (Exception e) {
        clientFailure = e;
        LOG.error("Client failed to authenticate to rs-C with a valid token", e);
      }

      // let rs-C catch up; the very same token is now accepted -> the token was valid
      delay.release.countDown();
      final int nk = newKey;
      waitFor("rs-C to learn the new key", 30000, new java.util.concurrent.Callable<Boolean>() {
        public Boolean call() { return rsC.getKey(nk) != null; }
      });
      String after = whoAmI(server, token);
      LOG.info("After ZK notifications were delivered, rs-C accepted the token: " + after);

      server.stop("done");
      Threads.shutdown(serverThread);
      rsB.stop();

      assertNotNull("client authentication should have failed", clientFailure);
      InvalidTokenHolder.check(observed.rejected.get());
      throw new AssertionError("Valid token (key " + newKey + ", issued by key master after"
          + " failover) rejected by follower rs-C", observed.rejected.get());
    } finally {
      TEST_UTIL.shutdownMiniZKCluster();
    }
  }

  private static class InvalidTokenHolder {
    static void check(SecretManager.InvalidToken e) {
      assertNotNull("follower should have rejected the token", e);
      assertTrue(e.getMessage(), e.getMessage().startsWith("Unknown master key for token"));
    }
  }

  private static String whoAmI(final TokenServer server,
      Token<AuthenticationTokenIdentifier> token) throws Exception {
    UserGroupInformation testuser =
        UserGroupInformation.createUserForTesting("testuser", new String[]{"testgroup"});
    testuser.setAuthenticationMethod(UserGroupInformation.AuthenticationMethod.TOKEN);
    UserGroupInformation.setConfiguration(TEST_UTIL.getConfiguration());
    testuser.addToken(token);
    return testuser.doAs(new PrivilegedExceptionAction<String>() {
      public String run() throws Exception {
        Configuration c = server.getConfiguration();
        RpcClient rpcClient = RpcClientFactory.createClient(c, clusterId.toString());
        ServerName sn = ServerName.valueOf(server.getAddress().getHostName(),
            server.getAddress().getPort(), System.currentTimeMillis());
        try {
          BlockingRpcChannel channel = rpcClient.createBlockingRpcChannel(sn,
              User.getCurrent(), HConstants.DEFAULT_HBASE_RPC_TIMEOUT);
          AuthenticationProtos.AuthenticationService.BlockingInterface stub =
              AuthenticationProtos.AuthenticationService.newBlockingStub(channel);
          AuthenticationProtos.WhoAmIResponse response =
              stub.whoAmI(null, AuthenticationProtos.WhoAmIRequest.getDefaultInstance());
          assertEquals("testuser", response.getUsername());
          return response.getAuthMethod();
        } finally {
          rpcClient.close();
        }
      }
    });
  }
}
