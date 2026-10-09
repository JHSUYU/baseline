import java.io.EOFException;
import java.io.FileWriter;
import java.io.IOException;
import java.io.PrintWriter;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;
import org.apache.hadoop.hdfs.MiniDFSCluster;
import org.apache.hadoop.hdfs.protocol.ExtendedBlock;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.hdfs.server.datanode.ReplicaInfo;
import org.apache.hadoop.hdfs.server.protocol.BlockRecoveryCommand.RecoveringBlock;

/** Case-local runtime identity, target oracle, and ordered I/O exception door. */
public final class RecoveryProbe {
  private static final String TRACE = System.getProperty("hdfs.recovery.trace");
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final Map<DataNode, String> SOURCES = new IdentityHashMap<>();
  private static final Map<String, Integer> RECOVERY_ORDINALS = new HashMap<>();
  private static final Map<String, Integer> IO_ORDINALS = new HashMap<>();
  private static final ThreadLocal<Context> CURRENT = new ThreadLocal<>();
  private static final ThreadLocal<String> RPC_KIND = new ThreadLocal<>();
  private static final ThreadLocal<ServerContext> SERVER = new ThreadLocal<>();
  private static final Map<String, Context> RECOVERY_BY_KEY = new HashMap<>();
  private static final List<String[]> PLAN = readPlan();
  private static int nextFault = 0;

  private static final String GET_ID = "<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: org.apache.hadoop.hdfs.protocol.DatanodeID getDatanodeID(java.lang.String)>";
  private static final String GET_ACTIVE = "<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: org.apache.hadoop.hdfs.protocolPB.DatanodeProtocolClientSideTranslatorPB getActiveNamenodeForBP(java.lang.String)>";
  private static final String INIT_SITE = "<org.apache.hadoop.hdfs.server.datanode.BlockRecoveryWorker: org.apache.hadoop.hdfs.server.protocol.ReplicaRecoveryInfo callInitReplicaRecovery(org.apache.hadoop.hdfs.server.protocol.InterDatanodeProtocol,org.apache.hadoop.hdfs.server.protocol.BlockRecoveryCommand$RecoveringBlock)>#L561";
  private static final String IPC_SITE = "<org.apache.hadoop.ipc.Client$Connection: void sendRpcRequest(org.apache.hadoop.ipc.Client$Call)>#entry";

  private static final class Context {
    String source;
    String bpid;
    long blockId;
    long recoveryId;
    int attempt;
    String root;
  }

  private static final class ServerContext {
    String serverSource;
    String ownerSource;
    String ownerRoot;
    long blockId;
    long recoveryId;
  }

  private RecoveryProbe() { }

  private static String escape(String value) {
    if (value == null) return "";
    return value.replace("\\", "\\\\").replace("\"", "\\\"")
        .replace("\n", "\\n").replace("\r", "\\r");
  }

  private static synchronized void record(String payload) {
    if (TRACE == null) return;
    try (PrintWriter out = new PrintWriter(new FileWriter(TRACE, true))) {
      out.println("{\"schemaVersion\":3,\"seq\":" + SEQUENCE.incrementAndGet()
          + ",\"thread\":\"" + escape(Thread.currentThread().getName())
          + "\"," + payload + "}");
    } catch (IOException exception) {
      throw new RuntimeException("HDFS recovery trace write failed", exception);
    }
  }

  private static List<String[]> readPlan() {
    List<String[]> plan = new ArrayList<>();
    String path = System.getProperty("hdfs.recovery.plan");
    if (path == null) return plan;
    try {
      for (String line : Files.readAllLines(Paths.get(path), StandardCharsets.UTF_8)) {
        if (line.trim().isEmpty()) continue;
        String[] fields = line.split("\\t", -1);
        if (fields.length != 6 && fields.length != 7)
          throw new IllegalArgumentException("invalid recovery plan row");
        if (fields.length == 6) {
          String[] legacy = new String[7];
          System.arraycopy(fields, 0, legacy, 0, 6);
          legacy[6] = "";
          fields = legacy;
        }
        plan.add(fields);
      }
    } catch (IOException exception) {
      throw new RuntimeException("cannot read recovery fault plan", exception);
    }
    return plan;
  }

