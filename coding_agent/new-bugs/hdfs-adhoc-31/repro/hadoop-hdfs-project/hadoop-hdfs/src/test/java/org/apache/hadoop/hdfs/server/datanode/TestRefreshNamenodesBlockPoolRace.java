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

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import java.net.InetSocketAddress;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.FileSystem;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.hdfs.DFSConfigKeys;
import org.apache.hadoop.hdfs.DFSTestUtil;
import org.apache.hadoop.hdfs.HdfsConfiguration;
import org.apache.hadoop.hdfs.MiniDFSCluster;
import org.apache.hadoop.hdfs.protocol.ExtendedBlock;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

/**
 * Renaming the nameservice of a running DataNode (e.g. converting a
 * non-federated / non-HA configuration into a named nameservice, as done when
 * enabling HA) with "dfsadmin -refreshNamenodes" starts a new BPOfferService
 * for the same NameNode / block pool and stops the old one. If the new
 * BPOfferService is added to BlockPoolManager (addBlockPool overwrites
 * bpid -&gt; old with bpid -&gt; new) before the old one has finished exiting, the
 * old one's cleanup (BlockPoolManager#remove, which removes by block pool id
 * without checking identity) deletes the mapping of the new BPOfferService.
 * The new BPOfferService then completes its initialization (storage, dataset,
 * registration) and keeps serving the block pool, but it is never put back in
 * the map: every DataNode#getBPOSForBlock fails with
 * "cannot locate OfferService thread for bp=...".
 */
public class TestRefreshNamenodesBlockPoolRace {

  private MiniDFSCluster cluster;
  private DataNodeFaultInjector oldInjector;

  @AfterEach
  public void tearDown() {
    if (oldInjector != null) {
      DataNodeFaultInjector.set(oldInjector);
    }
    if (cluster != null) {
      cluster.shutdown();
      cluster = null;
    }
  }

