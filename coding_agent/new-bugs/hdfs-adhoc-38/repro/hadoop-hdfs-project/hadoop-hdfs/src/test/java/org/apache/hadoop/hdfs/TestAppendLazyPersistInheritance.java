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
package org.apache.hadoop.hdfs;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.File;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.BlockLocation;
import org.apache.hadoop.fs.FSDataOutputStream;
import org.apache.hadoop.fs.FileSystem;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.fs.StorageType;
import org.apache.hadoop.hdfs.server.namenode.NameNodeAdapter;
import org.apache.hadoop.ipc.RemoteException;
import org.apache.hadoop.test.GenericTestUtils;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

/**
 * LAZY_PERSIST is a "copy on create" storage policy: it is fixed on a file
 * when the file is created (FSDirWriteFileOp#setNewINodeStoragePolicy) and
 * the NameNode refuses to put it on an already existing file
 * ("Policy LAZY_PERSIST cannot be set after file creation").  Setting it on a
 * directory, however, is accepted, and an existing file whose own policy is
 * unspecified inherits it through INodeFile#getStoragePolicyID().  An
 * ordinary file whose data is on DISK is then treated as a lazy persist file
 * and append is rejected at FSDirAppendOp.java:122.
 */
public class TestAppendLazyPersistInheritance {

  private static final String CHECK_FRAME =
      "FSDirAppendOp.appendFile(FSDirAppendOp.java:122)";

  private static void expectLazyPersistRejection(FileSystem fs, Path p) {
    RemoteException re = assertThrows(RemoteException.class,
        () -> fs.append(p).close());
    System.out.println("append(" + p + ") failed with:\n" + re);
    AppendTestUtil.LOG.info("append failed", re);
    assertEquals(UnsupportedOperationException.class.getName(),
        re.getClassName());
    assertTrue(re.getMessage().contains(CHECK_FRAME), re.getMessage());
  }

  @Test
  @Timeout(value = 120)
  public void testAppendRejectedAfterParentSetToLazyPersist()
      throws Exception {
    Configuration conf = new HdfsConfiguration();
    File builderBaseDir = new File(GenericTestUtils.getRandomizedTempPath());
    MiniDFSCluster cluster = new MiniDFSCluster.Builder(conf, builderBaseDir)
        .numDataNodes(1).build();
    try {
      cluster.waitActive();
      final DistributedFileSystem admin = cluster.getFileSystem();
      final FileSystem writer =
          AppendTestUtil.createHdfsWithDifferentUsername(conf);
      final Path dir = new Path("/data");
      admin.mkdirs(dir);
      admin.setPermission(dir,
          new org.apache.hadoop.fs.permission.FsPermission((short) 0777));
      final Path p = new Path(dir, "log");
      final int len = 1 << 16;
      final byte[] contents = AppendTestUtil.initBuffer(len);

      // 1. A client creates a normal (non lazy persist) file and is writing
      //    it; its replicas are on DISK.
      FSDataOutputStream out = writer.create(p, true, 4096, (short) 1, len);
      out.write(contents, 0, len / 2);
      out.hflush();

      // 2. Concurrently, an administrator sets LAZY_PERSIST on the parent
      //    directory (intended for files created there from now on).  The
      //    same policy is refused on the existing file itself.
      RemoteException direct = assertThrows(RemoteException.class,
          () -> admin.setStoragePolicy(p, "LAZY_PERSIST"));
      assertTrue(direct.getMessage().contains("cannot be set after file"
          + " creation"), direct.getMessage());
      admin.setStoragePolicy(dir, "LAZY_PERSIST");

      // 3. The writer finishes and closes the file normally.
      out.write(contents, len / 2, len - len / 2);
      out.close();
      for (BlockLocation loc : admin.getFileBlockLocations(p, 0, len)) {
        for (StorageType t : loc.getStorageTypes()) {
          assertEquals(StorageType.DISK, t);
        }
      }
      // The file's own policy was never set; it now reports LAZY_PERSIST.
      assertEquals("LAZY_PERSIST", admin.getStoragePolicy(p).getName());

      // 4. Later the writer appends to its own, ordinary file -> rejected.
      expectLazyPersistRejection(writer, p);

      writer.close();
    } finally {
      cluster.shutdown();
    }
  }