  public static synchronized void registerCluster(MiniDFSCluster cluster) {
    List<DataNode> nodes = cluster.getDataNodes();
    for (int i = 0; i < nodes.size(); i++) {
      SOURCES.put(nodes.get(i), "dn" + i);
    }
    record("\"event\":\"CLUSTER_REGISTER\",\"dataNodes\":" + nodes.size());
  }

  private static synchronized String source(DataNode node) {
    String key = SOURCES.get(node);
    return key == null ? "unregistered" : key;
  }

  public static synchronized void beginRecovery(ExtendedBlock block,
                                                 long recoveryId, DataNode node) {
    Context context = new Context();
    context.source = source(node);
    context.bpid = block.getBlockPoolId();
    context.blockId = block.getBlockId();
    context.recoveryId = recoveryId;
    String key = context.source + "/block:" + context.blockId;
    context.attempt = RECOVERY_ORDINALS.containsKey(key)
        ? RECOVERY_ORDINALS.get(key) + 1 : 1;
    RECOVERY_ORDINALS.put(key, context.attempt);
    context.root = key + "/attempt:" + context.attempt;
    CURRENT.set(context);
    RECOVERY_BY_KEY.put(recoveryKey(context.bpid, context.blockId,
                                    context.recoveryId), context);
    RPC_KIND.remove();
    record("\"event\":\"RECOVERY_BEGIN\",\"sourceKey\":\""
        + escape(context.source) + "\",\"blockId\":" + context.blockId
        + ",\"recoveryId\":" + recoveryId + ",\"attempt\":"
        + context.attempt + ",\"occurrenceAddress\":\""
        + escape(context.root) + "\"");
  }

  private static String recoveryKey(String bpid, long blockId, long recoveryId) {
    return bpid + "/" + blockId + "/" + recoveryId;
  }

  /** Propagate the block-recovery origin to a real DataNode's dataset thread. */
  public static synchronized void beginServerRecovery(RecoveringBlock recovering,
                                                      DataNode server) {
    ExtendedBlock block = recovering.getBlock();
    long recoveryId = recovering.getNewGenerationStamp();
    Context owner = CURRENT.get();
    if (owner == null || owner.blockId != block.getBlockId()
        || owner.recoveryId != recoveryId) {
      owner = RECOVERY_BY_KEY.get(recoveryKey(block.getBlockPoolId(),
                                              block.getBlockId(), recoveryId));
    }
    ServerContext context = new ServerContext();
    context.serverSource = source(server);
    context.ownerSource = owner == null ? "unknown-origin" : owner.source;
    context.ownerRoot = owner == null ? "unknown-origin" : owner.root;
    context.blockId = block.getBlockId();
    context.recoveryId = recoveryId;
    SERVER.set(context);
    record("\"event\":\"SERVER_RECOVERY_BEGIN\",\"sourceKey\":\""
        + escape(context.serverSource) + "\",\"originSourceKey\":\""
        + escape(context.ownerSource) + "\",\"blockId\":" + context.blockId
        + ",\"recoveryId\":" + recoveryId);
  }

