/*
 * MC-1 reproduction. Level 0: public FileSystem API on a MiniDFSCluster, pristine classes,
 * no fault injection, no failpoint, no reflection, no write to the file's own policy id.
 *
 * Variant of org.apache.hadoop.hdfs.TestFileAppend#testAppendTwice with the setup copied from
 * that test. The runner (test_bugMC-1_append_after_ancestor_lazy_persist.sh) installs this file as
 * hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/SpeculaAdhocFSDirAppendOpMC1Test.java
 *
 * A test passes when the anomalous behaviour it names happens. Lines prefixed "MC1|" are the evidence.
 *
 *   t0  control: workload as written, no tag. First append works, second gets ABCE.
 *   t1  counterexample spec/output/MC_hunt_s1_bfs.out: tag / after close, first append throws.
 *   t1w the workload's body plus that one line: the workload's own assertion fails.
 *   t2  tag /testAppendTwice after close, first append throws.
 *   t3  tag between the appends, second append throws UOE instead of ABCE.
 *   t4  control: direct route refused, ancestor route admitted; new file is stamped, old file flips.
 *   t5  permanence: retry, NameNode restart from edits, restart from fsimage; unset is the only exit.
 *   t6  real consumer: hdfs dfs -appendToFile.
 *   t7  reach: a non-admin without write access to the file blocks another user's appends.
 *   t8  context CR-2: truncate guard fires by the same mechanism.
 *   t9  context T-1: the scrubber deletes a DISK file after a transient DataNode outage.
 *   t10 context T-1: a NameNode restart alone deletes a tagged DISK file, default configuration.
 */
package org.apache.hadoop.hdfs;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.BlockLocation;
import org.apache.hadoop.fs.FSDataOutputStream;
import org.apache.hadoop.fs.FileSystem;
import org.apache.hadoop.fs.FsShell;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.fs.SafeModeAction;
import org.apache.hadoop.fs.permission.FsPermission;
import org.apache.hadoop.hdfs.MiniDFSCluster.DataNodeProperties;
import org.apache.hadoop.hdfs.protocol.AlreadyBeingCreatedException;
import org.apache.hadoop.hdfs.protocol.ExtendedBlock;
import org.apache.hadoop.hdfs.server.namenode.INodeFile;
import org.apache.hadoop.ipc.RemoteException;
import org.apache.hadoop.security.AccessControlException;
import org.apache.hadoop.security.UserGroupInformation;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.util.ToolRunner;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.MethodOrderer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestMethodOrder;
import org.junit.jupiter.api.Timeout;

@TestMethodOrder(MethodOrderer.MethodName.class)
@Timeout(240)
public class SpeculaAdhocFSDirAppendOpMC1Test {
  private static final String LP = "LAZY_PERSIST";
  private static final Path ROOT = new Path("/");
  private static final Path D = new Path("/testAppendTwice");
  private static final Path P = new Path("/testAppendTwice/foo");
  private static final int LEN = 1 << 16;
  private static final String TARGET_FRAME =
      "org.apache.hadoop.hdfs.server.namenode.FSDirAppendOp.appendFile(FSDirAppendOp.java:122)";
  private static final String TARGET_MSG = "Cannot append to lazy persist file ";

  private static void say(String s) {
    System.out.println("MC1|" + s);
    System.out.flush();
  }

  @BeforeAll
  public static void provenance() throws Exception {
    Class<?> c = Class.forName("org.apache.hadoop.hdfs.server.namenode.FSDirAppendOp");
    say("FSDirAppendOp loaded from " + c.getProtectionDomain().getCodeSource().getLocation());
    boolean instrumented = true;
    try {
      Class.forName("org.apache.hadoop.hdfs.server.namenode.SpeculaNNTrace");
    } catch (ClassNotFoundException e) {
      instrumented = false;
    }
    say("SpeculaNNTrace on classpath: " + instrumented);
    assertFalse(instrumented, "reproduction must run on pristine classes");
  }

