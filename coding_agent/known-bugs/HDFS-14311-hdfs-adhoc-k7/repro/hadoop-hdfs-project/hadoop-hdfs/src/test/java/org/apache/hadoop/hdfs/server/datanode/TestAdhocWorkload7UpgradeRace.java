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
package org.apache.hadoop.hdfs.server.datanode;

import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import java.io.File;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.CommonConfigurationKeysPublic;
import org.apache.hadoop.hdfs.DFSConfigKeys;
import org.apache.hadoop.hdfs.HdfsConfiguration;
import org.apache.hadoop.hdfs.MiniDFSCluster;
import org.apache.hadoop.hdfs.UpgradeUtilities;
import org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB;
import org.apache.hadoop.hdfs.server.common.HdfsServerConstants.StartupOption;
import org.apache.hadoop.hdfs.server.common.Storage;
import org.apache.hadoop.hdfs.server.namenode.NameNode;
import org.apache.hadoop.hdfs.server.protocol.NamespaceInfo;
import org.apache.hadoop.test.GenericTestUtils;
import org.junit.BeforeClass;
import org.junit.Test;
import org.mockito.Mockito;
import org.mockito.invocation.InvocationOnMock;
import org.mockito.stubbing.Answer;

/**
 * Upgrade of a DataNode with two volumes, where the deferred (parallel)
 * block pool upgrade task of volume 1 runs concurrently with the main
 * thread's doTransition() of volume 2. Both share the fields
 * layoutVersion/cTime of the single BlockPoolSliceStorage object, so volume 2
 * is mistaken as already upgraded: it is stamped with the new cTime without a
 * "previous" snapshot. A later rollback then rejects volume 2 at
 * BlockPoolSliceStorage.doTransition ("Datanode state ... is newer than the
 * namespace state").
 *
 * The interleaving is forced only by delaying threads (the main thread right
 * after it read volume 2's VERSION file, and the upgrade task right before it
 * writes the new cTime into the shared field) - an ordering that the OS
 * scheduler can produce on its own.
 */
public class TestAdhocWorkload7UpgradeRace {

  @BeforeClass
  public static void initialize() throws Exception {
    UpgradeUtilities.initialize();
  }

  private static boolean inFrame(String cls, String method) {
    for (StackTraceElement e : Thread.currentThread().getStackTrace()) {
      if (e.getClassName().startsWith(cls) && e.getMethodName().equals(method)) {
        return true;
      }
    }
    return false;
  }

