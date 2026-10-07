import java.io.BufferedWriter;
import java.io.FileWriter;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.WeakHashMap;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hdfs.protocol.ExtendedBlock;
import org.apache.hadoop.hdfs.server.datanode.DataNode;

/** HDFS-31 V3: bind BP RPC I/O and the direct DataNode guard to a real DN. */
public final class Hdfs31Probe {
  private static final String TRACE = System.getProperty("hdfs31.v3.trace", "");
  private static final String PLAN = System.getProperty("hdfs31.v3.plan", "");
  private static final Map<DataNode, Actor> ACTORS =
      Collections.synchronizedMap(new WeakHashMap<DataNode, Actor>());
  private static final ThreadLocal<Integer> START_EPISODE = new ThreadLocal<>();
  private static final ThreadLocal<Actor> CURRENT_ACTOR = new ThreadLocal<>();
  private static final ThreadLocal<DataNode> CURRENT_DN = new ThreadLocal<>();
  private static final ThreadLocal<InetSocketAddress> CURRENT_NN = new ThreadLocal<>();
  private static final ThreadLocal<Object> CURRENT_SERVICE = new ThreadLocal<>();
  private static final Map<Object, Integer> SERVICE_IDS = new IdentityHashMap<>();
  private static final Map<Object, Actor> SERVICE_ACTORS = new IdentityHashMap<>();
  private static final Map<Object, String> SERVICE_BP = new IdentityHashMap<>();
  private static final Map<Integer, Integer> EPISODE_SLOTS = new HashMap<>();
  private static final Map<String, Integer> HITS = new HashMap<>();
  private static final List<String[]> FAULTS = new ArrayList<>();
  private static int nextEpisode, nextObject, nextService, nextFault;
  private static long seq;
  private static BufferedWriter writer;

  private static final class Actor {
    final int episode, slot, objectId;
    final String dirs, key;
    Actor(int episode, int slot, int objectId, String dirs) {
      this.episode = episode;
      this.slot = slot;
      this.objectId = objectId;
      this.dirs = dirs;
      this.key = "episode=" + episode + "/dn=" + slot + "/dirs=" + dirs;
    }
  }

  static {
    try {
      if (!TRACE.isEmpty()) writer = new BufferedWriter(new FileWriter(TRACE));
      if (!PLAN.isEmpty()) {
        for (String line : Files.readAllLines(Paths.get(PLAN), StandardCharsets.UTF_8)) {
          if (!line.isEmpty() && !line.startsWith("#")) FAULTS.add(line.split("\\t", -1));
        }
      }
      Runtime.getRuntime().addShutdownHook(new Thread(() -> {
        synchronized (Hdfs31Probe.class) {
          try { if (writer != null) writer.close(); } catch (IOException ignored) { }
        }
      }));
    } catch (IOException ex) { throw new ExceptionInInitializerError(ex); }
  }

  private Hdfs31Probe() { }

  private static String q(Object value) {
    return "\"" + String.valueOf(value).replace("\\", "\\\\").replace("\"", "\\\"")
        .replace("\n", "\\n").replace("\r", "\\r") + "\"";
  }

  private static void emit(String event, String fields) {
    synchronized (Hdfs31Probe.class) {
      if (writer == null) return;
      try {
        writer.write("{\"event\":" + q(event) + ",\"seq\":" + (++seq)
            + ",\"thread\":" + q(Thread.currentThread().getName()) + fields + "}\n");
        writer.flush();
      } catch (IOException ex) { throw new RuntimeException(ex); }
    }
  }

  private static String dataDirs(Configuration conf) {
    String raw = conf == null ? "" : conf.get("dfs.datanode.data.dir", "");
    List<String> dirs = new ArrayList<>();
    for (String item : raw.split(",")) {
      java.util.regex.Matcher m = java.util.regex.Pattern.compile(
          "(?:^|/)dfs/(data[0-9]+|data|datanodeMaster)(?:/|$)").matcher(item);
      if (m.find()) dirs.add("dfs/" + m.group(1));
    }
    Collections.sort(dirs);
    return dirs.isEmpty() ? "unbound" : String.join(",", dirs);
  }

  public static synchronized void startEpisode() {
    int episode = ++nextEpisode;
    START_EPISODE.set(episode);
    emit("START_EPISODE", ",\"episode\":" + episode);
  }

  public static void endEpisode() { START_EPISODE.remove(); }

