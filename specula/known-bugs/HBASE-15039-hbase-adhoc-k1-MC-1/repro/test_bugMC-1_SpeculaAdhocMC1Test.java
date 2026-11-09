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
import java.util.concurrent.atomic.AtomicInteger;
import org.apache.hadoop.hbase.zookeeper.ZooKeeperListener;
import org.junit.Before;
import org.junit.After;

/**
 * Specula MC-1 (hbase-adhoc-k1): variant of {@link TestTokenAuthentication} with TWO token
 * servers sharing one ZooKeeper. The keymaster rolls a fresh key (ATSM:254-256) and a token
 * signed with it is presented to the follower before the follower's ZK event thread applied
 * the key's NodeChildrenChanged event (ZKSW:120-131). retrievePassword then throws
 * InvalidToken at ATSM:147.
 *
 * The TokenServer class below is copied verbatim from TestTokenAuthentication (only the
 * TEST_UTIL reference is unchanged and static). Nothing in the system under test is modified.
 */
@Category({SecurityTests.class, MediumTests.class})
public class SpeculaAdhocMC1Test {
  static {
    System.setProperty("java.security.krb5.realm", "hbase");
    System.setProperty("java.security.krb5.kdc", "blah");
  }
  private static final Log LOG = LogFactory.getLog(SpeculaAdhocMC1Test.class);
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

  private static HBaseTestingUtility TEST_UTIL;
  private static ClusterId clusterId = new ClusterId();
  private final List<TokenServer> servers = new ArrayList<TokenServer>();
  private final List<Thread> threads = new ArrayList<Thread>();

  private static void out(String s) {
    System.out.println("[MC1] " + s);
    System.out.flush();
  }

  /** Same setup as TestTokenAuthentication.setupBeforeClass, per server. */
  private TokenServer startServer(Configuration conf) throws Exception {
    TokenServer server = new TokenServer(conf);
    Thread t = new Thread(server);
    Threads.setDaemonThreadRunning(t, "TokenServer:" + server.getServerName().toString());
    while (!server.isStarted() && !server.isStopped()) {
      Thread.sleep(10);
    }
    server.rpcServer.refreshAuthManager(new PolicyProvider() {
      @Override
      public Service[] getServices() {
        return new Service [] {
          new Service("security.client.protocol.acl",
            AuthenticationProtos.AuthenticationService.BlockingInterface.class)};
      }
    });
    servers.add(server);
    threads.add(t);
    return server;
  }

  private Configuration baseConf() {
    Configuration conf = TEST_UTIL.getConfiguration();
    conf.set("hadoop.security.authentication", "kerberos");
    conf.set("hbase.security.authentication", "kerberos");
    conf.setBoolean(HADOOP_SECURITY_AUTHORIZATION, true);
    return conf;
  }

  @Before
  public void setUp() throws Exception {
    TEST_UTIL = new HBaseTestingUtility();
    TEST_UTIL.startMiniZKCluster();
    SecurityInfo.addInfo(AuthenticationProtos.AuthenticationService.getDescriptor().getName(),
      new SecurityInfo("hbase.test.kerberos.principal",
        AuthenticationProtos.TokenIdentifier.Kind.HBASE_AUTH_TOKEN));
  }

  @After
  public void tearDown() throws Exception {
    for (TokenServer s : servers) s.stop("Test complete");
    for (Thread t : threads) Threads.shutdown(t);
    servers.clear();
    threads.clear();
    TEST_UTIL.shutdownMiniZKCluster();
  }

  private static AuthenticationTokenSecretManager mgr(TokenServer s) {
    return (AuthenticationTokenSecretManager) s.getSecretManager();
  }

