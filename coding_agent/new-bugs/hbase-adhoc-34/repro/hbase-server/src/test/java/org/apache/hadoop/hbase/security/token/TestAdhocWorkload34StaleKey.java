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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.apache.hadoop.hbase.HBaseTestingUtil;
import org.apache.hadoop.hbase.SingleProcessHBaseCluster;
import org.apache.hadoop.hbase.ipc.RpcServer;
import org.apache.hadoop.hbase.ipc.RpcServerFactory;
import org.apache.hadoop.hbase.testclassification.MediumTests;
import org.apache.hadoop.hbase.testclassification.SecurityTests;
import org.apache.hadoop.hbase.util.EnvironmentEdgeManager;
import org.apache.hadoop.hbase.zookeeper.ZKListener;
import org.apache.hadoop.hbase.zookeeper.ZKWatcher;
import org.apache.hadoop.security.token.Token;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Same setup as {@link TestAdhocWorkload34} (every server runs its token secret manager), with a
 * short key roll interval and token lifetime. The delivery of the "new key" ZooKeeper notification
 * to the follower manager is delayed (its ZK event thread is held, as happens when the event
 * thread is busy or the follower is briefly disconnected from ZooKeeper). Meanwhile the follower
 * keeps issuing tokens with its now-stale current key. Those tokens get an expiration (issue time +
 * max lifetime) later than the expiration the leader gave the replaced key (roll time + max
 * lifetime), so the leader deletes the key while the tokens are still unexpired; afterwards every
 * server rejects them as "Unknown master key".
 */
@Tag(SecurityTests.TAG)
@Tag(MediumTests.TAG)
public class TestAdhocWorkload34StaleKey {

  private static final Logger LOG = LoggerFactory.getLogger(TestAdhocWorkload34StaleKey.class);

  private static final HBaseTestingUtil UTIL = new HBaseTestingUtil();

  private static final long KEY_UPDATE_INTERVAL = 2000;
  private static final long TOKEN_MAX_LIFETIME = 20000;

  @BeforeAll
  public static void setUp() throws Exception {
    UTIL.getConfiguration().set(RpcServerFactory.CUSTOM_RPC_SERVER_IMPL_CONF_KEY,
      TestAdhocWorkload34.TokenSecretsRpcServer.class.getName());
    UTIL.getConfiguration().setLong("hbase.auth.key.update.interval", KEY_UPDATE_INTERVAL);
    UTIL.getConfiguration().setLong("hbase.auth.token.max.lifetime", TOKEN_MAX_LIFETIME);
    UTIL.startMiniCluster(1);
  }

  @AfterAll
  public static void tearDown() throws Exception {
    UTIL.shutdownMiniCluster();
  }

  /** Holds the ZK event thread when the token keys parent's children change, until released. */
  private static final class DelayKeyEvents extends ZKListener {
    private final String keysParent;
    final CountDownLatch entered = new CountDownLatch(1);
    final CountDownLatch release = new CountDownLatch(1);

    DelayKeyEvents(ZKWatcher watcher, String keysParent) {
      super(watcher);
      this.keysParent = keysParent;
    }

    @Override
    public void nodeChildrenChanged(String path) {
      if (keysParent.equals(path) && release.getCount() > 0) {
        entered.countDown();
        try {
          release.await(60, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
          Thread.currentThread().interrupt();
        }
      }
    }
  }

  @Test
  public void run() throws Exception {
    SingleProcessHBaseCluster cluster = UTIL.getMiniHBaseCluster();
    AuthenticationTokenSecretManager onMaster = (AuthenticationTokenSecretManager) ((RpcServer) cluster
      .getMaster().getRpcServer()).getSecretManager();
    AuthenticationTokenSecretManager onServer = (AuthenticationTokenSecretManager) ((RpcServer) cluster
      .getRegionServer(0).getRpcServer()).getSecretManager();
    UTIL.waitFor(60000, () -> onMaster.isMaster() || onServer.isMaster());
    final AuthenticationTokenSecretManager leader = onMaster.isMaster() ? onMaster : onServer;
    final AuthenticationTokenSecretManager follower = leader == onMaster ? onServer : onMaster;
    ZKWatcher followerZk = leader == onMaster
      ? cluster.getRegionServer(0).getZooKeeper()
      : cluster.getMaster().getZooKeeper();
    LOG.info("Key leader is {}, follower is {}", leader.getName(), follower.getName());

    // follower has caught up with the leader's current key
    UTIL.waitFor(60000, () -> leader.getCurrentKey() != null && follower.getCurrentKey() != null
      && follower.getCurrentKey().getKeyId() == leader.getCurrentKey().getKeyId());

    // delay the delivery of the next key change notification to the follower
    String keysParent = new ZKSecretWatcher(UTIL.getConfiguration(), followerZk, follower)
      .getKeysParentZNode();
    DelayKeyEvents delay = new DelayKeyEvents(followerZk, keysParent);
    followerZk.registerListenerFirst(delay);
    AuthenticationTokenIdentifier identifier;
    try {
      final int staleId = follower.getCurrentKey().getKeyId();
      // the leader rolls its key (periodic roll); the follower does not learn it yet
      assertTrue(delay.entered.await(60, TimeUnit.SECONDS));
      UTIL.waitFor(60000, () -> leader.getCurrentKey().getKeyId() > staleId);
      long rollSeen = EnvironmentEdgeManager.currentTime();
      AuthenticationKey staleKeyAtLeader = leader.getKey(staleId);
      LOG.info("Leader rolled to key {}; replaced key {} expires at {}",
        leader.getCurrentKey().getKeyId(), staleId,
        staleKeyAtLeader == null ? -1 : staleKeyAtLeader.getExpiration());

      // follower keeps serving token requests in the meantime (e.g. TokenProvider on its regions)
      Thread.sleep(10000);
      Token<AuthenticationTokenIdentifier> token = follower.generateToken("adhoc");
      identifier = token.decodeIdentifier();
      assertEquals(staleId, identifier.getKeyId());
      LOG.info("Follower issued token with key {} expiring at {} (roll seen at {})",
        identifier.getKeyId(), identifier.getExpirationDate(), rollSeen);
    } finally {
      delay.release.countDown();
      followerZk.unregisterListener(delay);
    }

    final int keyId = identifier.getKeyId();
    // the leader expires the replaced key (roll time + max lifetime) and deletes it from ZK
    UTIL.waitFor(60000, () -> leader.getKey(keyId) == null && follower.getKey(keyId) == null);
    long now = EnvironmentEdgeManager.currentTime();
    LOG.info("Key {} deleted at {}; token still valid until {}", keyId, now,
      identifier.getExpirationDate());
    assertTrue(identifier.getExpirationDate() > now, "token should not have expired yet");

    // the unexpired token, signed by a key the cluster distributed, is now rejected everywhere
    follower.retrievePassword(identifier);
  }
}
