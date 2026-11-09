/**
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
package org.apache.hadoop.hdfs.server.namenode.snapshot;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.CommonConfigurationKeys;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.fs.permission.FsAction;
import org.apache.hadoop.hdfs.DFSConfigKeys;
import org.apache.hadoop.hdfs.DistributedFileSystem;
import org.apache.hadoop.hdfs.HdfsConfiguration;
import org.apache.hadoop.hdfs.MiniDFSCluster;
import org.apache.hadoop.hdfs.MiniDFSNNTopology;
import org.apache.hadoop.hdfs.client.HdfsClientConfigKeys;
import org.apache.hadoop.hdfs.protocol.SnapshottableDirectoryStatus;
import org.apache.hadoop.hdfs.server.namenode.EditLogFileOutputStream;
import org.apache.hadoop.hdfs.server.namenode.INode;
import org.apache.hadoop.hdfs.server.namenode.INodeAttributeProvider;
import org.apache.hadoop.hdfs.server.namenode.INodeAttributes;
import org.apache.hadoop.hdfs.server.namenode.ha.HATestUtil;
import org.apache.hadoop.security.AccessControlException;
import org.apache.hadoop.security.UserGroupInformation;
import org.apache.hadoop.test.GenericTestUtils;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

/**
 * allowSnapshot / disallowSnapshot are {@code @Idempotent} and are not
 * protected by the retry cache. When the first attempt of
 * disallowSnapshot("/") is slow on the NameNode (here: a slow external
 * authorization enforcer that runs before the namesystem lock is taken), the
 * client times out, fails over and retries; the retry succeeds and the admin
 * proceeds with allowSnapshot("/"). The original, stale disallowSnapshot("/")
 * then executes on the NameNode after allowSnapshot("/") and silently resets
 * the snapshot quota of the root directory to 0. The next createSnapshot("/")
 * fails with SnapshotException at DirectorySnapshottableFeature#addSnapshot
 * ("there are already 0 snapshot(s) and the snapshot quota is 0") although
 * the admin's last successful operation made "/" snapshottable.
 */
public class TestRootSnapshotStaleDisallowRetry {
  static {
    EditLogFileOutputStream.setShouldSkipFsyncForTesting(true);
  }

  private static final int RPC_TIMEOUT_MS = 3000;

  /** Armed by the test: hold back the first disallowSnapshot call. */
  static final AtomicBoolean DELAY_DISALLOW = new AtomicBoolean(false);
  static final AtomicInteger DISALLOW_CHECKS = new AtomicInteger();
  static final CountDownLatch FIRST_DISALLOW_ENTERED = new CountDownLatch(1);
  static final CountDownLatch RELEASE_FIRST_DISALLOW = new CountDownLatch(1);

  /**
   * An external authorization provider (as deployed e.g. with an external
   * policy engine) whose superuser check of the first disallowSnapshot call
   * is slow (e.g. a remote policy/audit call). It does not change any
   * authorization decision; it only delegates to the default enforcer.
   */
  public static class SlowAuthorizationProvider extends INodeAttributeProvider {
    @Override
    public void start() {
    }

    @Override
    public void stop() {
    }

    @Override
    public INodeAttributes getAttributes(String[] pathElements,
        INodeAttributes inode) {
      return inode;
    }

    @Override
    public AccessControlEnforcer getExternalAccessControlEnforcer(
        final AccessControlEnforcer defaultEnforcer) {
      return new AccessControlEnforcer() {
        @Override
        public void checkPermission(String fsOwner, String supergroup,
            UserGroupInformation ugi, INodeAttributes[] inodeAttrs,
            INode[] inodes, byte[][] pathByNameArr, int snapshotId,
            String path, int ancestorIndex, boolean doCheckOwner,
            FsAction ancestorAccess, FsAction parentAccess, FsAction access,
            FsAction subAccess, boolean ignoreEmptyDir)
            throws AccessControlException {
          defaultEnforcer.checkPermission(fsOwner, supergroup, ugi,
              inodeAttrs, inodes, pathByNameArr, snapshotId, path,
              ancestorIndex, doCheckOwner, ancestorAccess, parentAccess,
              access, subAccess, ignoreEmptyDir);
        }

        @Override
        public void checkPermissionWithContext(
            AuthorizationContext authzContext) throws AccessControlException {
          defaultEnforcer.checkPermissionWithContext(authzContext);
        }

        @Override
        public void checkSuperUserPermissionWithContext(
            AuthorizationContext authzContext) throws AccessControlException {
          if ("disallowSnapshot".equals(authzContext.getOperationName())
              && DELAY_DISALLOW.get()
              && DISALLOW_CHECKS.incrementAndGet() == 1) {
            // first attempt of disallowSnapshot: slow authorization
            FIRST_DISALLOW_ENTERED.countDown();
            try {
              RELEASE_FIRST_DISALLOW.await(120, TimeUnit.SECONDS);
            } catch (InterruptedException e) {
              Thread.currentThread().interrupt();
            }
          }
          defaultEnforcer.checkSuperUserPermissionWithContext(authzContext);
        }
      };
    }
  }