  /** whoAmI over SASL/DIGEST with the token, exactly as TestTokenAuthentication does it. */
  private String whoAmIWithToken(final TokenServer target,
      Token<AuthenticationTokenIdentifier> token) throws Exception {
    UserGroupInformation testuser =
        UserGroupInformation.createUserForTesting("testuser", new String[]{"testgroup"});
    testuser.setAuthenticationMethod(UserGroupInformation.AuthenticationMethod.TOKEN);
    UserGroupInformation.setConfiguration(TEST_UTIL.getConfiguration());
    testuser.addToken(token);
    try {
      return testuser.doAs(new PrivilegedExceptionAction<String>() {
        public String run() throws Exception {
          Configuration c = target.getConfiguration();
          RpcClient rpcClient = RpcClientFactory.createClient(c, clusterId.toString());
          ServerName sn = ServerName.valueOf(target.getAddress().getHostName(),
              target.getAddress().getPort(), System.currentTimeMillis());
          try {
            BlockingRpcChannel channel = rpcClient.createBlockingRpcChannel(sn,
                User.getCurrent(), HConstants.DEFAULT_HBASE_RPC_TIMEOUT);
            AuthenticationProtos.AuthenticationService.BlockingInterface stub =
                AuthenticationProtos.AuthenticationService.newBlockingStub(channel);
            AuthenticationProtos.WhoAmIResponse response =
                stub.whoAmI(null, AuthenticationProtos.WhoAmIRequest.getDefaultInstance());
            return "OK user=" + response.getUsername() + " authMethod=" + response.getAuthMethod();
          } finally {
            rpcClient.close();
          }
        }
      });
    } catch (Exception e) {
      Throwable c = e;
      StringBuilder sb = new StringBuilder("FAILED:");
      while (c != null) {
        sb.append(" <- ").append(c.getClass().getName()).append(": ").append(c.getMessage());
        c = c.getCause();
      }
      return sb.toString();
    }
  }

  private static int keyIdOf(Token<AuthenticationTokenIdentifier> token) throws IOException {
    AuthenticationTokenIdentifier ident = new AuthenticationTokenIdentifier();
    Writables.getWritable(token.getIdentifier(), ident);
    return ident.getKeyId();
  }

  /** Direct call of the follower's public retrievePassword, as testTokenCreation does. */
  private static boolean validateDirect(AuthenticationTokenSecretManager follower,
      Token<AuthenticationTokenIdentifier> token, String label) throws IOException {
    AuthenticationTokenIdentifier ident = new AuthenticationTokenIdentifier();
    Writables.getWritable(token.getIdentifier(), ident);
    try {
      byte[] pw = follower.retrievePassword(ident);
      out(label + ": follower.retrievePassword OK, password matches="
          + Bytes.equals(pw, token.getPassword()));
      return true;
    } catch (SecretManager.InvalidToken it) {
      out(label + ": follower.retrievePassword THREW " + it);
      for (StackTraceElement f : it.getStackTrace()) {
        out("    at " + f);
        if (f.getClassName().startsWith("org.junit")) break;
      }
      return false;
    }
  }

  /**
   * Level 0 (pure black box). Server A becomes keymaster; server B is a follower that has
   * fully started (watch on the keys znode set). hbase.auth.key.update.interval is shortened
   * (time compression through the key RpcServer reads, RpcServer:2189) so the keymaster rolls
   * a fresh key on each 5 s pass of its loop (ATSM:315-327). For every roll, the client takes
   * a token from A as soon as A's currentKey changes and presents it to B.
   */
  @Test(timeout = 180000)
  public void testLevel0FreshKeyAtFollower() throws Exception {
    Configuration conf = baseConf();
    conf.setLong("hbase.auth.key.update.interval", 1000);
    TokenServer a = startServer(conf);
    ZKClusterId.setClusterId(a.getZooKeeper(), clusterId);
    AuthenticationTokenSecretManager ma = mgr(a);
    while (ma.getCurrentKey() == null) Thread.sleep(1);
    TokenServer b = startServer(conf);
    AuthenticationTokenSecretManager mb = mgr(b);
    while (mb.getCurrentKey() == null) Thread.sleep(1);
    out("L0 A isMaster=" + ma.isMaster() + " B isMaster=" + mb.isMaster()
        + " A.cur=" + ma.getCurrentKey().getKeyId() + " B.cur=" + mb.getCurrentKey().getKeyId());
    // warm up the RPC path so class loading does not dominate the timing
    out("L0 warm-up whoAmI at B: " + whoAmIWithToken(b, ma.generateToken("testuser")));

    int directFail = 0, rpcFail = 0, trials = 4;
    for (int i = 0; i < trials; i++) {
      int seen = ma.getCurrentKey().getKeyId();
      while (ma.getCurrentKey().getKeyId() == seen) Thread.yield();
      // A just installed a fresh key into allKeys/currentKey (ATSM:254-255)
      Token<AuthenticationTokenIdentifier> t1 = ma.generateToken("testuser");
      boolean bHas = mb.getKey(keyIdOf(t1)) != null;
      out("L0 trial " + i + ": token keyId=" + keyIdOf(t1) + " follower has key=" + bHas);
      if (!validateDirect(mb, t1, "L0 trial " + i + " direct")) directFail++;
      Token<AuthenticationTokenIdentifier> t2 = ma.generateToken("testuser");
      String r = whoAmIWithToken(b, t2);
      out("L0 trial " + i + " RPC whoAmI at B (keyId=" + keyIdOf(t2) + "): " + r);
      if (r.startsWith("FAILED")) rpcFail++;
    }
    out("L0 SUMMARY trials=" + trials + " directInvalidToken=" + directFail
        + " rpcAuthFailed=" + rpcFail);
  }

