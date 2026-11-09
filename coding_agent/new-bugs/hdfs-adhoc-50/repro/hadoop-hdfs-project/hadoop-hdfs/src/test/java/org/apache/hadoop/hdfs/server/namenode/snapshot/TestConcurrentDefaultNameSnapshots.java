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

import static org.junit.jupiter.api.Assertions.fail;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.atomic.AtomicReference;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.FileSystem;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.hdfs.DFSConfigKeys;
import org.apache.hadoop.hdfs.DFSTestUtil;
import org.apache.hadoop.hdfs.DistributedFileSystem;
import org.apache.hadoop.hdfs.MiniDFSCluster;
import org.apache.hadoop.hdfs.protocol.SnapshotException;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

/**
 * Several independent clients concurrently take a snapshot of the same
 * snapshottable directory without giving a snapshot name (e.g.
 * "hdfs dfs -createSnapshot /dir", the documented usage where the NameNode
 * picks a default name). The NameNode derives the default name from the
 * wall clock with millisecond precision ("'s'yyyyMMdd-HHmmss.SSS"), so two
 * requests handled within the same millisecond get the same name and the
 * second one is rejected by the duplicate-name check in
 * DirectorySnapshottableFeature#addSnapshot, although the client never
 * asked for a particular name.
 */
public class TestConcurrentDefaultNameSnapshots {
  private static final short REPLICATION = 3;
  private static final long BLOCKSIZE = 1024;
  private static final long SEED = 0;
  private static final int CLIENTS = 8;
  private static final int MAX_ROUNDS = 2000;

  private Configuration conf;
  private MiniDFSCluster cluster;
  private DistributedFileSystem hdfs;

  @BeforeEach
  public void setUp() throws Exception {
    conf = new Configuration();
    conf.setInt(DFSConfigKeys.DFS_NAMENODE_SNAPSHOT_MAX_LIMIT, 65536);
    cluster = new MiniDFSCluster.Builder(conf).numDataNodes(REPLICATION)
        .build();
    cluster.waitActive();
    hdfs = cluster.getFileSystem();
  }

  @AfterEach
  public void tearDown() throws Exception {
    if (cluster != null) {
      cluster.shutdown();
      cluster = null;
    }
  }

  @Test
  @Timeout(value = 300)
  public void testConcurrentDefaultNameSnapshots() throws Exception {
    final Path dir = new Path("/testConcurrentDefaultNameSnapshots/foo");
    DFSTestUtil.createFile(hdfs, new Path(dir, "file1"), BLOCKSIZE,
        REPLICATION, SEED);
    hdfs.allowSnapshot(dir);

    // independent clients (as from different hosts / cron jobs)
    final List<FileSystem> clients = new ArrayList<>();
    for (int i = 0; i < CLIENTS; i++) {
      clients.add(FileSystem.newInstance(cluster.getURI(), conf));
    }

    final AtomicReference<Throwable> failure = new AtomicReference<>();
    final CyclicBarrier barrier = new CyclicBarrier(CLIENTS);
    final int[] roundsDone = new int[1];
    List<Thread> threads = new ArrayList<>();
    for (int i = 0; i < CLIENTS; i++) {
      final FileSystem fs = clients.get(i);
      Thread t = new Thread(() -> {
        try {
          for (int r = 0; r < MAX_ROUNDS; r++) {
            barrier.await();
            if (failure.get() != null) {
              return;
            }
            try {
              // no snapshot name: the NameNode generates a default one
              fs.createSnapshot(dir);
            } catch (SnapshotException e) {
              failure.compareAndSet(null, e);
            }
            synchronized (roundsDone) {
              roundsDone[0] = Math.max(roundsDone[0], r + 1);
            }
          }
        } catch (Throwable e) {
          if (!(e instanceof java.util.concurrent.BrokenBarrierException)) {
            failure.compareAndSet(null, e);
          }
          barrier.reset();
        }
      }, "snapshot-client-" + i);
      threads.add(t);
      t.start();
    }
    for (Thread t : threads) {
      t.join();
    }
    for (FileSystem fs : clients) {
      fs.close();
    }

    Throwable e = failure.get();
    if (e != null) {
      System.out.println("Concurrent default-named createSnapshot failed after "
          + roundsDone[0] + " round(s):");
      e.printStackTrace(System.out);
      if (e instanceof SnapshotException) {
        throw (SnapshotException) e;
      }
      fail("unexpected failure: " + e);
    }
    System.out.println("No collision in " + MAX_ROUNDS + " rounds");
  }
}