  /** A checked file status/length read while validating a recovering replica. */
  public static synchronized void ioFileCheck(ReplicaInfo replica,
                                               String operation) throws IOException {
    ServerContext context = SERVER.get();
    if (context == null || context.blockId != replica.getBlockId()
        || context.ownerSource.equals("unknown-origin")) return;
    String filePhase = null;
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (!frame.getClassName().equals(
          "org.apache.hadoop.hdfs.server.datanode.fsdataset.impl.FsDatasetImpl"))
        continue;
      if (frame.getMethodName().equals("initReplicaRecoveryImpl")) {
        filePhase = "initReplicaRecovery";
        break;
      }
      if (frame.getMethodName().equals("updateReplicaUnderRecovery"))
        filePhase = "updateReplicaUnderRecovery";
    }
    if (filePhase == null) return;
    if (filePhase.equals("updateReplicaUnderRecovery")) {
      // The incoming update RPC needs a separate transport context. Only
      // attribute the local update on the original coordinator thread here.
      Context owner = CURRENT.get();
      if (owner == null || owner.blockId != replica.getBlockId()
          || !owner.root.equals(context.ownerRoot)
          || !owner.source.equals(context.serverSource)) return;
    }
    String marker = "FAULT:HDFS_FILE:REPLICA_CHECK";
    String site = "<org.apache.hadoop.hdfs.server.datanode.fsdataset.impl.FsDatasetImpl: void checkReplicaFiles(org.apache.hadoop.hdfs.server.datanode.ReplicaInfo)>#"
        + operation;
    String sourceKey = context.serverSource;
    String occurrence = context.ownerRoot + "/server:" + sourceKey
        + "/file:" + operation;
    String key = marker + "|" + site + "|" + sourceKey + "|" + occurrence;
    int ordinal = IO_ORDINALS.containsKey(key) ? IO_ORDINALS.get(key) + 1 : 1;
    IO_ORDINALS.put(key, ordinal);
    String fields = "\"marker\":\"" + escape(marker)
        + "\",\"siteId\":\"" + escape(site)
        + "\",\"sourceKey\":\"" + escape(sourceKey)
        + "\",\"originSourceKey\":\"" + escape(context.ownerSource)
        + "\",\"occurrenceAddress\":\"" + escape(occurrence)
        + "\",\"hitOrdinal\":" + ordinal
        + ",\"blockId\":" + context.blockId
        + ",\"recoveryId\":" + context.recoveryId
        + ",\"filePhase\":\"" + escape(filePhase) + "\""
        + ",\"requestApi\":\"FsDatasetImpl.checkReplicaFiles."
        + escape(operation) + "\"";
    record("\"event\":\"FAULT_POINT_OBSERVED\"," + fields);
    if (nextFault >= PLAN.size()) return;
    String[] wanted = PLAN.get(nextFault);
    if (!(wanted[0].equals(marker) && wanted[1].equals(site)
          && wanted[2].equals(sourceKey) && wanted[3].equals(occurrence)
          && Integer.parseInt(wanted[4]) == ordinal
          && wanted[6].equals(filePhase))) return;
    String type = wanted[5];
    record("\"event\":\"FAULT_MATCHED\"," + fields
        + ",\"faultType\":\"" + escape(type)
        + "\",\"planIndex\":" + nextFault);
    record("\"event\":\"FAULT_APPLIED\"," + fields
        + ",\"faultType\":\"" + escape(type)
        + "\",\"planIndex\":" + nextFault);
    nextFault++;
    if (type.equals("IOException")) throw new IOException("HDFS recovery injected file check failure");
    if (type.equals("FileNotFoundException"))
      throw new java.io.FileNotFoundException("HDFS recovery injected missing replica file");
    throw new IllegalArgumentException("unsupported replica file fault " + type);
  }

  private static Context context(DataNode node) {
    Context current = CURRENT.get();
    if (current != null) return current;
    current = new Context();
    current.source = source(node);
    current.blockId = -1L;
    current.recoveryId = -1L;
    current.attempt = 0;
    current.root = current.source + "/no-recovery-context";
    return current;
  }

  public static void targetCheck(int caseNumber, String bpid, Object value,
                                 DataNode node) {
    Context context = context(node);
    String method = caseNumber == 28 ? GET_ID : GET_ACTIVE;
    String site = method + (caseNumber == 30 ? "#u23" : "#u12");
    boolean missing = value == null;
    String fields = "\"caseId\":\"HDFS-" + caseNumber
        + "\",\"method\":\"" + escape(method)
        + "\",\"siteId\":\"" + escape(site)
        + "\",\"sourceKey\":\"" + escape(context.source)
        + "\",\"blockId\":" + context.blockId
        + ",\"recoveryId\":" + context.recoveryId
        + ",\"attempt\":" + context.attempt
        + ",\"bpid\":\"" + escape(bpid)
        + "\",\"occurrenceAddress\":\"" + escape(context.root)
        + "\",\"outcome\":" + missing;
    record("\"event\":\"TARGET_CHECK\"," + fields);
    record("\"event\":\"BRANCH\"," + fields);
  }

  public static void targetThrow(int caseNumber, Throwable error) {
    Context context = CURRENT.get();
    String source = context == null ? "unregistered" : context.source;
    String root = context == null ? "unknown" : context.root;
    long blockId = context == null ? -1L : context.blockId;
    String method = caseNumber == 28 ? GET_ID : GET_ACTIVE;
    String site = method + (caseNumber == 30 ? "#u23" : "#u12");
    record("\"event\":\"TARGET_THROW\",\"caseId\":\"HDFS-"
        + caseNumber + "\",\"sourceKey\":\"" + escape(source)
        + "\",\"method\":\"" + escape(method)
        + "\",\"siteId\":\"" + escape(site)
        + "\",\"blockId\":" + blockId
        + "\",\"occurrenceAddress\":\"" + escape(root)
        + "\",\"runtimeType\":\"" + escape(error.getClass().getName())
        + "\",\"message\":\"" + escape(error.getMessage()) + "\"");
  }

  /** Called before a production InterDatanodeProtocol RPC call site. */
  public static synchronized void ioInitReplicaRecovery(Object proxy) throws IOException {
    Context context = CURRENT.get();
    if (context == null) return;
    boolean remote = !(proxy instanceof DataNode);
    RPC_KIND.set(remote ? "initReplicaRecovery" : "localInitReplicaRecovery");
    String marker = remote ? "FAULT:HDFS_RPC:INIT_REPLICA_RECOVERY"
                           : "OBSERVE:HDFS_LOCAL:INIT_REPLICA_RECOVERY";
    io(marker, INIT_SITE, remote, "initReplicaRecovery");
  }

  public static void markCommitRpc() {
    if (CURRENT.get() != null) RPC_KIND.set("commitBlockSynchronization");
  }

  public static void markUpdateRpc() {
    if (CURRENT.get() != null) RPC_KIND.set("updateReplicaUnderRecovery");
  }

  /** The physical Hadoop IPC request send, scoped to this recovery thread. */
  public static synchronized void ioHadoopIpc() throws IOException {
    if (CURRENT.get() == null) return;
    String kind = RPC_KIND.get();
    if (kind == null) kind = "unclassifiedRecoveryRpc";
    io("FAULT:HADOOP_IPC:REQUEST", IPC_SITE, true, kind);
  }

  private static void io(String marker, String site, boolean remote,
                         String operation) throws IOException {
    Context context = CURRENT.get();
    if (context == null) return;
    String sourceKey = context.source;
    String occurrence = context.root + "/rpc:" + operation + "/site:" + site;
    String key = marker + "|" + site + "|" + sourceKey + "|" + occurrence;
    int ordinal = IO_ORDINALS.containsKey(key) ? IO_ORDINALS.get(key) + 1 : 1;
    IO_ORDINALS.put(key, ordinal);
    String fields = "\"marker\":\"" + escape(marker)
        + "\",\"siteId\":\"" + escape(site)
        + "\",\"sourceKey\":\"" + escape(sourceKey)
        + "\",\"occurrenceAddress\":\"" + escape(occurrence)
        + "\",\"hitOrdinal\":" + ordinal
        + ",\"blockId\":" + context.blockId
        + ",\"attempt\":" + context.attempt
        + ",\"requestApi\":\"" + escape(operation) + "\""
        + ",\"remote\":" + remote;
    record("\"event\":\"FAULT_POINT_OBSERVED\"," + fields);
    if (!remote || nextFault >= PLAN.size()) return;
    String[] wanted = PLAN.get(nextFault);
    if (!(wanted[0].equals(marker) && wanted[1].equals(site)
          && wanted[2].equals(sourceKey) && wanted[3].equals(occurrence)
          && Integer.parseInt(wanted[4]) == ordinal
          && wanted[6].isEmpty())) return;
    String type = wanted[5];
    record("\"event\":\"FAULT_MATCHED\"," + fields
        + ",\"faultType\":\"" + escape(type)
        + "\",\"planIndex\":" + nextFault);
    record("\"event\":\"FAULT_APPLIED\"," + fields
        + ",\"faultType\":\"" + escape(type)
        + "\",\"planIndex\":" + nextFault);
    nextFault++;
    if (type.equals("EOFException")) throw new EOFException("HDFS recovery injected EOF");
    if (type.equals("SocketTimeoutException"))
      throw new SocketTimeoutException("HDFS recovery injected RPC timeout");
    if (type.equals("IOException")) throw new IOException("HDFS recovery injected RPC failure");
    throw new IllegalArgumentException("unsupported recovery fault type " + type);
  }
}