  @Test(timeout = 180000)
  public void run() throws Exception {
    final int numDirs = 2;
    Configuration conf = new HdfsConfiguration();
    conf = UpgradeUtilities.initializeStorageStateConf(numDirs, conf);
    String[] nameNodeDirs =
        conf.getStrings(DFSConfigKeys.DFS_NAMENODE_NAME_DIR_KEY);
    final String[] dataNodeDirs =
        conf.getStrings(DFSConfigKeys.DFS_DATANODE_DATA_DIR_KEY);
    conf.setBoolean(DFSConfigKeys.DFS_DATANODE_DUPLICATE_REPLICA_DELETION,
        false);

    UpgradeUtilities.createNameNodeStorageDirs(nameNodeDirs, "current");
    // Phase 1: NameNode upgrade (new cTime T1).
    MiniDFSCluster cluster = new MiniDFSCluster.Builder(conf).numDataNodes(0)
        .format(false)
        .manageDataDfsDirs(false)
        .manageNameDfsDirs(false)
        .startupOption(StartupOption.UPGRADE)
        .build();
    final String bpid = UpgradeUtilities.getCurrentBlockPoolID(cluster);
    final File dir1BpPrevious =
        new File(dataNodeDirs[0], "current/" + bpid + "/previous");
    final File dir2BpPrevious =
        new File(dataNodeDirs[1], "current/" + bpid + "/previous");
    try {
      // The NameNode is restarted (e.g. NN process bounce) while the
      // DataNode is coming up; the DN retries its versionRequest.
      cluster.shutdownNameNode(0);
      // DN fails its versionRequest fast while the NN is down, and retries
      // after BPServiceActor's 5s back-off.
      conf.setInt(CommonConfigurationKeysPublic.IPC_CLIENT_CONNECT_MAX_RETRIES_KEY, 0);
      UpgradeUtilities.createDataNodeStorageDirs(dataNodeDirs, "current");
      cluster.startDataNodes(conf, 1, false, StartupOption.REGULAR, null);
      DataNode dn = cluster.getDataNodes().get(0);

      final CountDownLatch dir2PropertiesRead = new CountDownLatch(1);
      final AtomicInteger bpTransitions = new AtomicInteger();

      // Wrap the namespace info returned by the NN so that the two
      // concurrently running threads can be ordered.
      BPServiceActor actor = null;
      long deadline = System.currentTimeMillis() + 30000;
      while (actor == null && System.currentTimeMillis() < deadline) {
        for (BPOfferService bpos : dn.getAllBpOs()) {
          for (BPServiceActor a : bpos.getBPServiceActors()) {
            if (a.getNameNodeProxy() != null) {
              actor = a;
            }
          }
        }
        Thread.sleep(50);
      }
      assertTrue("no BPServiceActor", actor != null);
      final DatanodeProtocolClientSideTranslatorPB origNN =
          actor.getNameNodeProxy();
      DatanodeProtocolClientSideTranslatorPB spyNN = Mockito.spy(origNN);
      Mockito.doAnswer(new Answer<NamespaceInfo>() {
        @Override
        public NamespaceInfo answer(InvocationOnMock inv) throws Throwable {
          NamespaceInfo real = origNN.versionRequest();
          NamespaceInfo spy = Mockito.spy(real);
          // Main BP thread: right after BlockPoolSliceStorage.doTransition()
          // of volume 2 has read the VERSION file, it is descheduled until
          // the upgrade task of volume 1 has completed.
          Mockito.doAnswer(new Answer<Integer>() {
            @Override
            public Integer answer(InvocationOnMock i) throws Throwable {
              if (inFrame(BlockPoolSliceStorage.class.getName(),
                  "doTransition")
                  && bpTransitions.incrementAndGet() == 2) {
                dir2PropertiesRead.countDown();
                long end = System.currentTimeMillis() + 30000;
                while (!dir1BpPrevious.exists()
                    && System.currentTimeMillis() < end) {
                  Thread.sleep(10);
                }
              }
              return (Integer) i.callRealMethod();
            }
          }).when(spy).getNamespaceID();
          // Upgrade task of volume 1 (executor thread): it is slow (e.g. many
          // hard links) and sets the shared cTime field only after the main
          // thread has read volume 2's VERSION file.
          Mockito.doAnswer(new Answer<Long>() {
            @Override
            public Long answer(InvocationOnMock i) throws Throwable {
              if (inFrame(BlockPoolSliceStorage.class.getName() + "$", "call")
                  && inFrame(BlockPoolSliceStorage.class.getName(),
                  "doUpgrade")) {
                dir2PropertiesRead.await(30, TimeUnit.SECONDS);
              }
              return (Long) i.callRealMethod();
            }
          }).when(spy).getCTime();
          return spy;
        }
      }).when(spyNN).versionRequest();
      actor.setNameNode(spyNN);

      cluster.restartNameNode(0, false, StartupOption.REGULAR.getName());
      deadline = System.currentTimeMillis() + 60000;
      while (!dn.isBPServiceAlive(bpid) || !dir1BpPrevious.exists()) {
        assertTrue("DN did not come up", System.currentTimeMillis() < deadline);
        Thread.sleep(100);
      }
      System.out.println("After upgrade: " + dir1BpPrevious + " exists="
          + dir1BpPrevious.exists() + ", " + dir2BpPrevious + " exists="
          + dir2BpPrevious.exists());
      assertTrue(dir1BpPrevious.isDirectory());
    } finally {
      cluster.shutdown();
    }

    // Phase 2: the administrator rolls the upgrade back (NN -rollback,
    // DN -rollback), which is allowed since the upgrade was not finalized.
    GenericTestUtils.LogCapturer logs =
        GenericTestUtils.LogCapturer.captureLogs(Storage.LOG);
    NameNode.doRollback(conf, false);
    cluster = new MiniDFSCluster.Builder(conf).numDataNodes(0)
        .format(false)
        .manageDataDfsDirs(false)
        .manageNameDfsDirs(false)
        .dnStartupOption(StartupOption.ROLLBACK)
        .build();
    try {
      cluster.startDataNodes(conf, 1, false, StartupOption.ROLLBACK, null);
      Thread.sleep(3000);
      String out = logs.getOutput();
      logs.stopCapturing();
      if (out.contains("is newer than the namespace state")) {
        System.out.println("==== Captured DataNode rollback log ====\n" + out);
        fail("DataNode rollback rejected volume " + dataNodeDirs[1]
            + " (upgraded without a previous snapshot due to the race):\n"
            + out);
      }
      DataNode dn = cluster.getDataNodes().get(0);
      assertTrue(dn.isBPServiceAlive(bpid));
    } finally {
      cluster.shutdown();
      UpgradeUtilities.createEmptyDirs(nameNodeDirs);
      UpgradeUtilities.createEmptyDirs(dataNodeDirs);
    }
  }
}