  @Test
  @Timeout(value = 180, unit = TimeUnit.SECONDS)
  public void testRenameNameserviceRacesWithOldBposExit() throws Exception {
    Configuration conf = new HdfsConfiguration();
    conf.setLong(DFSConfigKeys.DFS_HEARTBEAT_INTERVAL_KEY, 1L);
    conf.setInt(DFSConfigKeys.DFS_NAMENODE_HEARTBEAT_RECHECK_INTERVAL_KEY,
        1000);
    cluster = new MiniDFSCluster.Builder(conf).numDataNodes(1).build();
    cluster.waitActive();
    FileSystem fs = cluster.getFileSystem();
    Path file = new Path("/test.dat");
    DFSTestUtil.createFile(fs, file, 1024, (short) 1, 0L);
    ExtendedBlock block = DFSTestUtil.getFirstBlock(fs, file);
    final String bpid = block.getBlockPoolId();

    final DataNode dn = cluster.getDataNodes().get(0);
    final BPOfferService oldBpos = dn.getBPOfferService(bpid);
    assertNotNull(oldBpos);
    assertNull(oldBpos.getNameserviceId(),
        "non-federated config: nameservice id is null");

    // Scheduling hook (DataNodeFaultInjector#endOfferService): the old
    // actor thread is slow to leave its offerService loop (e.g. it was in
    // the middle of a long iteration when it got stopped).
    final Set<Thread> oldActorThreads = ConcurrentHashMap.newKeySet();
    final AtomicBoolean armed = new AtomicBoolean(false);
    final CountDownLatch oldParked = new CountDownLatch(1);
    final CountDownLatch releaseOld = new CountDownLatch(1);
    oldInjector = DataNodeFaultInjector.get();
    DataNodeFaultInjector.set(new DataNodeFaultInjector() {
      @Override
      public void endOfferService() throws Exception {
        Thread t = Thread.currentThread();
        if (!armed.get()) {
          oldActorThreads.add(t);
          return;
        }
        if (!oldActorThreads.contains(t) || releaseOld.getCount() == 0) {
          return;
        }
        oldParked.countDown();
        while (true) {
          try {
            if (releaseOld.await(60, TimeUnit.SECONDS)) {
              break;
            }
          } catch (InterruptedException ie) {
            // stop() interrupts us; keep waiting (thread is just slow)
          }
        }
      }
    });
    GenericTestUtils.waitFor(() -> !oldActorThreads.isEmpty(), 50, 10000);
    armed.set(true);
    assertTrue(oldParked.await(30, TimeUnit.SECONDS));
    final Thread oldThread = oldActorThreads.iterator().next();

    // Admin renames the nameservice (e.g. preparing for HA): same NameNode,
    // now configured under nameservice "ns1"; then runs
    // "hdfs dfsadmin -refreshNamenodes".
    InetSocketAddress nnAddr = cluster.getNameNode().getServiceRpcAddress();
    String addr = nnAddr.getHostString() + ":" + nnAddr.getPort();
    final Configuration newConf = new Configuration(dn.getConf());
    newConf.set(DFSConfigKeys.DFS_NAMESERVICES, "ns1");
    newConf.set(DFSConfigKeys.DFS_NAMENODE_RPC_ADDRESS_KEY + ".ns1", addr);
    newConf.set(DFSConfigKeys.DFS_NAMENODE_SERVICE_RPC_ADDRESS_KEY + ".ns1",
        addr);

    LogCapturer logs = LogCapturer.captureLogs(DataNode.LOG);
    final AtomicReference<Throwable> refreshError = new AtomicReference<>();
    Thread refresher = new Thread(() -> {
      try {
        dn.refreshNamenodes(newConf);
      } catch (Throwable t) {
        refreshError.set(t);
      }
    }, "refreshNamenodes");

    // Order the two concurrent threads (new BPOS actor initializing the block
    // pool, old BPOS actor cleaning it up). Holding the DataStorage monitor
    // only delays the new actor's storage analysis (as slow storage I/O or a
    // concurrent storage operation would); it does not change any state.
    synchronized (dn.getStorage()) {
      refresher.start();
      // new BPOS handshakes with the NN and calls initBlockPool:
      // BlockPoolManager#addBlockPool(new) overwrites bpid -> old.
      GenericTestUtils.waitFor(() -> {
        BPOfferService b = dn.getBPOfferService(bpid);
        return b != null && "ns1".equals(b.getNameserviceId());
      }, 10, 30000);
      // now the old actor thread finally exits its loop and cleans up:
      // BlockPoolManager#remove(old) removes bpid -> *new*.
      releaseOld.countDown();
      GenericTestUtils.waitFor(() -> dn.getBPOfferService(bpid) == null,
          10, 30000);
      GenericTestUtils.waitFor(
          () -> oldThread.getState() == Thread.State.BLOCKED, 10, 30000);
    }
    refresher.join(60000);
    assertNull(refreshError.get());

    BPOfferService newBpos = null;
    for (BPOfferService b : dn.getAllBpOs()) {
      if ("ns1".equals(b.getNameserviceId())) {
        newBpos = b;
      }
    }
    assertNotNull(newBpos);
    final BPOfferService nb = newBpos;
    GenericTestUtils.waitFor(() -> nb.isInitialized(), 50, 30000);
    assertEquals(1, dn.getAllBpOs().size());
    assertTrue(newBpos.isAlive());
    assertEquals(bpid, newBpos.getBlockPoolId());
    // The new BPOfferService is alive, registered and heartbeating for bpid,
    // but the DataNode can no longer locate it by block pool id.
    assertNull(dn.getBPOfferService(bpid));

    // The NameNode asks the DataNode to replicate the block to a new
    // DataNode (DNA_TRANSFER, via the live new BPOfferService).
    cluster.startDataNodes(conf, 1, true, null, null);
    cluster.waitActive();
    fs.setReplication(file, (short) 2);
    GenericTestUtils.waitFor(() -> logs.getOutput().contains(
        "cannot locate OfferService thread for bp=" + bpid), 100, 60000);
    logs.stopCapturing();
    fail("DataNode#getBPOSForBlock failed for a live block pool: "
        + "cannot locate OfferService thread for bp=" + bpid
        + " (see 'Failed to transfer block' stack trace in the log)");
  }
}