  /** The workload's setup, copied from TestFileAppend#testAppendTwice. */
  private static final class Rig implements AutoCloseable {
    final Configuration conf;
    final MiniDFSCluster cluster;
    final DistributedFileSystem fs1;
    final FileSystem fs2;

    Rig() throws Exception {
      this(new HdfsConfiguration());
    }

    Rig(Configuration conf) throws Exception {
      this.conf = conf;
      File builderBaseDir = new File(GenericTestUtils.getRandomizedTempPath());
      cluster = new MiniDFSCluster.Builder(conf, builderBaseDir).build();
      fs1 = cluster.getFileSystem();
      fs2 = AppendTestUtil.createHdfsWithDifferentUsername(conf);
    }

    /** create a new file with a full block, as the workload does. */
    void createAndClose(Path p) throws IOException {
      final byte[] fileContents = AppendTestUtil.initBuffer(LEN);
      FSDataOutputStream out = fs2.create(p, true, 4096, (short) 1, LEN);
      out.write(fileContents, 0, LEN);
      out.close();
    }

    INodeFile inode(Path p) throws IOException {
      return cluster.getNamesystem().getFSDirectory().getINode(p.toString()).asFile();
    }

    /** Read-only observation of the guard's operand and of what clients can see. */
    void show(String label, Path p) throws IOException {
      INodeFile f = inode(p);
      BlockLocation[] locs = fs1.getFileBlockLocations(p, 0, Long.MAX_VALUE);
      StringBuilder types = new StringBuilder();
      for (BlockLocation l : locs) {
        types.append(Arrays.toString(l.getStorageTypes()));
      }
      say(label + ": " + p + " own=" + f.getLocalStoragePolicyID()
          + " eff=" + f.getStoragePolicyID()
          + " getStoragePolicy=" + fs1.getStoragePolicy(p).getName()
          + " underConstruction=" + f.isUnderConstruction()
          + " replication=" + f.getFileReplication()
          + " blockStorageTypes=" + types);
    }

    @Override
    public void close() throws Exception {
      fs2.close();
      fs1.close();
      cluster.shutdown();
    }
  }

  /**
   * Same-bug test: exception type, message and the frame at the target's file and line. The class and
   * the stack come from the NameNode. RemoteException.unwrapRemoteException cannot rebuild a class that
   * is not an IOException (RemoteException.java:88), so the client holds a RemoteException naming it.
   */
  private static void assertTarget(String label, RemoteException e, Path p) {
    String m = e.getMessage();
    say(label + ": client caught RemoteException(" + e.getClassName() + "): " + m.split("\n", 2)[0]);
    String frame = "";
    for (String line : m.split("\n")) {
      if (line.contains("FSDirAppendOp.appendFile(")) {
        frame = line.trim();
        break;
      }
    }
    say(label + ": NameNode stack frame: " + frame);
    assertEquals(UnsupportedOperationException.class.getName(), e.getClassName());
    assertTrue(m.startsWith(TARGET_MSG + p), m);
    assertEquals("at " + TARGET_FRAME, frame, m);
  }

  private static RemoteException appendThrows(FileSystem fs, Path p) {
    return assertThrows(RemoteException.class, () -> fs.append(p).close());
  }

  @Test
  public void t0_controlWorkloadAsWritten() throws Exception {
    try (Rig r = new Rig()) {
      r.createAndClose(P);
      r.show("t0 after close", P);
      FSDataOutputStream first = r.fs2.append(P);
      say("t0: first append succeeded");
      r.show("t0 after first append", P);
      try {
        r.fs1.append(P);
        fail();
      } catch (RemoteException re) {
        say("t0: second append got " + re.getClassName());
        assertEquals(AlreadyBeingCreatedException.class.getName(), re.getClassName());
      }
      first.close();
    }
  }

