import java.io.BufferedWriter;
import java.io.EOFException;
import java.io.FileWriter;
import java.io.IOException;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hdfs.protocol.datatransfer.sasl.SaslDataTransferServer;
import org.apache.hadoop.hdfs.net.Peer;
import org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager;
import org.apache.hadoop.hdfs.server.datanode.DataNode;

/** A case-local, graph-free runtime identity and I/O fault recorder. */
public final class HdfsKeyActorProbe {
  private static final String TRACE = System.getProperty("hdfsKey.v2.trace", "");
  private static final String PLAN = System.getProperty("hdfsKey.v2.plan", "");
  private static final ThreadLocal<Integer> EPISODE = new ThreadLocal<>();
  private static final Map<DataNode, Actor> DATA_NODES = new IdentityHashMap<>();
  private static final Map<BlockTokenSecretManager, Manager> MANAGERS = new IdentityHashMap<>();
  private static final Map<SaslDataTransferServer, Actor> SERVERS = new IdentityHashMap<>();
  private static final Map<Integer, Integer> SLOTS = new LinkedHashMap<>();
  private static final Map<String, Integer> ORDINALS = new LinkedHashMap<>();
  private static final List<String[]> FAULTS = new ArrayList<>();
  private static BufferedWriter writer;
  private static long seq;
  private static int nextEpisode;
  private static int nextFault;

  private static final class Actor {
    final int episode;
    final int slot;
    final String key;
    final String dirs;
    final Map<String, String> pools = new LinkedHashMap<>();

    Actor(int episode, int slot, String dirs) {
      this.episode = episode;
      this.slot = slot;
      this.dirs = dirs;
      this.key = "episode=" + episode + "/dn=" + slot + "/dirs=" + dirs;
    }

    String pool(String raw) {
      String existing = pools.get(raw);
      if (existing != null) return existing;
      String canonical = "BP" + pools.size();
      pools.put(raw, canonical);
      return canonical;
    }

    String uniquePool() {
      return pools.size() == 1 ? pools.values().iterator().next() : "unbound";
    }
  }

  private static final class Manager {
    final Actor actor;
    final String pool;
    final String rawPool;
    Manager(Actor actor, String pool, String rawPool) {
      this.actor = actor;
      this.pool = pool;
      this.rawPool = rawPool;
    }
  }

  static {
    try {
      if (!TRACE.isEmpty()) writer = new BufferedWriter(new FileWriter(TRACE));
      if (!PLAN.isEmpty()) {
        for (String line : Files.readAllLines(Paths.get(PLAN), StandardCharsets.UTF_8)) {
          if (line.isEmpty() || line.startsWith("#")) continue;
          String[] fields = line.split("\t", -1);
          if (fields.length != 6) throw new IllegalArgumentException("expected six V2 plan fields");
          FAULTS.add(fields);
        }
      }
      Runtime.getRuntime().addShutdownHook(new Thread(() -> {
        synchronized (HdfsKeyActorProbe.class) {
          try { if (writer != null) writer.close(); } catch (IOException ignored) { }
        }
      }));
    } catch (IOException error) { throw new ExceptionInInitializerError(error); }
  }

  private HdfsKeyActorProbe() { }

  private static String q(Object value) {
    return "\"" + String.valueOf(value).replace("\\", "\\\\")
        .replace("\"", "\\\"").replace("\n", "\\n")
        .replace("\r", "\\r") + "\"";
  }

  private static void emit(String event, String fields) {
    if (writer == null) return;
    try {
      writer.write("{\"event\":" + q(event) + ",\"seq\":" + (++seq)
          + ",\"thread\":" + q(Thread.currentThread().getName()) + fields + "}\n");
      writer.flush();
    } catch (IOException error) { throw new RuntimeException("V2 trace write failed", error); }
  }

  public static synchronized void startEpisode() {
    int episode = ++nextEpisode;
    EPISODE.set(episode);
    emit("START_EPISODE", ",\"episode\":" + episode);
  }

  public static void endEpisode() { EPISODE.remove(); }

  private static String dirs(Configuration conf) {
    String raw = conf == null ? "" : conf.get("dfs.datanode.data.dir", "");
    java.util.regex.Matcher matcher = java.util.regex.Pattern.compile(
        "(?:^|/)dfs/(?:data/)?(data[0-9]+|datanodeMaster)(?:/|,|$)").matcher(raw);
    java.util.List<String> normalized = new java.util.ArrayList<>();
    while (matcher.find()) normalized.add("dfs/data/" + matcher.group(1));
    java.util.Collections.sort(normalized);
    return normalized.isEmpty() ? "unbound" : String.join(",", normalized);
  }

  public static synchronized void registerDataNode(DataNode dn, Configuration conf) {
    Integer episode = EPISODE.get();
    if (dn == null || episode == null) {
      emit("ACTOR_UNBOUND", ",\"reason\":\"missing_start_episode\"");
      return;
    }
    if (DATA_NODES.containsKey(dn)) return;
    int slot = SLOTS.containsKey(episode) ? SLOTS.get(episode) + 1 : 1;
    SLOTS.put(episode, slot);
    Actor actor = new Actor(episode, slot, dirs(conf));
    DATA_NODES.put(dn, actor);
    emit("ACTOR_REGISTERED", ",\"actorKey\":" + q(actor.key)
        + ",\"dnObjectHash\":" + System.identityHashCode(dn)
        + ",\"configuredDataDirsRaw\":" + q(conf.get("dfs.datanode.data.dir", "")));
  }

