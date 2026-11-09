/*
 * CR-4 reproduction: DFSInputStream positional read (pread) adds the DataNode
 * that rejected a stale DataEncryptionKey to deadNodes, although it has just
 * cleared the DEK and would succeed on that same DN with a fresh key.
 *
 * Install as hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/TestBugCR4PreadDek.java
 * (class name below). Variant of TestEncryptedTransfer#testLongLivedReadClientAfterRestart
 * (the workload's sibling in the same test class): only public APIs + MiniDFSCluster
 * restartNameNode / restartDataNode(s) (Level 0). No source modification, no state injection.
 *
 * The stale DEK is produced by the real sequence: client reads (caches DEK from NN #1),
 * NN restarts (fresh BlockTokenSecretManager keys), DN restarts (only knows NN #2's keys),
 * client preads -> DN BlockTokenSecretManager.retrieveDataEncryptionKey:424 throws
 * InvalidEncryptionKeyException -> client DFSInputStream.fetchBlockByteRange:965-971.
 */
package org.apache.hadoop.hdfs;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import java.io.IOException;
import java.io.OutputStream;
import java.lang.reflect.Field;
import java.util.Map;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.FSDataInputStream;
import org.apache.hadoop.fs.FileSystem;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.hdfs.protocol.DatanodeInfo;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.junit.Test;

public class TestBugCR4PreadDek {
  private static final String PLAIN_TEXT = "this is very secret plain text";
  private static final Path TEST_PATH = new Path("/cr4-file");

  private MiniDFSCluster cluster;
  private FileSystem fs;

  private static void out(String s) { System.out.println("CR4: " + s); }