  private MiniDFSCluster cluster;

  @BeforeEach
  public void setUp() throws Exception {
    Configuration conf = new HdfsConfiguration();
    conf.set(DFSConfigKeys.DFS_NAMENODE_INODE_ATTRIBUTES_PROVIDER_KEY,
        SlowAuthorizationProvider.class.getName());
    cluster = new MiniDFSCluster.Builder(conf)
        .nnTopology(MiniDFSNNTopology.simpleHATopology())
        .numDataNodes(1).build();
    cluster.waitActive();
    cluster.transitionToActive(0);
  }

  @AfterEach
  public void tearDown() throws Exception {
    RELEASE_FIRST_DISALLOW.countDown();
    if (cluster != null) {
      cluster.shutdown();
      cluster = null;
    }
  }

  @Test
  @Timeout(value = 300)
  public void testStaleDisallowSnapshotRetryResetsRootQuota()
      throws Exception {
    // client with an RPC timeout (as configured in many deployments)
    Configuration clientConf = new Configuration(cluster.getConfiguration(0));
    clientConf.setInt(CommonConfigurationKeys.IPC_CLIENT_RPC_TIMEOUT_KEY,
        RPC_TIMEOUT_MS);
    clientConf.setInt(
        HdfsClientConfigKeys.Failover.SLEEPTIME_BASE_KEY, 100);
    clientConf.setInt(
        HdfsClientConfigKeys.Failover.SLEEPTIME_MAX_KEY, 500);
    final DistributedFileSystem hdfs =
        HATestUtil.configureFailoverFs(cluster, clientConf);
    final Path root = new Path("/");

    hdfs.mkdirs(new Path("/data"));
    // "/" is snapshottable and used, e.g., by a backup tool
    hdfs.allowSnapshot(root);
    hdfs.createSnapshot(root, "s0");
    hdfs.deleteSnapshot(root, "s0");

    // Admin resets the snapshottable state of "/": disallow, then allow.
    DELAY_DISALLOW.set(true);
    long start = System.currentTimeMillis();
    // first attempt is slow on NN0 -> client times out, fails over to NN1
    // (standby), fails back to NN0 and retries; the retry succeeds.
    hdfs.disallowSnapshot(root);
    long elapsed = System.currentTimeMillis() - start;
    assertTrue(FIRST_DISALLOW_ENTERED.await(0, TimeUnit.SECONDS),
        "first disallowSnapshot attempt should be in progress on NN0");
    assertTrue(DISALLOW_CHECKS.get() >= 2,
        "disallowSnapshot should have been retried by the client");
    System.out.println("disallowSnapshot(/) returned after " + elapsed
        + " ms, attempts on NN0 = " + DISALLOW_CHECKS.get());

    hdfs.allowSnapshot(root);
    SnapshottableDirectoryStatus[] listing =
        hdfs.getSnapshottableDirListing();
    assertNotNull(listing);
    assertEquals(1, listing.length);
    assertEquals("/", listing[0].getFullPath().toString());
    System.out.println("allowSnapshot(/) succeeded; / is snapshottable");

    // the stale first disallowSnapshot attempt now gets through
    RELEASE_FIRST_DISALLOW.countDown();
    final SnapshotManager sm =
        cluster.getNamesystem(0).getSnapshotManager();
    GenericTestUtils.waitFor(() -> sm.getNumSnapshottableDirs() == 0,
        100, 30000);
    System.out.println("stale disallowSnapshot(/) executed after "
        + "allowSnapshot(/)");

    // The admin's last successful operation was allowSnapshot("/"), yet:
    try {
      hdfs.createSnapshot(root, "s1");
    } catch (Exception e) {
      System.out.println("createSnapshot(/) failed:");
      e.printStackTrace(System.out);
      throw e;
    }
  }
}
