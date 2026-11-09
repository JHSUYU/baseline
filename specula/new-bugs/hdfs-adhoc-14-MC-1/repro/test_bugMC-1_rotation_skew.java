/*
 * MC-1 reproduction (Specula ad hoc target hdfs-adhoc-14).
 *
 * Installed by test_bugMC-1_rotation_skew.sh as
 *   hadoop-hdfs-project/hadoop-hdfs/src/test/java/org/apache/hadoop/hdfs/SpeculaAdhoc14MC1Test.java
 *
 * Variant of the workload TestEncryptedTransfer#testEncryptedReadDefaultAlgorithmCipherSuite[1]:
 * resolverClazz = null (data()[0], invocation [1]), algorithm "", cipher suites "",
 * setEncryptionConfigKeys() and getFileSystem() copied from that test.
 * It adds only what the counterexample's configuration uses:
 *   - dfs.encrypt.data.overwrite.downstream.derived.qop = true   (documented, hdfs-default.xml)
 *   - dfs.block.access.key.update.interval = 1 (minutes)          (documented config key; time
 *     compression only. The NameNode's own HeartbeatManager.Monitor rotates the key.)
 * Workload: a few writers that create small files (more rounds of the same operation).
 * No fault injection. No write to the guard's operands. No change to the target method.
 * The only test utilities used are log-level and log-capture settings (log4j) and read-only
 * getters (getCurrentKey) to print the key state.
 *
 * Counterexample (s1_rotation_skew_w1_steady.out): NNRotate -> MarkKeyUpdate -> ClientAddBlock(<<d1,d2>>)
 * -> client connects d1 -> d1 TargetCheck passes -> d1 WriteBlockMirrorSecret re-signs with dnCur=1
 * keeping kid=2 -> d2 TargetCheck fails (BTSM:418).
 */
package org.apache.hadoop.hdfs;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Supplier;

import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.fs.FSDataOutputStream;
import org.apache.hadoop.fs.FileSystem;
import org.apache.hadoop.fs.Path;
import org.apache.hadoop.hdfs.client.HdfsClientConfigKeys;
import org.apache.hadoop.hdfs.protocol.DatanodeInfo;
import org.apache.hadoop.hdfs.protocol.datatransfer.sasl.SaslDataTransferClient;
import org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.security.token.SecretManager.InvalidToken;
import org.apache.log4j.Appender;
import org.apache.log4j.AppenderSkeleton;
import org.apache.log4j.Level;
import org.apache.log4j.Logger;
import org.apache.log4j.spi.LoggingEvent;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

public class SpeculaAdhoc14MC1Test {

  private static final String PLAIN_TEXT = "this is very secret plain text";
  /** The target's throw site, as a JVM stack frame. */
  static final String TARGET_FRAME =
      "org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager"
      + ".checkAccess(BlockTokenSecretManager.java:418)";

  private MiniDFSCluster cluster = null;
  private Configuration conf = null;
  private FileSystem fs = null;
  private Collector collector = null;
  private final List<Logger> attached = new ArrayList<>();
  private final long t0 = System.currentTimeMillis();

  private static void out(String s) {
    System.out.println("MC1| " + s);
    System.out.flush();
  }

  private long rel() {
    return System.currentTimeMillis() - t0;
  }