  /** The counterexample, step for step. */
  @Test
  public void t1_counterexampleTagRootAfterClose() throws Exception {
    try (Rig r = new Rig()) {
      r.createAndClose(P);                                 // CE states 2 and 3
      r.show("t1 after close", P);
      r.fs1.setStoragePolicy(ROOT, LP);                    // CE state 4
      r.show("t1 after setStoragePolicy(/)", P);
      assertEquals(0, r.inode(P).getLocalStoragePolicyID());
      assertEquals(15, r.inode(P).getStoragePolicyID());
      RemoteException e = appendThrows(r.fs2, P);          // CE state 5, TestFileAppend:337
      assertTarget("t1", e, P);
      say("t1: full exception as the client sees it:\n" + e.getMessage());
      r.show("t1 after failed append", P);
      assertFalse(r.inode(P).isUnderConstruction());
    }
  }

  /**
   * The workload's body with the counterexample's step as the only added line, and the workload's own
   * catch block and assertion. Its oracle is the caller that observes the wrong outcome.
   */
  @Test
  public void t1w_workloadOwnOracleSeesWrongOutcome() throws Exception {
    AssertionError oracle = assertThrows(AssertionError.class, () -> {
      Configuration conf = new HdfsConfiguration();
      File builderBaseDir = new File(GenericTestUtils.getRandomizedTempPath());
      MiniDFSCluster cluster = new MiniDFSCluster.Builder(conf, builderBaseDir)
          .build();
      final FileSystem fs1 = cluster.getFileSystem();
      final FileSystem fs2 = AppendTestUtil.createHdfsWithDifferentUsername(conf);
      try {

        final Path p = new Path("/testAppendTwice/foo");
        final int len = 1 << 16;
        final byte[] fileContents = AppendTestUtil.initBuffer(len);

        {
          // create a new file with a full block.
          FSDataOutputStream out = fs2.create(p, true, 4096, (short)1, len);
          out.write(fileContents, 0, len);
          out.close();
        }

        fs1.setStoragePolicy(new Path("/"), "LAZY_PERSIST"); // the only added line: CE state 4

        //1st append does not add any data so that the last block remains full
        //and the last block in INodeFileUnderConstruction is a BlockInfo
        //but does not have a BlockUnderConstructionFeature.
        fs2.append(p);

        //2nd append should get AlreadyBeingCreatedException
        fs1.append(p);
        fail();
      } catch(RemoteException re) {
        AppendTestUtil.LOG.info("Got an exception:", re);
        assertEquals(AlreadyBeingCreatedException.class.getName(),
            re.getClassName());
      } finally {
        fs2.close();
        fs1.close();
        cluster.shutdown();
      }
    });
    say("t1w: the workload's own assertion failed: " + oracle.getMessage());
    assertTrue(oracle.getMessage().contains(UnsupportedOperationException.class.getName()));
  }

  @Test
  public void t2_tagParentAfterClose() throws Exception {
    try (Rig r = new Rig()) {
      r.createAndClose(P);
      r.fs1.setStoragePolicy(D, LP);
      r.show("t2 after setStoragePolicy(/testAppendTwice)", P);
      assertEquals(0, r.inode(P).getLocalStoragePolicyID());
      assertEquals(15, r.inode(P).getStoragePolicyID());
      assertTarget("t2", appendThrows(r.fs2, P), P);
    }
  }

  @Test
  public void t3_tagBetweenAppendsReplacesAbce() throws Exception {
    try (Rig r = new Rig()) {
      r.createAndClose(P);
      FSDataOutputStream first = r.fs2.append(P);
      say("t3: first append succeeded");
      r.fs1.setStoragePolicy(D, LP);
      r.show("t3 after tag between appends", P);
      assertTrue(r.inode(P).isUnderConstruction());
      assertTarget("t3", appendThrows(r.fs1, P), P);
      first.close();
    }
  }

