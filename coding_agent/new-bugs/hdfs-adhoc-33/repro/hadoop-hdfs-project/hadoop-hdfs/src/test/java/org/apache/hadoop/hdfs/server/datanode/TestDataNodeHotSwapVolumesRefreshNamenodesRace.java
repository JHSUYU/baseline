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

import static org.apache.hadoop.hdfs.DFSConfigKeys.DFS_DATANODE_DATA_DIR_KEY;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import java.io.File;
import java.io.IOException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.conf.ReconfigurationException;
import org.apache.hadoop.fs.CommonConfigurationKeys;
import org.apache.hadoop.hdfs.DFSConfigKeys;
import org.apache.hadoop.hdfs.MiniDFSCluster;
import org.apache.hadoop.hdfs.MiniDFSNNTopology;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Hot-swap adding a data volume (reconfiguration of dfs.datanode.data.dir)
 * races with the removal of a block pool (refreshNamenodes dropping a
 * nameservice). DataStorage.prepareVolume() registers the
 * BlockPoolSliceStorage, DataNode.shutdownBlockPool() removes it, and
 * DataStorage.VolumeBuilder.build() then finds no BlockPoolSliceStorage.
 */
public class TestDataNodeHotSwapVolumesRefreshNamenodesRace {
  private static final Logger LOG = LoggerFactory.getLogger(
      TestDataNodeHotSwapVolumesRefreshNamenodesRace.class);

  /** Armed only during the hot-swap; set to the new volume's path. */
  static volatile String blockPath = null;
  static final CountDownLatch REACHED = new CountDownLatch(1);
  static final CountDownLatch RELEASE = new CountDownLatch(1);

  /**
   * A space-usage implementation (plugged in through the regular
   * fs.getspaceused.classname setting) whose construction is slow for
   * the newly hot-added volume, i.e. it models a slow du / slow disk while
   * FsVolumeImpl.addBlockPool() runs inside FsDatasetImpl.addVolume().
   */
  public static class SlowSpaceUsed extends FSCachingGetSpaceUsed {
    public SlowSpaceUsed(FSCachingGetSpaceUsed.Builder builder)
        throws IOException {
      super(builder);
      String p = blockPath;
      if (p != null && builder.getPath().getAbsolutePath().startsWith(p)
          && REACHED.getCount() > 0) {
        LOG.info("SlowSpaceUsed: addBlockPool of new volume for {} paused",
            builder.getBpid());
        REACHED.countDown();
        try {
          RELEASE.await(30, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
          Thread.currentThread().interrupt();
        }
      }
    }

    @Override
    protected void refresh() {
      // nothing; used space tracked by the initial value only
    }
  }

  private MiniDFSCluster cluster;

  @AfterEach
  public void tearDown() {
    blockPath = null;
    RELEASE.countDown();
    if (cluster != null) {
      cluster.shutdown();
      cluster = null;
    }
  }

  @Test
  @Timeout(value = 120)
  public void testAddVolumeRacesWithBlockPoolRemoval() throws Exception {
    Configuration conf = new Configuration();
    conf.setLong(DFSConfigKeys.DFS_BLOCK_SIZE_KEY, 512);
    conf.setLong(DFSConfigKeys.DFS_NAMENODE_MIN_BLOCK_SIZE_KEY, 1);
    conf.setInt(DFSConfigKeys.DFS_HEARTBEAT_INTERVAL_KEY, 1);
    conf.setClass(CommonConfigurationKeys.FS_GETSPACEUSED_CLASSNAME,
        SlowSpaceUsed.class, org.apache.hadoop.fs.GetSpaceUsed.class);

    cluster = new MiniDFSCluster.Builder(conf)
        .nnTopology(MiniDFSNNTopology.simpleFederatedTopology(2))
        .numDataNodes(1)
        .storagesPerDatanode(2)
        .build();
    cluster.waitActive();

    final DataNode dn = cluster.getDataNodes().get(0);
    assertEquals(2, dn.getAllBpOs().size());
    final java.util.Set<String> bpidsBefore = new java.util.HashSet<>();
    for (BPOfferService bpos : dn.getAllBpOs()) {
      bpidsBefore.add(bpos.getBlockPoolId());
    }
    assertEquals(2, bpidsBefore.size());

    // New volume to hot-add.
    final Configuration dnConf = dn.getConf();
    String oldDataDir = dnConf.get(DFS_DATANODE_DATA_DIR_KEY);
    File newVolume = cluster.getInstanceStorageDir(0, 3);
    newVolume.mkdirs();
    final String newDataDir = oldDataDir + ","
        + StorageLocation.parse(newVolume.toString()).toString();
    blockPath = newVolume.getAbsolutePath();

    LogCapturer logs = LogCapturer.captureLogs(DataNode.LOG);

    // Thread 1: admin adds a disk (dfsadmin -reconfig datanode ... start).
    ExecutorService exec = Executors.newSingleThreadExecutor();
    Future<Throwable> reconf = exec.submit(() -> {
      try {
        dn.reconfigurePropertyImpl(DFS_DATANODE_DATA_DIR_KEY, newDataDir);
        return null;
      } catch (ReconfigurationException e) {
        return e;
      }
    });

    // addVolume has run DataStorage.prepareVolume() (it registered the
    // BlockPoolSliceStorage of every block pool) and is now loading the
    // block pools of the new volume.
    assertTrue(REACHED.await(60, TimeUnit.SECONDS));

    // Thread 2 (concurrently): admin removes nameservice ns2 from the
    // DataNode's configuration and runs dfsadmin -refreshNamenodes.
    Configuration refreshConf = new Configuration(dnConf);
    refreshConf.set(DFSConfigKeys.DFS_NAMESERVICES, "ns1");
    dn.refreshNamenodes(refreshConf);

    GenericTestUtils.waitFor(() -> dn.getAllBpOs().size() == 1, 100, 30000);
    final String keptBpid = dn.getAllBpOs().get(0).getBlockPoolId();
    bpidsBefore.remove(keptBpid);
    final String removedBpid = bpidsBefore.iterator().next();
    // DataNode.shutdownBlockPool() -> DataStorage.removeBlockPoolStorage()
    GenericTestUtils.waitFor(
        () -> dn.getStorage().getBPStorage(removedBpid) == null, 100, 30000);
    assertNotNull(dn.getStorage().getBPStorage(keptBpid));
    LOG.info("Block pool {} (ns2) removed from DataStorage while volume {} "
        + "is being hot-added; kept block pool {}", removedBpid, newVolume,
        keptBpid);

    // Let the hot-swap continue: VolumeBuilder.build() now runs.
    RELEASE.countDown();
    Throwable t = reconf.get(60, TimeUnit.SECONDS);
    exec.shutdown();

    String out = logs.getOutput();
    logs.stopCapturing();
    LOG.info("Reconfiguration result: {}", String.valueOf(t));
    if (out.contains("java.lang.AssertionError")
        && out.contains("DataStorage$VolumeBuilder.build")) {
      int idx = out.indexOf("java.lang.AssertionError");
      String trace = out.substring(Math.max(0, idx - 2000),
          Math.min(out.length(), idx + 4000));
      System.out.println("==== captured AssertionError ====\n" + trace);
      AssertionError ae = new AssertionError(
          "DataStorage.VolumeBuilder.build() hit 'assert bpStorage != null' "
          + "while hot-adding a volume concurrently with block pool removal; "
          + "DataNode reconfiguration failed with: " + t + "\n" + trace);
      throw ae;
    }
    fail("Race did not trigger the assertion; reconfiguration result: " + t);
  }
}