  @Test
  @Timeout(value = 120)
  public void testAppendRejectedAfterRenameIntoLazyPersistDir()
      throws Exception {
    Configuration conf = new HdfsConfiguration();
    File builderBaseDir = new File(GenericTestUtils.getRandomizedTempPath());
    MiniDFSCluster cluster = new MiniDFSCluster.Builder(conf, builderBaseDir)
        .numDataNodes(1).build();
    try {
      cluster.waitActive();
      final DistributedFileSystem fs = cluster.getFileSystem();
      final Path scratch = new Path("/scratch");
      fs.mkdirs(scratch);
      fs.setStoragePolicy(scratch, "LAZY_PERSIST");
      final Path p = new Path("/testAppendTwice/foo");
      final int len = 1 << 16;
      FSDataOutputStream out = fs.create(p, true, 4096, (short) 1, len);
      out.write(AppendTestUtil.initBuffer(len), 0, len);
      out.close();
      // Append works while the file is outside the LAZY_PERSIST directory.
      fs.append(p).close();
      // Move the (disk resident) file into the LAZY_PERSIST directory.
      final Path moved = new Path(scratch, "foo");
      assertTrue(fs.rename(p, moved));
      assertEquals("LAZY_PERSIST", fs.getStoragePolicy(moved).getName());
      expectLazyPersistRejection(fs, moved);
    } finally {
      cluster.shutdown();
    }
  }

  /**
   * Consequence: the NameNode's LazyPersistFileScrubber uses the same
   * inherited policy, so the ordinary DISK file is deleted from the
   * namespace when its replicas are temporarily unavailable (here: its
   * DataNode is down while the NameNode restarts).
   */
  @Test
  @Timeout(value = 120)
  public void testInheritedLazyPersistFileDeletedByScrubber()
      throws Exception {
    Configuration conf = new HdfsConfiguration();
    conf.setInt(
        DFSConfigKeys.DFS_NAMENODE_LAZY_PERSIST_FILE_SCRUB_INTERVAL_SEC, 1);
    File builderBaseDir = new File(GenericTestUtils.getRandomizedTempPath());
    MiniDFSCluster cluster = new MiniDFSCluster.Builder(conf, builderBaseDir)
        .numDataNodes(1).build();
    try {
      cluster.waitActive();
      DistributedFileSystem fs = cluster.getFileSystem();
      final Path dir = new Path("/data");
      final Path p = new Path(dir, "log");
      final int len = 1 << 16;
      FSDataOutputStream out = fs.create(p, true, 4096, (short) 1, len);
      out.write(AppendTestUtil.initBuffer(len), 0, len);
      out.close();
      fs.setStoragePolicy(dir, "LAZY_PERSIST");
      expectLazyPersistRejection(fs, p);

      // The only DataNode holding the (DISK) replica is down while the
      // NameNode restarts.
      MiniDFSCluster.DataNodeProperties dn = cluster.stopDataNode(0);
      cluster.restartNameNode(false);
      // Equivalent of "hdfs dfsadmin -safemode leave" (with many files the
      // NameNode also leaves safe mode on its own with a few blocks missing).
      NameNodeAdapter.leaveSafeMode(cluster.getNameNode());
      final DistributedFileSystem dfs = (DistributedFileSystem)
          FileSystem.newInstance(cluster.getURI(), conf);
      GenericTestUtils.waitFor(() -> {
        try {
          return !dfs.exists(p);
        } catch (java.io.IOException e) {
          return false;
        }
      }, 200, 30000);
      // The DataNode (and its intact replica) comes back, but the file has
      // been removed from the namespace.
      cluster.restartDataNode(dn, true);
      cluster.waitActive();
      assertTrue(!cluster.getFileSystem().exists(p),
          "file should have been deleted by the scrubber");
      System.out.println("Ordinary DISK file " + p
          + " was deleted by LazyPersistFileScrubber");
    } finally {
      cluster.shutdown();
    }
  }
}