  /** The direct route is refused and the ancestor route is admitted, for the same effective state. */
  @Test
  public void t4_controlDirectRouteRefusedAndCopyOnCreateAsymmetry() throws Exception {
    try (Rig r = new Rig()) {
      r.createAndClose(P);
      RemoteException refused =
          assertThrows(RemoteException.class, () -> r.fs1.setStoragePolicy(P, LP));
      say("t4: setStoragePolicy(file, LAZY_PERSIST) refused: " + refused.getClassName() + ": "
          + refused.getMessage().split("\n", 2)[0]);
      assertTrue(refused.getMessage().contains("cannot be set after file creation"));
      assertEquals(0, r.inode(P).getLocalStoragePolicyID());
      assertEquals(0, r.inode(P).getStoragePolicyID());
      r.fs2.append(P).close();
      say("t4: append still works after the refusal");

      r.fs1.setStoragePolicy(D, LP);
      r.show("t4 old file after directory tag", P);
      assertTarget("t4 old file", appendThrows(r.fs2, P), P);

      Path fresh = new Path(D, "created_after_tag");
      r.createAndClose(fresh);
      r.show("t4 new file created under the tag", fresh);
      assertEquals(15, r.inode(fresh).getLocalStoragePolicyID());
      assertTarget("t4 new file", appendThrows(r.fs2, fresh), fresh);

      r.fs1.unsetStoragePolicy(D);
      r.show("t4 old file after unset", P);
      r.show("t4 new file after unset", fresh);
      assertEquals(0, r.inode(P).getStoragePolicyID());
      assertEquals(15, r.inode(fresh).getStoragePolicyID());
      r.fs2.append(P).close();
      say("t4: old file appendable again after unset; new file stays stamped");
      assertTarget("t4 new file after unset", appendThrows(r.fs2, fresh), fresh);
    }
  }

  /**
   * The second block keeps the restarted NameNode in safe mode until the DataNode has reported: the
   * threshold of 0.999 of one block truncates to 0, and t10 covers that case.
   */
  @Test
  public void t5_permanence() throws Exception {
    try (Rig r = new Rig()) {
      r.createAndClose(P);
      r.createAndClose(new Path(D, "second_block"));
      r.fs1.setStoragePolicy(ROOT, LP);
      assertTarget("t5 immediately", appendThrows(r.fs2, P), P);

      Thread.sleep(10000);
      assertTarget("t5 retry after 10s", appendThrows(r.fs2, P), P);

      // A client from before the restart holds a dead IPC connection; each step uses a fresh one.
      r.cluster.restartNameNode(true);
      r.show("t5 after NameNode restart (edit log replay)", P);
      try (FileSystem fresh = AppendTestUtil.createHdfsWithDifferentUsername(r.conf)) {
        assertTarget("t5 after restart from edits", appendThrows(fresh, P), P);
      }

      r.fs1.setSafeMode(SafeModeAction.ENTER);
      r.fs1.saveNamespace();
      r.fs1.setSafeMode(SafeModeAction.LEAVE);
      r.cluster.restartNameNode(true);
      r.show("t5 after checkpoint and NameNode restart (fsimage)", P);
      try (FileSystem fresh = AppendTestUtil.createHdfsWithDifferentUsername(r.conf)) {
        assertTarget("t5 after restart from fsimage", appendThrows(fresh, P), P);
      }

      r.fs1.unsetStoragePolicy(ROOT);
      r.show("t5 after explicit unset of /", P);
      byte[] extra = "appended-after-unset".getBytes(StandardCharsets.UTF_8);
      try (FileSystem fresh = AppendTestUtil.createHdfsWithDifferentUsername(r.conf);
          FSDataOutputStream out = fresh.append(P)) {
        out.write(extra);
      }
      long newLen = r.fs1.getFileStatus(P).getLen();
      say("t5: append works only after the explicit unset, len=" + newLen);
      assertEquals(LEN + extra.length, newLen);
    }
  }

