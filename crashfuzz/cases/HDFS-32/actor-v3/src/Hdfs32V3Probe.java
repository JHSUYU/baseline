package org.apache.hadoop.hdfs.server.datanode;

import java.io.EOFException;
import java.io.FileOutputStream;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hdfs.protocol.ExtendedBlock;
import org.apache.hadoop.hdfs.server.namenode.FSNamesystem;

/** Case-local physical-DN/BP I/O and exact target receipts. */
public final class Hdfs32V3Probe {
  private static final class Actor {
    final DataNode dn;
    final String key;
    Actor(DataNode value, String identity) { dn = value; key = identity; }
  }
  private static final class Context {
    final Actor actor;
    final BPOfferService bpos;
    final String service;
    final InetSocketAddress nn;
    Context(Actor a, BPOfferService b, String s, InetSocketAddress n) {
      actor = a; bpos = b; service = s; nn = n;
    }
  }
  private static final class Fault {
    final String marker, api, actor, service, type;
    final int ordinal;
    Fault(String[] row) {
      marker = row[0]; api = row[1]; actor = row[2]; service = row[3];
      ordinal = Integer.parseInt(row[4]); type = row[5];
    }
  }
  private static final Map<DataNode, Actor> ACTORS = new IdentityHashMap<>();
  private static final Map<Object, Actor> DATASETS = new IdentityHashMap<>();
  private static final Map<String, String> POOLS = new HashMap<>();
  private static final Map<String, Integer> HITS = new HashMap<>();
  private static final ThreadLocal<Integer> EPISODE = new ThreadLocal<>();
  private static final ThreadLocal<Context> CONTEXT = new ThreadLocal<>();
  private static final ThreadLocal<Boolean> LAST_SELECTED = new ThreadLocal<>();
  private static final List<Fault> PLAN = new ArrayList<>();
  private static final Path TRACE = Paths.get(System.getProperty("hdfs32.v3.trace"));
  private static long seq;
  private static int episode;
  private static int slot;
  private static int nextFault;
  private static int selectedChecks;