  /**
   * Level 1 (timing assistance). Same as Level 0, but a listener registered first on B's
   * ZooKeeperWatcher (ZooKeeperWatcher.registerListenerFirst, the codebase's own API) takes
   * 3 s on the keys-znode NodeChildrenChanged event. This only stretches B's single ZK event
   * thread (a busy/slow event thread); ZKSecretWatcher and ATSM logic are unchanged.
   */
  @Test(timeout = 180000)
  public void testLevel1SlowFollowerEventThread() throws Exception {
    Configuration conf = baseConf();
    conf.setLong("hbase.auth.key.update.interval", 1000);
    TokenServer a = startServer(conf);
    ZKClusterId.setClusterId(a.getZooKeeper(), clusterId);
    final AuthenticationTokenSecretManager ma = mgr(a);
    while (ma.getCurrentKey() == null) Thread.sleep(1);
    TokenServer b = startServer(conf);
    final AuthenticationTokenSecretManager mb = mgr(b);
    while (mb.getCurrentKey() == null) Thread.sleep(1);
    final String keysParent = ZKUtilJoin(b.getZooKeeper());
    final AtomicInteger delayed = new AtomicInteger();
    b.getZooKeeper().registerListenerFirst(new ZooKeeperListener(b.getZooKeeper()) {
      @Override
      public void nodeChildrenChanged(String path) {
        if (keysParent.equals(path)) {
          delayed.incrementAndGet();
          Threads.sleep(3000);
        }
      }
    });
    out("L1 A isMaster=" + ma.isMaster() + " B isMaster=" + mb.isMaster()
        + " A.cur=" + ma.getCurrentKey().getKeyId() + " B.cur=" + mb.getCurrentKey().getKeyId());
    out("L1 warm-up whoAmI at B: " + whoAmIWithToken(b, ma.generateToken("testuser")));

    int seen = ma.getCurrentKey().getKeyId();
    while (ma.getCurrentKey().getKeyId() == seen) Thread.yield();
    Token<AuthenticationTokenIdentifier> tok = ma.generateToken("testuser");
    int kid = keyIdOf(tok);
    // wait until A has published the key to ZK (ATSM:256), so only follower lag remains
    long t0 = System.currentTimeMillis();
    while (org.apache.hadoop.hbase.zookeeper.ZKUtil.checkExists(a.getZooKeeper(),
        keysParent + "/" + kid) < 0) Thread.sleep(1);
    out("L1 fresh key " + kid + " published in ZK after " + (System.currentTimeMillis() - t0)
        + " ms; follower has key=" + (mb.getKey(kid) != null));
    out("L1 >>> RPC whoAmI at B begin (no direct retrievePassword call before this point)");
    String r = whoAmIWithToken(b, tok);
    out("L1 <<< RPC whoAmI at B end");
    out("L1 RPC whoAmI at B with fresh token: " + r);
    validateDirect(mb, tok, "L1 direct");
    out("L1 whoAmI at A (issuer) with the same token: " + whoAmIWithToken(a, tok));
    // let B's event thread drain, then retry: shows the follower state is later repaired
    long t1 = System.currentTimeMillis();
    while (mb.getKey(kid) == null && System.currentTimeMillis() - t1 < 20000) Thread.sleep(10);
    out("L1 follower applied key " + kid + " after " + (System.currentTimeMillis() - t1)
        + " ms (delayed events=" + delayed.get() + ")");
    out("L1 retry RPC whoAmI at B with the same token: " + whoAmIWithToken(b, tok));
  }

  private static String ZKUtilJoin(ZooKeeperWatcher zkw) {
    // ZKSecretWatcher: baseZNode + "/tokenauth" + "/keys" (ZKSW:52-54, defaults)
    return org.apache.hadoop.hbase.zookeeper.ZKUtil.joinZNode(
        org.apache.hadoop.hbase.zookeeper.ZKUtil.joinZNode(zkw.baseZNode, "tokenauth"), "keys");
  }
}