  public static synchronized void bindManager(DataNode dn, BlockTokenSecretManager manager,
                                              String rawPool) {
    Actor actor = DATA_NODES.get(dn);
    if (actor == null || manager == null || rawPool == null) {
      emit("MANAGER_UNBOUND", ",\"reason\":\"unregistered_datanode_or_pool\"");
      return;
    }
    String pool = actor.pool(rawPool);
    Manager previous = MANAGERS.put(manager, new Manager(actor, pool, rawPool));
    if (previous != null && previous.actor != actor) {
      throw new IllegalStateException("BlockTokenSecretManager rebound to another DataNode");
    }
    emit("MANAGER_BOUND", ",\"actorKey\":" + q(actor.key)
        + ",\"resource\":" + q(pool) + ",\"rawBlockPoolId\":" + q(rawPool)
        + ",\"managerObjectHash\":" + System.identityHashCode(manager));
  }

  public static synchronized void bindSaslServer(DataNode dn, SaslDataTransferServer server) {
    Actor actor = DATA_NODES.get(dn);
    if (actor == null || server == null) {
      emit("SERVER_UNBOUND", ",\"reason\":\"unregistered_datanode\"");
      return;
    }
    SERVERS.put(server, actor);
    emit("SERVER_BOUND", ",\"actorKey\":" + q(actor.key)
        + ",\"serverObjectHash\":" + System.identityHashCode(server));
  }

  private static String actorFields(Manager manager) {
    return ",\"actorKey\":" + q(manager == null ? "unbound" : manager.actor.key)
        + ",\"targetActor\":" + q(manager == null ? "unbound" : manager.actor.key)
        + ",\"resource\":" + q(manager == null ? "unbound" : manager.pool)
        + ",\"rawBlockPoolId\":" + q(manager == null ? "unbound" : manager.rawPool);
  }

  private static void check(String caseId, String site, Object key,
                            BlockTokenSecretManager owner, int keyId) {
    Manager manager = MANAGERS.get(owner);
    emit("TARGET_CHECK", ",\"caseId\":" + q(caseId) + ",\"siteId\":" + q(site)
        + actorFields(manager) + ",\"keyId\":" + keyId
        + ",\"keyPresent\":" + (key != null));
  }

  public static synchronized void check11(Object key, BlockTokenSecretManager owner, int keyId) {
    check("HDFS-11", "BlockTokenSecretManager.retrieveDataEncryptionKey#L552", key, owner, keyId);
  }

  public static synchronized void check12(Object key, BlockTokenSecretManager owner, int keyId) {
    check("HDFS-12", "BlockTokenSecretManager.retrievePassword#L511", key, owner, keyId);
  }

  private static void targetThrow(String caseId, String site, Throwable error,
                                  BlockTokenSecretManager owner) {
    emit("TARGET_THROW", ",\"caseId\":" + q(caseId) + ",\"siteId\":" + q(site)
        + actorFields(MANAGERS.get(owner)) + ",\"exception\":" + q(error.getClass().getName()));
  }

  public static synchronized void throw11(Throwable error, BlockTokenSecretManager owner) {
    targetThrow("HDFS-11", "BlockTokenSecretManager.retrieveDataEncryptionKey#L553", error, owner);
  }

  public static synchronized void throw12(Throwable error, BlockTokenSecretManager owner) {
    targetThrow("HDFS-12", "BlockTokenSecretManager.retrievePassword#L514", error, owner);
  }

  /** The actual SaslDataTransferServer instance identifies the receiving DataNode. */
  public static synchronized void io(SaslDataTransferServer server, Peer peer,
                                     String marker, String site)
      throws IOException {
    Actor actor = SERVERS.get(server);
    String actorKey = actor == null ? "unbound" : actor.key;
    String pool = actor == null ? "unbound" : actor.uniquePool();
    String source = actorKey + "/resource=" + pool;
    String occurrence = source + "/site=" + site;
    String key = marker + "|" + site + "|" + source;
    int ordinal = ORDINALS.containsKey(key) ? ORDINALS.get(key) + 1 : 1;
    ORDINALS.put(key, ordinal);
    String fields = ",\"marker\":" + q(marker) + ",\"siteId\":" + q(site)
        + ",\"sourceKey\":" + q(source) + ",\"occurrence\":" + q(occurrence)
        + ",\"hitOrdinal\":" + ordinal + ",\"actorLocalOrdinal\":" + ordinal
        + ",\"faultActor\":" + q(actorKey) + ",\"resource\":" + q(pool)
        + ",\"rawRemoteEndpoint\":" + q(peer == null ? "unbound" : peer.getRemoteAddressString())
        + ",\"rawLocalEndpoint\":" + q(peer == null ? "unbound" : peer.getLocalAddressString());
    emit("FAULT_POINT_OBSERVED", fields);
    if (actor == null || "unbound".equals(actor.dirs) || "unbound".equals(pool)
        || nextFault >= FAULTS.size()) return;
    String[] selected = FAULTS.get(nextFault);
    if (!selected[0].equals(marker) || !selected[1].equals(site)
        || !selected[2].equals(actorKey) || !selected[3].equals(pool)
        || Integer.parseInt(selected[4]) != ordinal) return;
    emit("FAULT_MATCHED", fields + ",\"faultType\":" + q(selected[5])
        + ",\"planIndex\":" + nextFault);
    emit("FAULT_APPLIED", fields + ",\"faultType\":" + q(selected[5])
        + ",\"planIndex\":" + nextFault);
    nextFault++;
    if ("EOFException".equals(selected[5])) throw new EOFException("V2 injected SASL EOF");
    if ("SocketTimeoutException".equals(selected[5]))
      throw new SocketTimeoutException("V2 injected SASL timeout");
    if ("IOException".equals(selected[5])) throw new IOException("V2 injected SASL I/O error");
    throw new IllegalArgumentException("unsupported V2 fault " + selected[5]);
  }
}