  static {
    String path = System.getProperty("hdfs32.v3.plan", "");
    if (!path.isEmpty()) {
      try {
        for (String line : Files.readAllLines(Paths.get(path), StandardCharsets.UTF_8)) {
          if (line.isEmpty() || line.startsWith("#")) continue;
          String[] row = line.split("\t", -1);
          if (row.length != 6) throw new IllegalArgumentException("fault plan: " + line);
          PLAN.add(new Fault(row));
        }
      } catch (IOException error) { throw new ExceptionInInitializerError(error); }
    }
  }
  private Hdfs32V3Probe() { }
  private static String q(Object value) {
    if (value == null) return "";
    return value.toString().replace("\\", "\\\\").replace("\"", "\\\"")
        .replace("\n", "\\n").replace("\r", "\\r");
  }
  private static String f(String name, Object value) { return ",\"" + name + "\":\"" + q(value) + "\""; }
  private static synchronized void emit(String event, String fields) {
    String row = "{\"seq\":" + (++seq) + ",\"event\":\"" + event + "\""
        + f("thread", Thread.currentThread().getName()) + fields + "}\n";
    try (FileOutputStream out = new FileOutputStream(TRACE.toFile(), true)) {
      out.write(row.getBytes(StandardCharsets.UTF_8));
    } catch (IOException error) {
      System.err.println("HDFS32_V3_TRACE_ERROR " + error);
    }
  }
  public static synchronized void startEpisode() {
    EPISODE.set(++episode);
    slot = 0;
    emit("CLUSTER_EPISODE", f("episode", episode));
  }
  public static void endEpisode() { EPISODE.remove(); }
  public static synchronized DataNode registerDataNode(DataNode dn, Configuration conf) {
    if (dn == null || ACTORS.containsKey(dn) || EPISODE.get() == null) return dn;
    Actor actor = new Actor(dn, "episode" + EPISODE.get() + "/dn" + slot++);
    ACTORS.put(dn, actor);
    emit("DN_REGISTER", f("actor", actor.key) + f("uuid", dn.getDatanodeUuid())
        + f("dataDirs", conf == null ? "" : conf.get("dfs.datanode.data.dir", "")));
    return dn;
  }
  public static synchronized void registerDataNodes(ArrayList<DataNode> dataNodes) {
    StringBuilder actors = new StringBuilder();
    for (int i = 0; i < dataNodes.size(); ++i) {
      Actor actor = ACTORS.get(dataNodes.get(i));
      if (i > 0) actors.append(',');
      actors.append(actor == null ? "UNBOUND" : actor.key);
    }
    emit("CLUSTER_DN_LIST", f("actors", actors) + f("count", dataNodes.size()));
  }
  public static synchronized void registerNamesystem(int index, FSNamesystem ns) {
    if (ns == null) return;
    String raw = ns.getBlockPoolId();
    String role = "namesServerId" + (index + 1);
    if (raw != null) POOLS.put(raw, role);
    emit("NN_POOL", f("nnIndex", index) + f("service", role) + f("rawBpid", raw));
  }
  public static synchronized void mapDataset(DataNode dn, Object dataset) {
    Actor actor = ACTORS.get(dn);
    if (actor != null && dataset != null && !DATASETS.containsKey(dataset)) {
      DATASETS.put(dataset, actor);
      emit("DATASET_MAP", f("actor", actor.key)
          + f("uuid", dn.getDatanodeUuid())
          + f("datasetId", System.identityHashCode(dataset)));
    }
  }
  public static synchronized void poolAdd(BlockPoolManager manager, BPOfferService bpos) {
    if (bpos == null) return;
    Actor actor = ACTORS.get(bpos.getDataNode());
    String bpid = bpos.getBlockPoolId();
    String role = bpos.getNameserviceId();
    if (bpid != null && role != null) POOLS.put(bpid, role);
    emit("POOL_ADD", f("actor", actor == null ? "UNBOUND" : actor.key)
        + f("service", role) + f("rawBpid", bpid));
  }
  public static synchronized void poolRemove(BlockPoolManager manager, BPOfferService bpos) {
    if (bpos == null) return;
    Actor actor = ACTORS.get(bpos.getDataNode());
    emit("POOL_REMOVE", f("actor", actor == null ? "UNBOUND" : actor.key)
        + f("service", bpos.getNameserviceId()) + f("rawBpid", bpos.getBlockPoolId()));
  }
  public static synchronized void enterActor(DataNode dn, BPOfferService bpos,
      String service, InetSocketAddress nn) {
    Actor actor = ACTORS.get(dn);
    CONTEXT.set(new Context(actor, bpos, service, nn));
    String bpid = bpos == null ? null : bpos.getBlockPoolId();
    if (bpid != null && service != null) POOLS.put(bpid, service);
    emit("BP_ACTOR_BEGIN", f("actor", actor == null ? "UNBOUND" : actor.key)
        + f("uuid", dn == null ? null : dn.getDatanodeUuid())
        + f("service", service) + f("rawBpid", bpid) + f("nnEndpoint", nn));
  }
  public static void exitActor() { CONTEXT.remove(); }
  private static boolean samePeer(InetSocketAddress x, InetSocketAddress y) {
    if (x == null || y == null || x.getPort() != y.getPort()) return false;
    if (x.getAddress() != null && y.getAddress() != null)
      return x.getAddress().equals(y.getAddress());
    return x.getHostString().equalsIgnoreCase(y.getHostString());
  }
  private static String rpcApi() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      String owner = frame.getClassName();
      if (owner.startsWith("org.apache.hadoop.hdfs.") && owner.endsWith("TranslatorPB"))
        return owner.substring(owner.lastIndexOf('.') + 1) + "." + frame.getMethodName();
    }
    return "other";
  }
  public static void rpcResponse(InetSocketAddress remote) throws IOException {
    Context ctx = CONTEXT.get();
    Actor actor = ctx == null ? null : ctx.actor;
    String service = ctx == null ? "UNBOUND" : ctx.service;
    String bpid = ctx == null || ctx.bpos == null ? null : ctx.bpos.getBlockPoolId();
    if (bpid != null && !"UNBOUND".equals(service)) synchronized (Hdfs32V3Probe.class) { POOLS.put(bpid, service); }
    io("RPC", rpcApi(), actor, service, bpid, remote,
        ctx != null && samePeer(ctx.nn, remote), -1, -1);
  }
  public static void fileIO(Object dataset, ExtendedBlock block, String api) throws IOException {
    Actor actor;
    String service;
    synchronized (Hdfs32V3Probe.class) {
      actor = DATASETS.get(dataset);
      service = block == null ? null : POOLS.get(block.getBlockPoolId());
    }
    io("FILE", api, actor, service, block == null ? null : block.getBlockPoolId(),
        null, actor != null && service != null, block == null ? -1 : block.getBlockId(),
        System.identityHashCode(dataset));
  }
  private static synchronized void io(String marker, String api, Actor actor,
      String service, String bpid, InetSocketAddress remote, boolean bound,
      long blockId, int datasetId)
      throws IOException {
    String key = marker + "|" + api + "|" + (actor == null ? "UNBOUND" : actor.key)
        + "|" + service;
    int ordinal = HITS.containsKey(key) ? HITS.get(key) + 1 : 1;
    HITS.put(key, ordinal);
    String fields = f("marker", marker) + f("api", api)
        + f("actor", actor == null ? "UNBOUND" : actor.key)
        + f("uuid", actor == null ? null : actor.dn.getDatanodeUuid())
        + f("service", service) + f("rawBpid", bpid)
        + f("rawEndpoint", remote) + f("blockId", blockId)
        + f("datasetId", datasetId)
        + f("ordinal", ordinal) + f("bound", bound);
    emit("IO_OBSERVED", fields);
    if (!bound || actor == null || service == null || nextFault >= PLAN.size()) return;
    Fault fault = PLAN.get(nextFault);
    if (!fault.marker.equals(marker) || !fault.api.equals(api)
        || !fault.actor.equals(actor.key) || !fault.service.equals(service)
        || fault.ordinal != ordinal) return;
    emit("FAULT_MATCHED", fields + f("planIndex", nextFault) + f("exception", fault.type));
    emit("FAULT_APPLIED", fields + f("planIndex", nextFault) + f("exception", fault.type));
    nextFault++;
    if ("EOFException".equals(fault.type)) throw new EOFException("HDFS-32 V3 " + key);
    if ("SocketTimeoutException".equals(fault.type))
      throw new SocketTimeoutException("HDFS-32 V3 " + key);
    throw new IOException("HDFS-32 V3 " + key);
  }
  public static synchronized void guard(BPOfferService service, DataNode dn,
      String bpid, boolean force) {
    Actor actor = ACTORS.get(dn);
    String role = POOLS.get(bpid);
    if (service != null && service.getNameserviceId() != null)
      role = service.getNameserviceId();
    boolean selected = actor != null && actor.key.endsWith("/dn1")
        && "namesServerId1".equals(role) && force && selectedChecks++ == 0;
    LAST_SELECTED.set(selected);
    emit("TARGET_CHECK", f("actor", actor == null ? "UNBOUND" : actor.key)
        + f("uuid", dn == null ? null : dn.getDatanodeUuid())
        + f("service", role) + f("rawBpid", bpid) + f("force", force)
        + f("present", service != null) + f("selected", selected));
  }
  public static synchronized void targetThrow(Throwable error, DataNode dn,
      String bpid, boolean force) {
    Actor actor = ACTORS.get(dn);
    emit("TARGET_THROW", f("actor", actor == null ? "UNBOUND" : actor.key)
        + f("uuid", dn == null ? null : dn.getDatanodeUuid())
        + f("service", POOLS.get(bpid)) + f("rawBpid", bpid)
        + f("force", force) + f("selected", Boolean.TRUE.equals(LAST_SELECTED.get()))
        + f("type", error.getClass().getName()) + f("message", error.getMessage()));
  }
}
