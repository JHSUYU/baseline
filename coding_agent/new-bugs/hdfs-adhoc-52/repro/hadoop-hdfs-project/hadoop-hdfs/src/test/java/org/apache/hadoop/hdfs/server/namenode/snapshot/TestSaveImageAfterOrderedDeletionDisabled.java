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
package org.apache.hadoop.hdfs.server.namenode.snapshot;

import static org.apache.hadoop.hdfs.server.namenode.snapshot.SnapshotManager.DFS_NAMENODE_SNAPSHOT_DELETION_ORDERED;
import static org.apache.hadoop.hdfs.server.namenode.snapshot.SnapshotManager.DFS_NAMENODE_SNAPSHOT_DELETION_ORDERED_GC_PERIOD_MS;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.hdfs.DistributedFileSystem;
import org.apache.hadoop.hdfs.MiniDFSCluster;
import org.apache.hadoop.fs.SafeModeAction;
import org.apache.hadoop.hdfs.server.namenode.FSImage;
import org.apache.hadoop.hdfs.server.namenode.FSNamesystem;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

/**
 * Snapshots are deleted with ordered snapshot deletion enabled (so the
 * SnapshotDeletionGc thread logs a second OP_DELETE_SNAPSHOT for a snapshot
 * that was already logged as deleted), then the admin disables ordered
 * deletion and restarts the NameNode. Edit log replay tolerates the
 * duplicate delete (DirectorySnapshottableFeature#removeSnapshot returns null)
 * but SnapshotManager#deleteSnapshot still decrements numSnapshots, so the
 * snapshot counter no longer matches the snapshots in the namespace and the
 * next saveNamespace / checkpoint fails in
 * FSImageFormatPBSnapshot.Saver#serializeSnapshotSection.
 */
public class TestSaveImageAfterOrderedDeletionDisabled {
  private static final int GC_PERIOD = 10;
  private MiniDFSCluster cluster;

  @BeforeEach
  public void setUp() throws Exception {
    Configuration conf = new Configuration();
    conf.setBoolean(DFS_NAMENODE_SNAPSHOT_DELETION_ORDERED, true);
    conf.setInt(DFS_NAMENODE_SNAPSHOT_DELETION_ORDERED_GC_PERIOD_MS, GC_PERIOD);
    cluster = new MiniDFSCluster.Builder(conf).numDataNodes(1).build();
    cluster.waitActive();
  }

  @AfterEach
  public void tearDown() throws Exception {
    if (cluster != null) {
      cluster.shutdown();
      cluster = null;
    }
  }

  @Test
  @Timeout(value = 120)
  public void testSaveNamespaceAfterDisablingOrderedDeletion()
      throws Exception {
    DistributedFileSystem hdfs = cluster.getFileSystem();
    final Path dir = new Path("/dir");
    hdfs.mkdirs(dir);
    hdfs.allowSnapshot(dir);
    hdfs.mkdirs(new Path(dir, "sub0"));
    hdfs.createSnapshot(dir, "s0");
    hdfs.mkdirs(new Path(dir, "sub1"));
    hdfs.createSnapshot(dir, "s1");

    // s1 is not the earliest: only marked as deleted (OP_DELETE_SNAPSHOT s1).
    hdfs.deleteSnapshot(dir, "s1");
    // s0 is the earliest: really deleted (OP_DELETE_SNAPSHOT s0).
    hdfs.deleteSnapshot(dir, "s0");

    // The GC thread now really deletes s1 and logs OP_DELETE_SNAPSHOT for
    // its "deleted" name.
    final FSNamesystem fsn = cluster.getNamesystem();
    GenericTestUtils.waitFor(
        () -> fsn.getSnapshotManager().getNumSnapshots() == 0, 10, 30000);
    assertEquals(0, cluster.getNameNode().getNamesystem()
        .getSnapshotManager().getSnapshottableDirs().get(0)
        .getDirectorySnapshottableFeature().getNumSnapshots());

    // Admin turns ordered snapshot deletion off and restarts the NameNode;
    // the edits above are replayed.
    cluster.getNameNode().getConf()
        .setBoolean(DFS_NAMENODE_SNAPSHOT_DELETION_ORDERED, false);
    cluster.restartNameNode(true);
    hdfs = cluster.getFileSystem();
    SnapshotManager sm = cluster.getNamesystem().getSnapshotManager();
    System.out.println("numSnapshots after replay = " + sm.getNumSnapshots()
        + ", snapshots in dir = " + sm.getSnapshottableDirs().get(0)
        .getDirectorySnapshottableFeature().getNumSnapshots());

    // A regular checkpoint now fails.
    LogCapturer logs = LogCapturer.captureLogs(FSImage.LOG);
    hdfs.setSafeMode(SafeModeAction.ENTER);
    try {
      hdfs.saveNamespace();
      fail("saveNamespace should have failed");
    } catch (Exception e) {
      System.out.println("saveNamespace failed: " + e);
    } finally {
      logs.stopCapturing();
    }
    String out = logs.getOutput();
    System.out.println("Captured FSImage log:\n" + out);
    assertTrue(out.contains("java.lang.IllegalStateException"), out);
    assertTrue(out.contains("FSImageFormatPBSnapshot.java:467")
        || out.contains("FSImageFormatPBSnapshot.java:466"), out);
  }
}
