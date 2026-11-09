/*
 * Specula reproduction for finding MC-1:
 *   "Balancer/Mover data-encryption key is never refreshed and outlives its
 *    block key on every DataNode".
 *
 * Variant of the workload test TestBalancerWithEncryptedTransfer
 * (same module, same package). Escalation level 0: only public configuration
 * keys and normal operations (MiniDFSCluster, file write, add a DataNode,
 * Balancer.run -- the same entry point Balancer.Cli uses). No fault injection,
 * no state injection, no source change, no test-only setter.
 *
 * Configuration: dfs.block.access.key.update.interval = 1 (minute) and
 * dfs.block.access.token.lifetime = 1 (minute) -- the smallest valid values of
 * these minute-granular keys. dfs.balancer.max-size-to-move = 100 bytes (one
 * 100-byte block per iteration) and a 5 s redundancy interval only make the
 * Balancer run long enough (several key rolls) -- the same situation as a
 * production Balancer run lasting ~2I+L at default 600-min settings.
 *
 * Install as hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/server/balancer/
 *   TestBugMC1StaleBalancerDek.java
 */
package org.apache.hadoop.hdfs.server.balancer;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import java.net.URI;
import java.util.Collection;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.hdfs.DFSConfigKeys;
import org.apache.hadoop.hdfs.DFSUtil;
import org.apache.hadoop.hdfs.HdfsConfiguration;
import org.apache.hadoop.hdfs.MiniDFSCluster;
import org.apache.hadoop.hdfs.NameNodeProxies;
import org.apache.hadoop.hdfs.protocol.ClientProtocol;
import org.apache.hadoop.hdfs.protocol.DatanodeInfo;
import org.apache.hadoop.hdfs.protocol.HdfsConstants.DatanodeReportType;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.test.GenericTestUtils;
import org.apache.hadoop.test.GenericTestUtils.LogCapturer;
import org.apache.hadoop.util.Time;
import org.junit.Test;

public class TestBugMC1StaleBalancerDek {
  private static final long BLOCK = TestBalancer.DEFAULT_BLOCK_SIZE; // 100 B
  private static final long CAPACITY = 40000L;     // 400 blocks per DN
  private static final long FILE_LEN = 240 * BLOCK; // DN0 at 60 %

  // The target statement `throw new InvalidEncryptionKeyException(...)` spans
  // BlockTokenSecretManager.java:482-484. javap's LineNumberTable maps `new` to
  // line 482 and the constructor call (where the stack trace is filled in) to
  // line 484, so the JVM reports the frame as :484 for the line-482 throw.
  // The method has no other throw site.
  private static final String FRAME =
      "BlockTokenSecretManager.retrieveDataEncryptionKey(BlockTokenSecretManager.java:484)";

  private static void printUtil(String tag, ClientProtocol client)
      throws Exception {
    for (DatanodeInfo d : client.getDatanodeReport(DatanodeReportType.LIVE)) {
      System.out.println("MC1 " + tag + " dn=" + d.getXferAddr()
          + " used=" + d.getDfsUsed() + " cap=" + d.getCapacity()
          + " util=" + String.format("%.1f%%", 100.0 * d.getDfsUsed() / d.getCapacity()));
    }
  }

  private static int count(String s, String needle) {
    int c = 0;
    for (int i = s.indexOf(needle); i >= 0; i = s.indexOf(needle, i + 1)) c++;
    return c;
  }

  @Test(timeout = 900000)
  public void testLongBalancerRunOutlivesItsDek() throws Exception {
    final Configuration conf = new HdfsConfiguration();
    // --- exactly the workload test's configuration ---
    conf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, true);
    conf.setBoolean(DFSConfigKeys.DFS_BLOCK_ACCESS_TOKEN_ENABLE_KEY, true);
    TestBalancer.initConf(conf);
    // --- valid, public configuration: smallest key interval / lifetime ---
    conf.setLong(DFSConfigKeys.DFS_BLOCK_ACCESS_KEY_UPDATE_INTERVAL_KEY, 1L); // minutes
    conf.setLong(DFSConfigKeys.DFS_BLOCK_ACCESS_TOKEN_LIFETIME_KEY, 1L);      // minutes
    // --- make one Balancer run span several key rolls ---
    conf.setLong(DFSConfigKeys.DFS_NAMENODE_REDUNDANCY_INTERVAL_SECONDS_KEY, 5L);
    conf.setLong(DFSConfigKeys.DFS_BALANCER_MAX_SIZE_TO_MOVE_KEY, BLOCK);