  /** Encrypted cluster; client caches a DEK; then NN and all DNs restart. */
  private void setupStaleDek(int numDn, int maxAcquireFailures) throws Exception {
    Configuration conf = new Configuration();
    conf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, true);
    conf.setBoolean(DFSConfigKeys.DFS_BLOCK_ACCESS_TOKEN_ENABLE_KEY, true);
    conf.setInt(DFSConfigKeys.DFS_REPLICATION_KEY, numDn);
    cluster = new MiniDFSCluster.Builder(conf).numDataNodes(numDn).build();
    cluster.waitActive();
    Configuration clientConf = new Configuration(conf);
    clientConf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, false);
    clientConf.unset(DFSConfigKeys.DFS_DATA_ENCRYPTION_ALGORITHM_KEY);
    if (maxAcquireFailures >= 0) {
      clientConf.setInt(DFSConfigKeys.DFS_CLIENT_MAX_BLOCK_ACQUIRE_FAILURES_KEY,
          maxAcquireFailures);
    }
    fs = FileSystem.newInstance(clientConf);
    OutputStream o = fs.create(TEST_PATH);
    o.write(PLAIN_TEXT.getBytes());
    o.close();
    DFSTestUtil.waitReplication(fs, TEST_PATH, (short) numDn);
    assertEquals(PLAIN_TEXT, DFSTestUtil.readFile(fs, TEST_PATH)); // caches DEK
    // NN + DN restart: the client's cached DEK keyId is now unknown to every DN.
    cluster.restartNameNode();
    assertTrue(cluster.restartDataNodes(true));
    cluster.waitActive();
    DFSTestUtil.waitReplication(fs, TEST_PATH, (short) numDn);
  }

  private void teardown() throws IOException {
    if (fs != null) fs.close();
    if (cluster != null) cluster.shutdown();
    fs = null; cluster = null;
  }

  @SuppressWarnings("unchecked")
  private static Map<DatanodeInfo, DatanodeInfo> deadNodes(FSDataInputStream in)
      throws Exception {
    DFSInputStream dis = (DFSInputStream) in.getWrappedStream();
    Field f = DFSInputStream.class.getDeclaredField("deadNodes");
    f.setAccessible(true);
    return (Map<DatanodeInfo, DatanodeInfo>) f.get(dis);
  }

  private static String pread(FSDataInputStream in) throws IOException {
    byte[] buf = new byte[PLAIN_TEXT.length()];
    in.readFully(0, buf);   // positional read -> DFSInputStream.read(long,...) -> fetchBlockByteRange
    return new String(buf);
  }

  private static String statefulRead(FSDataInputStream in) throws IOException {
    byte[] buf = new byte[PLAIN_TEXT.length()];
    in.readFully(buf);      // stateful read -> readWithStrategy -> blockSeekTo
    return new String(buf);
  }

  /** (A) default config, 1 replica: pread marks the only DN dead after the DEK refetch. */
  @Test(timeout = 180000)
  public void testPreadSingleReplicaDefault() throws Exception {
    try {
      setupStaleDek(1, -1);
      LogCapturer logs = LogCapturer.captureLogs(DFSClient.LOG);
      FSDataInputStream in = fs.open(TEST_PATH);
      long t0 = System.currentTimeMillis();
      String got = pread(in);
      long ms = System.currentTimeMillis() - t0;
      in.close();
      logs.stopCapturing();
      String log = logs.getOutput();
      boolean refetch = log.contains("Will fetch a new encryption key and retry");
      boolean allDead = log.contains("from any node");
      out("A pread 1-replica default: data_ok=" + PLAIN_TEXT.equals(got)
          + " dekRefetch=" + refetch + " dnMarkedDead_allDeadPath=" + allDead
          + " elapsedMs=" + ms);
      for (String l : log.split("\n")) {
        if (l.contains("encryption key") || l.contains("from any node")
            || l.contains("chooseDataNode")) out("  log| " + l);
      }
      assertTrue(refetch);
      assertTrue("pread should have put the DN in deadNodes", allDead);
      assertEquals(PLAIN_TEXT, got);
    } finally { teardown(); }
  }

  /** (B) control: the stateful read path (blockSeekTo) retries the SAME DN, no dead-marking. */
  @Test(timeout = 180000)
  public void testStatefulReadSingleReplicaControl() throws Exception {
    try {
      setupStaleDek(1, -1);
      LogCapturer logs = LogCapturer.captureLogs(DFSClient.LOG);
      FSDataInputStream in = fs.open(TEST_PATH);
      long t0 = System.currentTimeMillis();
      String got = statefulRead(in);
      long ms = System.currentTimeMillis() - t0;
      in.close();
      logs.stopCapturing();
      String log = logs.getOutput();
      boolean refetch = log.contains("Will fetch a new encryption key and retry");
      boolean allDead = log.contains("from any node");
      out("B stateful 1-replica default: data_ok=" + PLAIN_TEXT.equals(got)
          + " dekRefetch=" + refetch + " dnMarkedDead_allDeadPath=" + allDead
          + " elapsedMs=" + ms);
      assertTrue(refetch);
      assertFalse(allDead);
      assertEquals(PLAIN_TEXT, got);
    } finally { teardown(); }
  }

  /** (C) dfs.client.max.block.acquire.failures=0: pread fails, stateful read succeeds. */
  @Test(timeout = 180000)
  public void testPreadSingleReplicaNoAcquireRetries() throws Exception {
    try {
      setupStaleDek(1, 0);
      FSDataInputStream in = fs.open(TEST_PATH);
      try {
        String got = pread(in);
        out("C pread 1-replica maxAcquire=0: SUCCEEDED data_ok=" + PLAIN_TEXT.equals(got));
      } catch (IOException e) {
        out("C pread 1-replica maxAcquire=0: FAILED " + e);
      }
      in.close();
    } finally { teardown(); }
    try {
      setupStaleDek(1, 0);
      FSDataInputStream in = fs.open(TEST_PATH);
      try {
        String got = statefulRead(in);
        out("C' stateful 1-replica maxAcquire=0: SUCCEEDED data_ok=" + PLAIN_TEXT.equals(got));
      } catch (IOException e) {
        out("C' stateful 1-replica maxAcquire=0: FAILED " + e);
      }
      in.close();
    } finally { teardown(); }
  }

  /** (D) 3 replicas: pread succeeds on the next DN, the first DN stays excluded for the stream. */
  @Test(timeout = 240000)
  public void testPreadThreeReplicasDeadNodeSticks() throws Exception {
    try {
      setupStaleDek(3, -1);
      FSDataInputStream in = fs.open(TEST_PATH);
      String got = pread(in);
      Map<DatanodeInfo, DatanodeInfo> dead = deadNodes(in);
      out("D pread 3-replica default: data_ok=" + PLAIN_TEXT.equals(got)
          + " deadNodesAfterPread=" + dead.keySet());
      String got2 = pread(in);
      out("D second pread data_ok=" + PLAIN_TEXT.equals(got2)
          + " deadNodesStill=" + deadNodes(in).keySet());
      in.close();
      assertEquals(PLAIN_TEXT, got);
      assertEquals(1, dead.size());
    } finally { teardown(); }
  }
}