  /** A real end-user tool, with the same command working before the tag. */
  @Test
  public void t6_consumerFsShellAppendToFile() throws Exception {
    File local = File.createTempFile("mc1", ".txt");
    Files.write(local.toPath(), "x".getBytes(StandardCharsets.UTF_8));
    try (Rig r = new Rig()) {
      r.createAndClose(P);
      String[] argv = {"-appendToFile", local.getPath(), P.toString()};

      assertEquals(0, shell(r.conf, argv, "t6 before tag"));
      r.fs1.setStoragePolicy(D, LP);
      int rc = shell(r.conf, argv, "t6 after tag");
      assertNotEquals(0, rc);
    } finally {
      local.delete();
    }
  }

  private static int shell(Configuration conf, String[] argv, String label) throws Exception {
    PrintStream savedErr = System.err;
    ByteArrayOutputStream buf = new ByteArrayOutputStream();
    System.setErr(new PrintStream(buf, true, "UTF-8"));
    int rc;
    try {
      rc = ToolRunner.run(new FsShell(conf), argv);
    } finally {
      System.setErr(savedErr);
    }
    String err = buf.toString("UTF-8");
    say(label + ": hdfs dfs " + String.join(" ", argv) + " exit=" + rc);
    say(label + ": stderr:\n" + err);
    if (rc != 0) {
      assertTrue(err.contains(TARGET_MSG + P), err);
    }
    return rc;
  }

  @Test
  public void t7_reachNonAdminWithoutWriteAccessToFile() throws Exception {
    try (Rig r = new Rig()) {
      Path shared = new Path("/shared");
      r.fs1.mkdirs(shared);
      r.fs1.setPermission(shared, new FsPermission((short) 0777));
      FileSystem alice = DFSTestUtil.getFileSystemAs(
          UserGroupInformation.createUserForTesting("mc1alice", new String[] {"mc1users"}), r.conf);
      FileSystem bob = DFSTestUtil.getFileSystemAs(
          UserGroupInformation.createUserForTesting("mc1bob", new String[] {"mc1users"}), r.conf);
      Path file = new Path(shared, "alice.dat");
      try (FSDataOutputStream out = alice.create(file, (short) 1)) {
        out.write(AppendTestUtil.initBuffer(LEN));
      }
      alice.append(file).close();
      say("t7: owner append works before the tag; file mode "
          + r.fs1.getFileStatus(file).getPermission());
      assertThrows(AccessControlException.class, () -> bob.append(file));
      say("t7: non-admin bob has no write access to the file (AccessControlException on append)");
      bob.setStoragePolicy(shared, LP);
      r.show("t7 after bob tagged /shared", file);
      assertTarget("t7 owner append", appendThrows(alice, file), file);
      alice.close();
      bob.close();
    }
  }

  /** Context CR-2, FSDirTruncateOp.java:100-102: same mechanism, outside TargetSafe. */
  @Test
  public void t8_contextTruncateGuard() throws Exception {
    try (Rig r = new Rig()) {
      r.createAndClose(P);
      r.fs1.setStoragePolicy(D, LP);
      // DFSClient.truncate does not unwrap this class, so the caller gets a RemoteException.
      RemoteException e = assertThrows(RemoteException.class, () -> r.fs2.truncate(P, LEN / 2));
      String frame = "";
      for (String line : e.getMessage().split("\n")) {
        if (line.contains("FSDirTruncateOp.truncate(")) {
          frame = line.trim();
          break;
        }
      }
      say("t8: truncate caught RemoteException(" + e.getClassName() + "): "
          + e.getMessage().split("\n", 2)[0]);
      say("t8: NameNode stack frame: " + frame);
      assertEquals(UnsupportedOperationException.class.getName(), e.getClassName());
      r.fs1.unsetStoragePolicy(D);
      r.fs2.truncate(P, LEN / 2);
      say("t8: truncate accepted after unset");
    }
  }