  /** Called before startDataNode starts its BP actor, on the cluster startup thread. */
  public static DataNode registerDataNode(DataNode dn, Configuration conf) {
    Integer episode = START_EPISODE.get();
    if (dn == null || episode == null) {
      emit("ACTOR_UNBOUND", ",\"reason\":\"missing_start_episode\"");
      return dn;
    }
    Actor actor;
    synchronized (Hdfs31Probe.class) {
      if (ACTORS.containsKey(dn)) return dn;
      int slot = EPISODE_SLOTS.containsKey(episode) ? EPISODE_SLOTS.get(episode) + 1 : 1;
      EPISODE_SLOTS.put(episode, slot);
      actor = new Actor(episode, slot, ++nextObject, dataDirs(conf));
      ACTORS.put(dn, actor);
    }
    emit("ACTOR_REGISTERED", actorFields(actor, dn)
        + ",\"configuredDataDirsRaw\":" + q(conf.get("dfs.datanode.data.dir", "")));
    return dn;
  }

  private static String actorFields(Actor actor, DataNode dn) {
    return ",\"actorKey\":" + q(actor == null ? "unbound" : actor.key)
        + ",\"startupEpisode\":" + (actor == null ? -1 : actor.episode)
        + ",\"dnSlot\":" + (actor == null ? -1 : actor.slot)
        + ",\"dnObjectId\":" + (actor == null ? -1 : actor.objectId)
        + ",\"dnObjectHash\":" + (dn == null ? -1 : System.identityHashCode(dn))
        + ",\"dnUuidRaw\":" + q(dn == null ? null : dn.getDatanodeUuid());
  }

  private static synchronized int serviceId(Object service) {
    if (service == null) return -1;
    Integer id = SERVICE_IDS.get(service);
    if (id == null) {
      id = ++nextService;
      SERVICE_IDS.put(service, id);
    }
    return id;
  }

  public static void enterActor(DataNode dn, InetSocketAddress nn, Object service) {
    Actor actor = ACTORS.get(dn);
    CURRENT_ACTOR.set(actor);
    CURRENT_DN.set(dn);
    CURRENT_NN.set(nn);
    CURRENT_SERVICE.set(service);
    if (actor != null && service != null) {
      synchronized (Hdfs31Probe.class) { SERVICE_ACTORS.put(service, actor); }
    }
    if (actor == null || "unbound".equals(actor.dirs)) {
      emit("ACTOR_UNBOUND", ",\"reason\":\"unregistered_datanode_or_dirs\""
          + actorFields(actor, dn) + ",\"namenodeEndpointRaw\":" + q(nn)
          + ",\"serviceObjectId\":" + serviceId(service));
    } else {
      emit("ACTOR_ENTER", actorFields(actor, dn)
          + ",\"namenodeEndpointRaw\":" + q(nn)
          + ",\"serviceObjectId\":" + serviceId(service));
    }
  }

  public static void exitActor() {
    CURRENT_ACTOR.remove();
    CURRENT_DN.remove();
    CURRENT_NN.remove();
    CURRENT_SERVICE.remove();
  }

  public static void rpcResponse(InetSocketAddress endpoint) throws IOException {
    Actor actor = CURRENT_ACTOR.get();
    InetSocketAddress nn = CURRENT_NN.get();
    boolean bound = actor != null && !"unbound".equals(actor.dirs)
        && nn != null && nn.equals(endpoint);
    String source = bound ? actor.key + "/peer=NN0" : "unbound";
    String marker = "FAULT:HDFS31_BP_RPC:RESPONSE";
    String site = "Client.getRpcResponse";
    String key = marker + "|" + site + "|" + source;
    int ordinal;
    String faultType = null;
    synchronized (Hdfs31Probe.class) {
      ordinal = HITS.containsKey(key) ? HITS.get(key) + 1 : 1;
      HITS.put(key, ordinal);
      String fields = ",\"marker\":" + q(marker) + ",\"siteId\":" + q(site)
          + ",\"sourceKey\":" + q(source)
          + ",\"occurrence\":" + q(source + "/" + site)
          + ",\"hitOrdinal\":" + ordinal
          + ",\"actorKey\":" + q(actor == null ? "unbound" : actor.key)
          + ",\"dnObjectId\":" + (actor == null ? -1 : actor.objectId)
          + ",\"dnUuidRaw\":" + q(CURRENT_DN.get() == null
              ? null : CURRENT_DN.get().getDatanodeUuid())
          + ",\"peerRole\":" + q(bound ? "NN0" : "unbound")
          + ",\"endpointRaw\":" + q(endpoint)
          + ",\"actorNamenodeRaw\":" + q(nn);
      fields += ",\"serviceObjectId\":" + serviceId(CURRENT_SERVICE.get());
      emit("FAULT_POINT_OBSERVED", fields);
      if (bound && nextFault < FAULTS.size()) {
        String[] f = FAULTS.get(nextFault);
        if (f.length >= 6 && f[0].equals(marker) && f[1].equals(site)
            && f[2].equals(source) && Integer.parseInt(f[3]) == ordinal) {
          int index = nextFault++;
          faultType = f[5];
          emit("FAULT_MATCHED", fields + ",\"faultIndex\":" + index
              + ",\"faultType\":" + q(faultType));
          emit("FAULT_APPLIED", fields + ",\"faultIndex\":" + index
              + ",\"faultType\":" + q(faultType));
        }
      }
    }
    if (faultType != null) {
      String message = "HDFS31 actor V3 " + faultType + " " + source + "/" + ordinal;
      if (faultType.equals("SocketTimeoutException")) throw new java.net.SocketTimeoutException(message);
      if (faultType.equals("EOFException")) throw new java.io.EOFException(message);
      if (!faultType.equals("IOException")) throw new IllegalArgumentException(faultType);
      throw new IOException(message);
    }
  }

