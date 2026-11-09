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

import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.spy;

import java.io.File;
import java.io.IOException;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.FileUtil;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.hdfs.DFSConfigKeys;
import org.apache.hadoop.hdfs.DFSTestUtil;
import org.apache.hadoop.hdfs.HdfsConfiguration;
import org.apache.hadoop.hdfs.MiniDFSCluster;
import org.apache.hadoop.hdfs.server.common.HdfsServerConstants.StartupOption;
import org.apache.hadoop.hdfs.server.protocol.NamespaceInfo;
import org.apache.hadoop.test.GenericTestUtils;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.mockito.stubbing.Answer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Two volumes hot-added at the same time (DataNode#refreshVolumes adds every
 * new volume in its own thread) share one BlockPoolSliceStorage object and its
 * in-memory cTime field. A volume that is perfectly up to date (cTime equal to
 * the namenode cTime) is rejected by the ad hoc check in
 * BlockPoolSliceStorage#loadStorageDirectory when another volume, which still
 * carries the pre-upgrade cTime, reads its VERSION file in between.
 *
 * The NamespaceInfo spies only delay getCTime() (they return the real value)
 * to pin the interleaving that can happen with real thread scheduling.
 */
public class TestBlockPoolSliceStorageConcurrentHotSwap {
  private static final Logger LOG = LoggerFactory.getLogger(
      TestBlockPoolSliceStorageConcurrentHotSwap.class);

  private MiniDFSCluster cluster;

  private static boolean calledFromBpDoTransition() {
    for (StackTraceElement e : Thread.currentThread().getStackTrace()) {
      if (e.getClassName().equals(BlockPoolSliceStorage.class.getName())
          && e.getMethodName().equals("doTransition")) {
        return true;
      }
    }
    return false;
  }

  @Test
  @Timeout(value = 120)
  public void testConcurrentHotSwapOfStaleAndNewVolume() throws Exception {
    File base = GenericTestUtils.getTestDir("bpss-concurrent-hotswap");
    FileUtil.fullyDelete(base);
    File nameDir = new File(base, "name");
    File d1 = new File(base, "data1");   // always attached
    File d2 = new File(base, "data2");   // offline during the NN upgrade
    File d3 = new File(base, "data3");   // brand-new disk

    // Phase 1: cluster with one DN with volumes data1 and data2.
    Configuration conf = new HdfsConfiguration();
    conf.set(DFSConfigKeys.DFS_NAMENODE_NAME_DIR_KEY, nameDir.getAbsolutePath());
    conf.set(DFSConfigKeys.DFS_NAMENODE_EDITS_DIR_KEY,
        nameDir.getAbsolutePath());
    conf.set(DFSConfigKeys.DFS_DATANODE_DATA_DIR_KEY,
        d1.getAbsolutePath() + "," + d2.getAbsolutePath());
    cluster = new MiniDFSCluster.Builder(conf).numDataNodes(1)
        .manageNameDfsDirs(false).manageDataDfsDirs(false).build();
    cluster.waitActive();
    DFSTestUtil.createFile(cluster.getFileSystem(), new Path("/f1"),
        1024 * 1024, (short) 1, 0L);
    long oldCTime = cluster.getNameNodeRpc().versionRequest().getCTime();
    cluster.shutdown();

    // Phase 2: NN is upgraded (new cTime) while data2 is offline,
    // so only data1 is upgraded by the DN.
    conf.set(DFSConfigKeys.DFS_DATANODE_DATA_DIR_KEY, d1.getAbsolutePath());
    cluster = new MiniDFSCluster.Builder(conf).numDataNodes(1)
        .format(false).manageNameDfsDirs(false).manageDataDfsDirs(false)
        .startupOption(StartupOption.UPGRADE).build();
    cluster.waitActive();
    NamespaceInfo realNsInfo = cluster.getNameNodeRpc().versionRequest();
    final long nnCTime = realNsInfo.getCTime();
    LOG.info("NN cTime before upgrade = {}, after upgrade = {}",
        oldCTime, nnCTime);
    assertNotEquals(oldCTime, nnCTime);
    DataNode dn = cluster.getDataNodes().get(0);

    // Phase 3: the admin hot-adds the old disk data2 and a new disk data3
    // at the same time; refreshVolumes calls FsDatasetSpi#addVolume for
    // each of them concurrently. We do the same, ordering the two threads.
    final CountDownLatch newVolInCheck = new CountDownLatch(1);
    final CountDownLatch staleVolReadVersion = new CountDownLatch(1);
    final CountDownLatch newVolDone = new CountDownLatch(1);

    NamespaceInfo nsForNew = spy(realNsInfo);
    final AtomicBoolean newOnce = new AtomicBoolean();
    doAnswer((Answer<Long>) inv -> {
      long v = (Long) inv.callRealMethod();
      if (calledFromBpDoTransition() && newOnce.compareAndSet(false, true)) {
        // the new volume has read its own VERSION (cTime == NN cTime)
        newVolInCheck.countDown();
        staleVolReadVersion.await(30, TimeUnit.SECONDS);
      }
      return v;
    }).when(nsForNew).getCTime();

    NamespaceInfo nsForStale = spy(realNsInfo);
    final AtomicBoolean staleOnce = new AtomicBoolean();
    doAnswer((Answer<Long>) inv -> {
      long v = (Long) inv.callRealMethod();
      if (calledFromBpDoTransition() && staleOnce.compareAndSet(false, true)) {
        // the stale volume has read its VERSION (old cTime)
        staleVolReadVersion.countDown();
        newVolDone.await(30, TimeUnit.SECONDS);
      }
      return v;
    }).when(nsForStale).getCTime();

    final List<NamespaceInfo> newNs = Collections.singletonList(nsForNew);
    final List<NamespaceInfo> staleNs = Collections.singletonList(nsForStale);
    final StorageLocation loc2 = StorageLocation.parse(d2.getAbsolutePath());
    final StorageLocation loc3 = StorageLocation.parse(d3.getAbsolutePath());

    ExecutorService service = Executors.newFixedThreadPool(2);
    Future<IOException> newFuture = service.submit(() -> {
      try {
        dn.getFSDataset().addVolume(loc3, newNs);
        return null;
      } catch (IOException e) {
        return e;
      } finally {
        newVolDone.countDown();
      }
    });
    assertTrue(newVolInCheck.await(30, TimeUnit.SECONDS));
    Future<IOException> staleFuture = service.submit(() -> {
      try {
        dn.getFSDataset().addVolume(loc2, staleNs);
        return null;
      } catch (IOException e) {
        return e;
      }
    });
    IOException newErr = newFuture.get();
    IOException staleErr = staleFuture.get();
    service.shutdown();

    LOG.info("stale volume add result: {}", staleErr == null ? "OK" : staleErr);
    if (newErr != null) {
      LOG.error("Adding the brand-new volume " + d3 + " failed", newErr);
      throw new AssertionError("Hot-adding an up-to-date volume failed "
          + "because a concurrently added volume overwrote the shared "
          + "BlockPoolSliceStorage cTime: " + newErr.getMessage(), newErr);
    }
  }

  @AfterEach
  public void tearDown() {
    if (cluster != null) {
      cluster.shutdown();
      cluster = null;
    }
  }
}
