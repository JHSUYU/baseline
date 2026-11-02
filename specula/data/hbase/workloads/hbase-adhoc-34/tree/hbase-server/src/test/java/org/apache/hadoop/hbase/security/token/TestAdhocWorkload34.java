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

import static org.junit.jupiter.api.Assertions.assertArrayEquals;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.util.List;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hbase.HBaseTestingUtil;
import org.apache.hadoop.hbase.Server;
import org.apache.hadoop.hbase.SingleProcessHBaseCluster;
import org.apache.hadoop.hbase.ipc.NettyRpcServer;
import org.apache.hadoop.hbase.ipc.RpcScheduler;
import org.apache.hadoop.hbase.ipc.RpcServer;
import org.apache.hadoop.hbase.ipc.RpcServerFactory;
import org.apache.hadoop.hbase.testclassification.MediumTests;
import org.apache.hadoop.hbase.testclassification.SecurityTests;
import org.apache.hadoop.security.token.Token;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;

/**
 * Authentication token keys on a one-region-server cluster with simple authentication. Every
 * server's RPC server runs its token secret manager (leader election and key distribution through
 * ZooKeeper), as on a secure cluster, while its connections stay simple. The manager elected key
 * master generates a token; the other server's manager drops its copy of the token's key and then
 * validates the token's identifier.
 */
@Tag(SecurityTests.TAG)
@Tag(MediumTests.TAG)
public class TestAdhocWorkload34 {

  private static final HBaseTestingUtil UTIL = new HBaseTestingUtil();

  /**
   * A {@link NettyRpcServer} that runs its token secret manager whatever the authentication: the
   * manager is built as {@code RpcServer#createSecretManager} builds it on a secure cluster.
   */
  public static class TokenSecretsRpcServer extends NettyRpcServer {
    public TokenSecretsRpcServer(Server server, String name,
      List<RpcServer.BlockingServiceAndInterface> services, InetSocketAddress bindAddress,
      Configuration conf, RpcScheduler scheduler, boolean reservoirEnabled) throws IOException {
      super(server, name, services, bindAddress, conf, scheduler, reservoirEnabled);
    }

    @Override
    protected AuthenticationTokenSecretManager createSecretManager() {
      if (server == null) {
        return null;
      }
      Configuration conf = server.getConfiguration();
      long keyUpdateInterval = conf.getLong("hbase.auth.key.update.interval", 24 * 60 * 60 * 1000);
      long maxAge = conf.getLong("hbase.auth.token.max.lifetime", 7 * 24 * 60 * 60 * 1000);
      return new AuthenticationTokenSecretManager(conf, server.getZooKeeper(),
        server.getServerName().toString(), keyUpdateInterval, maxAge);
    }
  }

  @BeforeAll
  public static void setUp() throws Exception {
    UTIL.getConfiguration().set(RpcServerFactory.CUSTOM_RPC_SERVER_IMPL_CONF_KEY,
      TokenSecretsRpcServer.class.getName());
    UTIL.startMiniCluster(1);
  }

  @AfterAll
  public static void tearDown() throws Exception {
    UTIL.shutdownMiniCluster();
  }

  @Test
  public void run() throws Exception {
    SingleProcessHBaseCluster cluster = UTIL.getMiniHBaseCluster();
    AuthenticationTokenSecretManager onMaster = (AuthenticationTokenSecretManager) ((RpcServer) cluster
      .getMaster().getRpcServer()).getSecretManager();
    AuthenticationTokenSecretManager onServer = (AuthenticationTokenSecretManager) ((RpcServer) cluster
      .getRegionServer(0).getRpcServer()).getSecretManager();
    UTIL.waitFor(60000, () -> onMaster.isMaster() || onServer.isMaster());
    AuthenticationTokenSecretManager leader = onMaster.isMaster() ? onMaster : onServer;
    AuthenticationTokenSecretManager other = leader == onMaster ? onServer : onMaster;
    UTIL.waitFor(60000, () -> leader.getCurrentKey() != null);

    Token<AuthenticationTokenIdentifier> token = leader.generateToken("adhoc");
    AuthenticationTokenIdentifier identifier = token.decodeIdentifier();
    other.removeKey(identifier.getKeyId());
    assertArrayEquals(token.getPassword(), other.retrievePassword(identifier));
  }
}