  private static String blockFields(DataNode dn, ExtendedBlock block) {
    Actor actor = ACTORS.get(dn);
    return actorFields(actor, dn)
        + ",\"blockPoolIdRaw\":" + q(block == null ? null : block.getBlockPoolId())
        + ",\"blockIdRaw\":" + (block == null ? -1 : block.getBlockId());
  }

  private static synchronized boolean priorPoolOwnerMatches(Actor actor, String bpId) {
    if (actor == null || bpId == null) return false;
    for (Map.Entry<Object, String> item : SERVICE_BP.entrySet()) {
      if (actor == SERVICE_ACTORS.get(item.getKey()) && bpId.equals(item.getValue())) return true;
    }
    return false;
  }

  public static void transfer(DataNode dn, ExtendedBlock block) {
    emit("DIRECT_TRANSFER", ",\"caseId\":\"HDFS-31\"" + blockFields(dn, block));
  }

  public static void guard(Object service, DataNode dn, ExtendedBlock block) {
    Actor actor = ACTORS.get(dn);
    String bpId = block == null ? null : block.getBlockPoolId();
    int serviceId = serviceId(service);
    boolean ownerMatches;
    synchronized (Hdfs31Probe.class) {
      ownerMatches = service != null && actor != null
          && actor == SERVICE_ACTORS.get(service) && bpId != null
          && bpId.equals(SERVICE_BP.get(service));
    }
    emit("DIRECT_TARGET_CHECK", ",\"caseId\":\"HDFS-31\"" + blockFields(dn, block)
        + ",\"siteId\":\"DataNode.getBPOSForBlock#L1832\""
        + ",\"servicePresent\":" + (service != null)
        + ",\"serviceObjectId\":" + serviceId
        + ",\"serviceObjectHash\":" + (service == null ? -1 : System.identityHashCode(service))
        + ",\"serviceOwnerSameDnBp\":" + ownerMatches
        + ",\"priorPoolOwnerSameDnBp\":" + priorPoolOwnerMatches(actor, bpId));
  }

  public static void targetThrow(Throwable error, DataNode dn, ExtendedBlock block) {
    Actor actor = ACTORS.get(dn);
    emit("DIRECT_TARGET_THROW", ",\"caseId\":\"HDFS-31\"" + blockFields(dn, block)
        + ",\"siteId\":\"DataNode.getBPOSForBlock#L1835\""
        + ",\"exception\":" + q(error.getClass().getName())
        + ",\"message\":" + q(error.getMessage())
        + ",\"priorPoolOwnerSameDnBp\":" + priorPoolOwnerMatches(
            actor, block == null ? null : block.getBlockPoolId()));
  }

  public static void poolAdd(DataNode dn, Object service, String bpId) {
    Actor actor = ACTORS.get(dn);
    synchronized (Hdfs31Probe.class) {
      if (service != null && actor != null) {
        serviceId(service);
        SERVICE_ACTORS.put(service, actor);
        SERVICE_BP.put(service, bpId);
      }
    }
    emit("POOL_ADD", actorFields(actor, dn) + ",\"blockPoolIdRaw\":" + q(bpId)
        + ",\"serviceObjectId\":" + serviceId(service)
        + ",\"serviceObjectHash\":" + (service == null ? -1 : System.identityHashCode(service)));
  }

  public static void poolRemove(DataNode dn, Object service, String bpId) {
    Actor actor = ACTORS.get(dn);
    emit("POOL_REMOVE", actorFields(actor, dn) + ",\"blockPoolIdRaw\":" + q(bpId)
        + ",\"serviceObjectId\":" + serviceId(service)
        + ",\"serviceObjectHash\":" + (service == null ? -1 : System.identityHashCode(service)));
  }
}