    MiniDFSCluster cluster = new MiniDFSCluster.Builder(conf).numDataNodes(1)
        .racks(new String[] {TestBalancer.RACK0})
        .simulatedCapacities(new long[] {CAPACITY}).build();
    final long t0 = Time.monotonicNow();
    try {
      cluster.waitActive();
      ClientProtocol client = NameNodeProxies.createProxy(conf,
          cluster.getFileSystem(0).getUri(), ClientProtocol.class).getProxy();
      TestBalancer.createFile(cluster, new Path("/mc1.dat"), FILE_LEN,
          (short) 1, 0);
      cluster.startDataNodes(conf, 1, true, null,
          new String[] {TestBalancer.RACK1}, new long[] {CAPACITY});
      cluster.waitActive();
      TestBalancer.waitForHeartBeat(FILE_LEN, 2 * CAPACITY, client, cluster);
      printUtil("before-balancer", client);

      LogCapturer dnLogs = GenericTestUtils.LogCapturer.captureLogs(DataNode.LOG);
      LogCapturer dispLogs = GenericTestUtils.LogCapturer.captureLogs(Dispatcher.LOG);

      Collection<URI> namenodes = DFSUtil.getInternalNsRpcUris(conf);
      final long tb = Time.monotonicNow();
      System.out.println("MC1 balancer-1 start at t=" + (tb - t0) / 1000 + "s");
      int r1 = Balancer.run(namenodes, BalancerParameters.DEFAULT, conf);
      final long te = Time.monotonicNow();
      System.out.println("MC1 balancer-1 exit=" + r1 + " ("
          + exitName(r1) + ") at t=" + (te - t0) / 1000 + "s, ran "
          + (te - tb) / 1000 + "s");
      printUtil("after-balancer-1", client);

      String dn = dnLogs.getOutput();
      String disp = dispLogs.getOutput();
      dnLogs.stopCapturing();
      dispLogs.stopCapturing();
      int ok = count(disp, "Successfully moved");
      int failed = count(disp, "Failed to move");
      int failedIEK = count(disp,
          "InvalidEncryptionKeyException: Can't re-compute encryption key");
      System.out.println("MC1 balancer-1 moves: succeeded=" + ok
          + " failed=" + failed + " failedWithInvalidEncryptionKey=" + failedIEK);
      int dnFrames = count(dn, FRAME);
      System.out.println("MC1 DataNode-side frames '" + FRAME + "': " + dnFrames);
      int i = dn.indexOf("DataXceiver error processing");
      if (i >= 0) {
        int j = dn.indexOf(FRAME, i);
        int end = (j >= 0) ? dn.indexOf('\n', j + 1) : Math.min(dn.length(), i + 3000);
        System.out.println("MC1 first DataNode error (excerpt):\n"
            + dn.substring(Math.max(0, dn.lastIndexOf('\n', i) + 1), end));
      }
      int k = disp.indexOf("Failed to move");
      if (k >= 0) {
        System.out.println("MC1 first Dispatcher failure (excerpt):\n"
            + disp.substring(Math.max(0, disp.lastIndexOf('\n', k) + 1),
                Math.min(disp.length(), disp.indexOf('\n', disp.indexOf('\n', k) + 1) + 1)));
      }

      // ---- control: a fresh Balancer run (fresh KeyManager / fresh DEK) on
      // the very same cluster, allowed to move everything in one iteration.
      Configuration conf2 = new Configuration(conf);
      conf2.unset(DFSConfigKeys.DFS_BALANCER_MAX_SIZE_TO_MOVE_KEY);
      LogCapturer dispLogs2 = GenericTestUtils.LogCapturer.captureLogs(Dispatcher.LOG);
      int r2 = Balancer.run(namenodes, BalancerParameters.DEFAULT, conf2);
      String disp2 = dispLogs2.getOutput();
      dispLogs2.stopCapturing();
      System.out.println("MC1 control balancer-2 (fresh DEK) exit=" + r2 + " ("
          + exitName(r2) + "), succeeded=" + count(disp2, "Successfully moved")
          + " failedWithInvalidEncryptionKey=" + count(disp2,
              "InvalidEncryptionKeyException"));
      printUtil("after-balancer-2", client);

      // ---- oracle: the target check fired on the DataNode, and it broke the
      // long-lived Balancer run, while a fresh run on the same cluster works.
      assertTrue("target check (throw at BlockTokenSecretManager.java:482-484) never fired",
          dnFrames > 0);
      assertTrue("no Balancer move failed with InvalidEncryptionKeyException",
          failedIEK > 0);
      assertTrue("balancer-1 should not have succeeded",
          r1 != ExitStatus.SUCCESS.getExitCode());
      assertEquals("control run with a fresh DEK should balance",
          ExitStatus.SUCCESS.getExitCode(), r2);
      System.out.println("MC1 RESULT: BUG TRIGGERED");
    } finally {
      cluster.shutdown();
    }
  }

  private static String exitName(int code) {
    for (ExitStatus s : ExitStatus.values()) {
      if (s.getExitCode() == code) return s.name();
    }
    return "?";
  }
}