  /**
   * Context T-1, FSNamesystem.java:4702, outside TargetSafe. Both files are DISK files with one
   * replica on the same DataNode, and the DataNode comes back with its disks intact. The scrub and
   * heartbeat intervals use the keys of LazyPersistTestCase, only to compress time.
   */
  @Test
  public void t9_contextScrubberDeletesDiskFileAfterTransientOutage() throws Exception {
    Configuration conf = new HdfsConfiguration();
    conf.setInt(DFSConfigKeys.DFS_NAMENODE_LAZY_PERSIST_FILE_SCRUB_INTERVAL_SEC, 3);
    conf.setLong(DFSConfigKeys.DFS_HEARTBEAT_INTERVAL_KEY, 1);
    conf.setInt(DFSConfigKeys.DFS_NAMENODE_HEARTBEAT_RECHECK_INTERVAL_KEY, 500);
    try (Rig r = new Rig(conf)) {
      Path control = new Path("/control/bar");
      r.createAndClose(P);
      r.createAndClose(control);
      byte[] expected = AppendTestUtil.initBuffer(LEN);
      ExtendedBlock block = DFSTestUtil.getFirstBlock(r.fs1, P);
      File replica = r.cluster.getBlockFile(0, block);
      r.fs1.setStoragePolicy(D, LP);
      r.show("t9 tagged file", P);
      r.show("t9 control file", control);

      DataNodeProperties dn = r.cluster.stopDataNode(0);
      say("t9: DataNode stopped; replica file on disk: " + replica.exists());
      GenericTestUtils.waitFor(() -> {
        try {
          return !r.fs1.exists(P);
        } catch (IOException e) {
          return false;
        }
      }, 200, 120000);
      say("t9: exists(tagged)=" + r.fs1.exists(P) + " exists(control)=" + r.fs1.exists(control)
          + " missingBlocks=" + r.cluster.getNamesystem().getMissingBlocksCount()
          + " replicaFileStillOnDisk=" + replica.exists());
      assertTrue(r.fs1.exists(control));
      assertTrue(replica.exists());

      r.cluster.restartDataNode(dn, true);
      r.cluster.waitActive();
      GenericTestUtils.waitFor(() -> {
        try {
          return r.cluster.getNamesystem().getMissingBlocksCount() == 0;
        } catch (RuntimeException e) {
          return false;
        }
      }, 200, 120000);
      byte[] back = DFSTestUtil.readFileBuffer(r.fs1, control);
      say("t9: DataNode back; control readable and intact=" + Arrays.equals(expected, back)
          + "; exists(tagged)=" + r.fs1.exists(P));
      assertTrue(Arrays.equals(expected, back));
      assertFalse(r.fs1.exists(P));
    }
  }

  /**
   * Context T-1 without a DataNode fault, default configuration (scrub interval 300 s), one block in
   * the namespace: the restarted NameNode leaves safe mode at once, and the scrubber's first pass runs
   * before the DataNode re-registers. Control: the same restart with no tag keeps the file.
   */
  @Test
  public void t10_contextNameNodeRestartDeletesTaggedDiskFile() throws Exception {
    try (Rig r = new Rig()) {
      r.createAndClose(P);
      r.show("t10 control before restart", P);
      r.cluster.restartNameNode(true);
      r.cluster.waitActive();
      Thread.sleep(8000);
      say("t10 control: no tag, exists after restart=" + r.fs1.exists(P));
      assertTrue(r.fs1.exists(P));
    }
    try (Rig r = new Rig()) {
      r.createAndClose(P);
      byte[] expected = AppendTestUtil.initBuffer(LEN);
      File replica = r.cluster.getBlockFile(0, DFSTestUtil.getFirstBlock(r.fs1, P));
      r.fs1.setStoragePolicy(ROOT, LP);
      r.show("t10 tagged before restart", P);
      say("t10 tagged: length=" + r.fs1.getFileStatus(P).getLen()
          + " readable=" + Arrays.equals(expected, DFSTestUtil.readFileBuffer(r.fs1, P))
          + " replicaFileOnDisk=" + replica.exists());
      r.cluster.restartNameNode(true);
      r.cluster.waitActive();
      Thread.sleep(8000);
      boolean exists = r.fs1.exists(P);
      say("t10 tagged: exists after restart=" + exists + " replicaFileOnDisk=" + replica.exists());
      assertFalse(exists);
    }
  }
}