  // ---- copied from TestEncryptedTransfer (resolverClazz == null) ----
  private void setEncryptionConfigKeys() {
    conf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, true);
    conf.setBoolean(DFSConfigKeys.DFS_BLOCK_ACCESS_TOKEN_ENABLE_KEY, true);
  }

  // Unset DFS_ENCRYPT_DATA_TRANSFER_KEY and DFS_DATA_ENCRYPTION_ALGORITHM_KEY
  // on the client side to ensure that clients will detect this setting
  // automatically from the NN.
  private static FileSystem getFileSystem(Configuration conf) throws IOException {
    Configuration localConf = new Configuration(conf);
    localConf.setBoolean(DFSConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_KEY, false);
    localConf.unset(DFSConfigKeys.DFS_DATA_ENCRYPTION_ALGORITHM_KEY);
    return FileSystem.get(localConf);
  }
  // ---- end copy ----

  @AfterEach
  public void teardown() throws IOException {
    for (Logger l : attached) {
      l.removeAppender(collector);
    }
    attached.clear();
    if (fs != null) {
      fs.close();
    }
    if (cluster != null) {
      cluster.shutdown();
    }
  }

  /** CE topology: 3 DataNodes, pipelines of 3, overwrite flag on. */
  @Test
  @Timeout(600)
  public void testRotationSkewOverwriteOn() throws Exception {
    Result r = runScenario("trigger-3dn", true, 3, (short) 3, 2);
    assertTrue(r.fired418 > 0,
        "expected InvalidToken thrown at " + TARGET_FRAME);
  }

  /** Same as above with the overwrite flag off (negative control). */
  @Test
  @Timeout(600)
  public void testRotationSkewOverwriteOffControl() throws Exception {
    Result r = runScenario("control-3dn-flag-off", false, 3, (short) 3, 2);
    assertEquals(0, r.fired418,
        "control: no InvalidToken at " + TARGET_FRAME + " expected with flag off");
  }

  /**
   * Consequence: more DataNodes, so all of the client's
   * dfs.client.block.write.retries (default 3, i.e. 4 attempts) can get a
   * pipeline of >= 2 nodes inside the skew window.
   */
  @Test
  @Timeout(600)
  public void testRotationSkewOverwriteOnSixDns() throws Exception {
    Result r = runScenario("trigger-6dn", true, 6, (short) 3, 2);
    assertTrue(r.fired418 > 0,
        "expected InvalidToken thrown at " + TARGET_FRAME);
  }

  // ------------------------------------------------------------------------

  static final class Result {
    int fired418;
    int writesOk;
    int writesDegraded;
    int writesFailed;
  }

  private Result runScenario(String name, boolean overwrite, int numDns,
      short repl, int rotationsToObserve) throws Exception {
    conf = new Configuration();
    // Encryption algorithm and cipher suites are left UNSET (negotiable), as in
    // TestEncryptedTransfer#testEncryptedWrite*. The workload sets them to "".
    // A DataNode passes its own dnConf.encryptionAlgorithm ("") to DIGEST-MD5
    // for DN->DN connections (DNConf.java:253, DataNode.java:2142), while the
    // client maps "" to null (PBHelperClient.java:1739). With "" every DN->DN
    // handshake fails ("Unable to negotiate a strength level for 'auth-conf'"),
    // independent of this finding. That is first run, run1-trigger3dn.txt.
    if (System.getProperty("mc1.emptyAlgorithm") != null
        || System.getenv("MC1_EMPTY_ALGORITHM") != null) {
      conf.set(DFSConfigKeys.DFS_DATA_ENCRYPTION_ALGORITHM_KEY, "");
      conf.set(HdfsClientConfigKeys.DFS_ENCRYPT_DATA_TRANSFER_CIPHER_SUITES_KEY, "");
    }
    setEncryptionConfigKeys();
    // the counterexample's configuration
    conf.setBoolean(
        DFSConfigKeys.DFS_ENCRYPT_DATA_OVERWRITE_DOWNSTREAM_DERIVED_QOP_KEY,
        overwrite);
    // time compression via the documented key (unit: minutes, smallest value)
    conf.setLong(DFSConfigKeys.DFS_BLOCK_ACCESS_KEY_UPDATE_INTERVAL_KEY, 1L);

    installCollector();

    out("==== scenario " + name + ": overwrite.downstream.derived.qop="
        + overwrite + " numDataNodes=" + numDns + " replication=" + repl
        + " key.update.interval=1min heartbeat.interval="
        + conf.getLong(DFSConfigKeys.DFS_HEARTBEAT_INTERVAL_KEY,
            DFSConfigKeys.DFS_HEARTBEAT_INTERVAL_DEFAULT) + "s");
    out("classpath check: SaslDataTransferClient from "
        + SaslDataTransferClient.class.getProtectionDomain().getCodeSource()
            .getLocation());
    out("classpath check: DataNode from "
        + DataNode.class.getProtectionDomain().getCodeSource().getLocation());
    boolean instrumented;
    try {
      Class.forName("org.apache.hadoop.hdfs.SpeculaTrace");
      instrumented = true;
    } catch (ClassNotFoundException e) {
      instrumented = false;
    }
    out("classpath check: Specula instrumentation present = " + instrumented);

    cluster = new MiniDFSCluster.Builder(conf).numDataNodes(numDns).build();
    cluster.waitActive();
    fs = getFileSystem(conf);
    final String bpid = cluster.getNamesystem().getBlockPoolId();
    final BlockTokenSecretManager nnBtsm =
        cluster.getNamesystem().getBlockManager().getBlockTokenSecretManager();
    final Supplier<String> snap = () -> {
      try {
        StringBuilder sb = new StringBuilder("NN.currentKey=")
            .append(nnBtsm.getCurrentKey().getKeyId());
        for (DataNode dn : cluster.getDataNodes()) {
          sb.append(" DN@").append(dn.getXferPort()).append(".currentKey=")
              .append(dn.getBlockPoolTokenSecretManager().get(bpid)
                  .getCurrentKey().getKeyId());
        }
        return sb.toString();
      } catch (Throwable t) {
        return "snapshot-failed: " + t;
      }
    };
    collector.snap = snap;
    out("t=" + rel() + "ms cluster up; " + snap.get());

    // writers
    final AtomicBoolean stop = new AtomicBoolean(false);
    final AtomicInteger ok = new AtomicInteger();
    final AtomicInteger degraded = new AtomicInteger();
    final AtomicInteger failed = new AtomicInteger();
    final List<String> failures = Collections.synchronizedList(new ArrayList<>());
    final List<String> degradedSamples =
        Collections.synchronizedList(new ArrayList<>());
    final int numWriters = 4;
    List<Thread> writers = new ArrayList<>();
    for (int w = 0; w < numWriters; w++) {
      final int id = w;
      Thread t = new Thread(() -> {
        int i = 0;
        while (!stop.get()) {
          Path p = new Path("/mc1/" + name + "/w" + id + "/f" + (i++));
          FSDataOutputStream o = null;
          try {
            o = fs.create(p, true, 4096, repl, 1024 * 1024);
            o.write(PLAIN_TEXT.getBytes(StandardCharsets.UTF_8));
            o.hflush();
            DatanodeInfo[] pipe =
                ((DFSOutputStream) o.getWrappedStream()).getPipeline();
            o.close();
            o = null;
            ok.incrementAndGet();
            if (pipe != null && pipe.length < repl) {
              degraded.incrementAndGet();
              if (degradedSamples.size() < 10) {
                degradedSamples.add("t=" + rel() + "ms " + p
                    + " written with pipeline of " + pipe.length + "/" + repl
                    + " nodes: " + java.util.Arrays.toString(pipe));
              }
            }
          } catch (IOException e) {
            failed.incrementAndGet();
            if (failures.size() < 20) {
              failures.add("t=" + rel() + "ms " + p + " -> " + e);
            }
            if (o != null) {
              try {
                o.close();
              } catch (IOException ignored) {
                // stream already failed
              }
            }
          }
        }
      }, "mc1-writer-" + w);
      writers.add(t);
      t.start();
    }

    // observe rotations of the NameNode key and when each DN applies it
    int lastNnKey = nnBtsm.getCurrentKey().getKeyId();
    int rotations = 0;
    long lastRotationAt = -1;
    long deadline = System.currentTimeMillis() + 200_000L;
    List<DataNode> dns = cluster.getDataNodes();
    int[] dnKey = new int[dns.size()];
    for (int i = 0; i < dns.size(); i++) {
      dnKey[i] = dns.get(i).getBlockPoolTokenSecretManager().get(bpid)
          .getCurrentKey().getKeyId();
    }
    while (System.currentTimeMillis() < deadline) {
      int k = nnBtsm.getCurrentKey().getKeyId();
      if (k != lastNnKey) {
        rotations++;
        lastRotationAt = System.currentTimeMillis();
        out("t=" + rel() + "ms NameNode rotated block key " + lastNnKey + " -> "
            + k + " (rotation #" + rotations + "); " + snap.get());
        lastNnKey = k;
      }
      for (int i = 0; i < dns.size(); i++) {
        int dk = dns.get(i).getBlockPoolTokenSecretManager().get(bpid)
            .getCurrentKey().getKeyId();
        if (dk != dnKey[i]) {
          out("t=" + rel() + "ms DN@" + dns.get(i).getXferPort()
              + " applied KeyUpdateCommand: currentKey " + dnKey[i] + " -> " + dk
              + (lastRotationAt > 0 ? " (" + (System.currentTimeMillis()
                  - lastRotationAt) + "ms after NN rotation)" : ""));
          dnKey[i] = dk;
        }
      }
      if (rotations >= rotationsToObserve
          && System.currentTimeMillis() - lastRotationAt > 8000) {
        break;
      }
      Thread.sleep(20);
    }
    stop.set(true);
    for (Thread t : writers) {
      t.join(60_000);
    }

    // ---- report ----
    Result r = new Result();
    r.fired418 = collector.at418.get();
    r.writesOk = ok.get();
    r.writesDegraded = degraded.get();
    r.writesFailed = failed.get();
    out("---- summary " + name + " ----");
    out("NN key rotations observed: " + rotations);
    out("writes ok=" + ok.get() + " (with pipeline shorter than replication: "
        + degraded.get() + "), writes failed at the application=" + failed.get());
    out("DataNode 'DataNode overwriting downstream QOP' (mirror re-sign) events: "
        + collector.overwriteCount.get());
    out("InvalidToken events logged by DataXceiver: "
        + collector.invalidTokenCount.get() + ", with top frame " + TARGET_FRAME
        + ": " + collector.at418.get());
    out("DN WARN 'Block token verification failed' events: "
        + collector.verifyFailedCount.get());
    out("client 'Exception in createBlockOutputStream' with InvalidBlockToken: "
        + collector.clientTokenErrors.get() + ", 'Abandoning': "
        + collector.abandonCount.get() + ", 'Excluding datanode': "
        + collector.excludingCount.get());
    synchronized (collector.samples) {
      for (String s : collector.samples) {
        out(s);
      }
    }
    if (collector.firstTrace != null) {
      out("first InvalidToken stack trace (as logged by DataXceiver.run at TRACE):");
      for (String line : collector.firstTrace.split("\n")) {
        out("  " + line);
      }
    }
    synchronized (degradedSamples) {
      for (String s : degradedSamples) {
        out("degraded write: " + s);
      }
    }
    synchronized (failures) {
      for (String s : failures) {
        out("application write failure: " + s);
      }
    }
    out("RESULT " + name + " fired418=" + r.fired418 + " writesOk=" + r.writesOk
        + " writesDegraded=" + r.writesDegraded + " writesFailed="
        + r.writesFailed);
    return r;
  }

  private void installCollector() {
    collector = new Collector();
    // Keep the console at INFO so that TRACE on the DataNode logger only
    // reaches the collector.
    Appender stdout = Logger.getRootLogger().getAppender("stdout");
    if (stdout instanceof AppenderSkeleton) {
      ((AppenderSkeleton) stdout).setThreshold(Level.INFO);
    }
    // DataXceiver.LOG == DataNode.LOG; DataXceiver.run logs the InvalidToken
    // (with its stack trace) at TRACE (DataXceiver.java:327-331).
    attach(Logger.getLogger(DataNode.class), Level.TRACE);
    // "DataNode overwriting downstream QOP" (SaslDataTransferClient.java:321)
    attach(Logger.getLogger(SaslDataTransferClient.class), Level.DEBUG);
    // client-side pipeline errors
    attach(Logger.getLogger("org.apache.hadoop.hdfs.DataStreamer"), Level.INFO);
    attach(Logger.getLogger(BlockTokenSecretManager.class), Level.INFO);
  }

  private void attach(Logger l, Level level) {
    l.setLevel(level);
    l.addAppender(collector);
    attached.add(l);
  }

  /** Collects the evidence from the loggers above. */
  final class Collector extends AppenderSkeleton {
    final AtomicInteger invalidTokenCount = new AtomicInteger();
    final AtomicInteger at418 = new AtomicInteger();
    final AtomicInteger verifyFailedCount = new AtomicInteger();
    final AtomicInteger overwriteCount = new AtomicInteger();
    final AtomicInteger clientTokenErrors = new AtomicInteger();
    final AtomicInteger abandonCount = new AtomicInteger();
    final AtomicInteger excludingCount = new AtomicInteger();
    final List<String> samples = Collections.synchronizedList(new ArrayList<>());
    volatile String firstTrace = null;
    volatile Supplier<String> snap = () -> "";

    private void sample(String s) {
      if (samples.size() < 40) {
        samples.add(s);
      }
    }

    @Override
    protected void append(LoggingEvent e) {
      Throwable th = e.getThrowableInformation() == null ? null
          : e.getThrowableInformation().getThrowable();
      if (th == null && e.getLevel() == Level.TRACE) {
        return;
      }
      String msg = e.getRenderedMessage();
      if (msg == null) {
        msg = "";
      }
      if (th instanceof InvalidToken) {
        invalidTokenCount.incrementAndGet();
        StackTraceElement[] st = th.getStackTrace();
        boolean top = st.length > 0 && st[0].toString().equals(TARGET_FRAME);
        if (top) {
          int n = at418.incrementAndGet();
          if (n <= 3) {
            sample("t=" + rel() + "ms TARGET FIRED #" + n + " [" + e.getThreadName()
                + "] " + msg + " :: " + th + " :: key state at this instant: "
                + snap.get());
          }
          if (firstTrace == null) {
            StringWriter sw = new StringWriter();
            th.printStackTrace(new PrintWriter(sw));
            firstTrace = msg + "\n" + sw;
          }
        } else if (invalidTokenCount.get() <= 3) {
          sample("t=" + rel() + "ms other InvalidToken (top frame "
              + (st.length > 0 ? st[0] : "?") + "): " + th);
        }
        return;
      }
      if (msg.startsWith("Block token verification failed")) {
        if (verifyFailedCount.incrementAndGet() <= 3) {
          sample("t=" + rel() + "ms DN WARN: " + msg);
        }
      } else if (msg.startsWith("DataNode overwriting downstream QOP")) {
        overwriteCount.incrementAndGet();
      } else if (msg.startsWith("Exception in createBlockOutputStream")) {
        if (th != null && th.toString().contains("InvalidBlockTokenException")) {
          if (clientTokenErrors.incrementAndGet() <= 3) {
            sample("t=" + rel() + "ms CLIENT WARN: " + msg + " :: " + th);
          }
        }
      } else if (msg.startsWith("Abandoning")) {
        abandonCount.incrementAndGet();
      } else if (msg.startsWith("Excluding datanode")) {
        if (excludingCount.incrementAndGet() <= 3) {
          sample("t=" + rel() + "ms CLIENT WARN: " + msg);
        }
      } else if (msg.startsWith("Updating block keys")) {
        sample("t=" + rel() + "ms NN BTSM INFO: " + msg + " [" + e.getThreadName()
            + "]");
      }
    }

    @Override
    public void close() {
    }

    @Override
    public boolean requiresLayout() {
      return false;
    }
  }
}
