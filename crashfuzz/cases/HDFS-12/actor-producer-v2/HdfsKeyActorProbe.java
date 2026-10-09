import java.io.BufferedWriter;
import java.io.EOFException;
import java.io.FileWriter;
import java.io.IOException;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hdfs.protocol.datatransfer.sasl.SaslDataTransferServer;
import org.apache.hadoop.hdfs.net.Peer;
import org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager;
import org.apache.hadoop.hdfs.security.token.block.BlockKey;
import org.apache.hadoop.hdfs.security.token.block.ExportedBlockKeys;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.hdfs.server.protocol.DatanodeCommand;
import org.apache.hadoop.hdfs.server.protocol.HeartbeatResponse;
import org.apache.hadoop.hdfs.server.protocol.KeyUpdateCommand;

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
  private static final Map<String, Integer> FIRST_TARGET_KEY = new LinkedHashMap<>();
  private static final Map<DatanodeCommand, ResponseCommand> RESPONSE_COMMANDS =
      new IdentityHashMap<>();
  private static final Map<DatanodeCommand, Integer> COMMAND_IDENTITIES =
      new IdentityHashMap<>();
  private static final List<String[]> FAULTS = new ArrayList<>();
  private static BufferedWriter writer;
  private static long seq;
  private static int nextEpisode;
  private static int nextFault;
  private static int nextManagerIdentity;
  private static int nextCommandIdentity;

  private static final class Actor {
    final int episode;
    final int slot;
    final String key;
    final String dirs;
    final Map<String, String> pools = new LinkedHashMap<>();
    final Map<String, String> nameNodes = new LinkedHashMap<>();

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

    String nameNode(String raw) {
      String existing = nameNodes.get(raw);
      if (existing != null) return existing;
      String canonical = "NN" + nameNodes.size();
      nameNodes.put(raw, canonical);
      return canonical;
    }
  }

  private static final class Manager {
    final Actor actor;
    final String pool;
    final String rawPool;
    final BlockTokenSecretManager owner;
    final int identity;
    Manager(Actor actor, String pool, String rawPool, BlockTokenSecretManager owner,
            int identity) {
      this.actor = actor;
      this.pool = pool;
      this.rawPool = rawPool;
      this.owner = owner;
      this.identity = identity;
    }
  }

  private static final class ResponseCommand {
    final Actor actor;
    final String pool;
    final String nn;
    final String rawNN;
    final int currentKeyId;
    final int[] allKeyIds;
    final String keyRole;
    ResponseCommand(Actor actor, String pool, String nn, String rawNN,
                    int currentKeyId, int[] allKeyIds, String keyRole) {
      this.actor = actor;
      this.pool = pool;
      this.nn = nn;
      this.rawNN = rawNN;
      this.currentKeyId = currentKeyId;
      this.allKeyIds = allKeyIds;
      this.keyRole = keyRole;
    }
  }

  static {
    try {
      if (!TRACE.isEmpty()) writer = new BufferedWriter(new FileWriter(TRACE));
      if (!PLAN.isEmpty()) {
        for (String line : Files.readAllLines(Paths.get(PLAN), StandardCharsets.UTF_8)) {
          if (line.isEmpty() || line.startsWith("#")) continue;
          String[] fields = line.split("\t", -1);
          if (fields.length != 7) throw new IllegalArgumentException("expected seven HDFS-12 V2 plan fields");
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
    Manager previous = MANAGERS.get(manager);
    if (previous != null && (previous.actor != actor || !previous.rawPool.equals(rawPool))) {
      throw new IllegalStateException("BlockTokenSecretManager rebound to another DataNode or pool");
    }
    if (previous == null) {
      MANAGERS.put(manager, new Manager(actor, pool, rawPool, manager, ++nextManagerIdentity));
    }
    Manager binding = MANAGERS.get(manager);
    emit("MANAGER_BOUND", ",\"actorKey\":" + q(actor.key)
        + ",\"resource\":" + q(pool) + ",\"rawBlockPoolId\":" + q(rawPool)
        + ",\"managerIdentity\":" + binding.identity
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

  private static int commandIdentity(DatanodeCommand command) {
    if (command == null) return 0;
    Integer existing = COMMAND_IDENTITIES.get(command);
    if (existing != null) return existing;
    int assigned = ++nextCommandIdentity;
    COMMAND_IDENTITIES.put(command, assigned);
    return assigned;
  }

  private static void check(String caseId, String site, Object key,
                            BlockTokenSecretManager owner, int keyId) {
    Manager manager = MANAGERS.get(owner);
    if ("HDFS-12".equals(caseId) && manager != null && key != null) {
      String stateKey = manager.actor.key + "/resource=" + manager.pool;
      if (!FIRST_TARGET_KEY.containsKey(stateKey)) FIRST_TARGET_KEY.put(stateKey, keyId);
    }
    emit("TARGET_CHECK", ",\"caseId\":" + q(caseId) + ",\"siteId\":" + q(site)
        + actorFields(manager) + ",\"managerIdentity\":"
        + (manager == null ? 0 : manager.identity) + ",\"managerObjectHash\":"
        + System.identityHashCode(owner) + ",\"keyId\":" + keyId
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

  /** A raw key ID is optional in replay plans because the NN seeds it randomly. */
  static boolean matchesFaultPlan(String[] requested, String marker, String site,
                                  String actorKey, String pool, int ordinal, int rawKeyId) {
    if (requested == null || requested.length != 7) return false;
    int requiredOrdinal;
    try { requiredOrdinal = Integer.parseInt(requested[4]); }
    catch (NumberFormatException invalid) { return false; }
    if (!requested[0].equals(marker) || !requested[1].equals(site)
        || !requested[2].equals(actorKey) || !requested[3].equals(pool)
        || requiredOrdinal != ordinal) return false;
    if ("*".equals(requested[6])) return rawKeyId >= 0;
    if ("-".equals(requested[6])) return rawKeyId < 0;
    try { return Integer.parseInt(requested[6]) == rawKeyId; }
    catch (NumberFormatException invalid) { return false; }
  }

  private static void applyFault(String kind, String site) throws IOException {
    if ("EOFException".equals(kind)) throw new EOFException("V2 injected EOF at " + site);
    if ("SocketTimeoutException".equals(kind))
      throw new SocketTimeoutException("V2 injected timeout at " + site);
    if ("IOException".equals(kind)) throw new IOException("V2 injected I/O at " + site);
    if ("Delay1500ms".equals(kind) || "Delay3000ms".equals(kind)) {
      try { Thread.sleep("Delay1500ms".equals(kind) ? 1500 : 3000); }
      catch (InterruptedException interrupted) {
        Thread.currentThread().interrupt();
        throw new java.io.InterruptedIOException("V2 interrupted delay at " + site);
      }
      return;
    }
    throw new IllegalArgumentException("unsupported V2 fault " + kind);
  }

  private static int[] keyIds(ExportedBlockKeys exported) {
    if (exported == null || exported.getAllKeys() == null) return new int[0];
    BlockKey[] keys = exported.getAllKeys();
    int[] ids = new int[keys.length];
    for (int i = 0; i < keys.length; i++) ids[i] = keys[i] == null ? -1 : keys[i].getKeyId();
    return ids;
  }

  private static int currentKeyId(ExportedBlockKeys exported) {
    return exported == null || exported.getCurrentKey() == null
        ? -1 : exported.getCurrentKey().getKeyId();
  }

  private static String rawDnUuid(DataNode dn) {
    if (dn == null || dn.getDatanodeId() == null) return "unbound";
    String uuid = dn.getDatanodeId().getDatanodeUuid();
    return uuid == null || uuid.isEmpty() ? "unbound" : uuid;
  }

  private static Manager boundManager(DataNode dn, String rawPool) {
    if (dn == null || rawPool == null || dn.getBlockPoolTokenSecretManager() == null) return null;
    try { return MANAGERS.get(dn.getBlockPoolTokenSecretManager().get(rawPool)); }
    catch (IllegalArgumentException missing) { return null; }
  }

  private static String producerFields(Actor actor, String pool, String nn,
                                       String rawNN, int currentId, int[] ids,
                                       String keyRole, DatanodeCommand command, DataNode dn) {
    String actorKey = actor == null ? "unbound" : actor.key;
    String rawPool = actor == null ? "unbound" : actor.pools.entrySet()
        .stream().filter(e -> e.getValue().equals(pool)).map(Map.Entry::getKey)
        .findFirst().orElse("unbound");
    Manager manager = boundManager(dn, rawPool);
    return ",\"faultActor\":" + q(actorKey) + ",\"resource\":" + q(pool)
        + ",\"rawBlockPoolId\":" + q(rawPool)
        + ",\"nnLogical\":" + q(nn) + ",\"rawNameNodeEndpoint\":" + q(rawNN)
        + ",\"rawDatanodeUuid\":" + q(rawDnUuid(dn))
        + ",\"dnObjectHash\":" + System.identityHashCode(dn)
        + ",\"managerIdentity\":" + (manager == null ? 0 : manager.identity)
        + ",\"managerObjectHash\":" + (manager == null ? 0
            : System.identityHashCode(manager.owner))
        + ",\"rawKeyId\":" + currentId
        + ",\"allKeyIds\":" + Arrays.toString(ids)
        + ",\"keyRole\":" + q(keyRole)
        + ",\"commandIdentity\":" + commandIdentity(command)
        + ",\"commandObjectHash\":" + System.identityHashCode(command);
  }

  private static String producerPoint(String marker, String site, Actor actor,
                                    String pool, String nn, String rawNN,
                                    int currentId, int[] ids, String keyRole,
                                    DatanodeCommand command, DataNode dn) {
    String actorKey = actor == null ? "unbound" : actor.key;
    String source = actorKey + "/resource=" + pool;
    String occurrence = source + "/site=" + site;
    String ordinalKey = marker + "|" + site + "|" + source;
    int ordinal = ORDINALS.containsKey(ordinalKey) ? ORDINALS.get(ordinalKey) + 1 : 1;
    ORDINALS.put(ordinalKey, ordinal);
    String fields = ",\"marker\":" + q(marker) + ",\"siteId\":" + q(site)
        + ",\"sourceKey\":" + q(source) + ",\"occurrence\":" + q(occurrence)
        + ",\"hitOrdinal\":" + ordinal + ",\"actorLocalOrdinal\":" + ordinal
        + producerFields(actor, pool, nn, rawNN, currentId, ids, keyRole, command, dn);
    emit("FAULT_POINT_OBSERVED", fields);
    if (actor == null || "unbound".equals(actor.dirs) || "unbound".equals(pool)
        || "unbound".equals(nn) || "null".equals(rawNN)
        || "unbound".equals(rawDnUuid(dn)) || currentId < 0
        || nextFault >= FAULTS.size()) return null;
    String[] selected = FAULTS.get(nextFault);
    if (!matchesFaultPlan(selected, marker, site, actorKey, pool, ordinal, currentId)) return null;
    emit("FAULT_MATCHED", fields + ",\"faultType\":" + q(selected[5])
        + ",\"requiredRawKeyId\":" + q(selected[6])
        + ",\"planIndex\":" + nextFault);
    emit("FAULT_APPLIED", fields + ",\"faultType\":" + q(selected[5])
        + ",\"requiredRawKeyId\":" + q(selected[6])
        + ",\"planIndex\":" + nextFault);
    nextFault++;
    return selected[5];
  }

  /** Called after a completed DataNode heartbeat RPC, before command enqueue. */
  public static void keyResponse(HeartbeatResponse response, DataNode dn,
                                              String rawPool, Object nnEndpoint)
      throws IOException {
    if (response == null) return;
    String faultKind = null;
    String faultSite = null;
    synchronized (HdfsKeyActorProbe.class) {
      Actor actor = DATA_NODES.get(dn);
      String pool = actor == null ? "unbound" : actor.pools.get(rawPool);
      if (pool == null) pool = "unbound";
      String rawNN = String.valueOf(nnEndpoint);
      String nn = actor == null ? "unbound" : actor.nameNode(rawNN);
      Manager manager = boundManager(dn, rawPool);
      boolean bound = manager != null && manager.actor == actor && manager.pool.equals(pool)
          && !"unbound".equals(rawDnUuid(dn)) && !"null".equals(rawNN);
      DatanodeCommand[] commands = response.getCommands();
      if (commands == null) return;
      for (DatanodeCommand command : commands) {
        if (!(command instanceof KeyUpdateCommand)) continue;
        ExportedBlockKeys exported = ((KeyUpdateCommand) command).getExportedKeys();
        int currentId = currentKeyId(exported);
        int[] ids = keyIds(exported);
        String stateKey = (actor == null ? "unbound" : actor.key) + "/resource=" + pool;
        Integer early = FIRST_TARGET_KEY.get(stateKey);
        String role = early != null && currentId >= 0 && currentId != early
            ? "ROTATED_CURRENT" : "INITIAL_OR_UNKNOWN";
        if (bound) RESPONSE_COMMANDS.put(command, new ResponseCommand(
            actor, pool, nn, rawNN, currentId, ids, role));
        emit("KEY_UPDATE_RESPONSE", producerFields(actor, pool, nn, rawNN,
            currentId, ids, role, command, dn)
            + ",\"responseObjectHash\":" + System.identityHashCode(response)
            + ",\"identityBound\":" + bound);
        if (bound) {
          faultSite = "BPServiceActor.offerService#keyUpdateResponse/" + nn;
          faultKind = producerPoint("FAULT:HDFS_KEY_UPDATE:RPC_RESPONSE",
              faultSite, actor, pool, nn, rawNN, currentId, ids, role, command, dn);
          if (faultKind != null) break;
        }
      }
    }
    if (faultKind != null) applyFault(faultKind, faultSite);
  }

  /** Command application is a local step; it is not mislabeled as an RPC. */
  public static void keyImportBefore(DataNode dn, String rawPool,
                                                  Object nnEndpoint, DatanodeCommand command)
      throws IOException {
    String faultKind = null;
    String faultSite = null;
    synchronized (HdfsKeyActorProbe.class) {
      Actor actor = DATA_NODES.get(dn);
      String pool = actor == null ? "unbound" : actor.pools.get(rawPool);
      if (pool == null) pool = "unbound";
      String rawNN = String.valueOf(nnEndpoint);
      String nn = actor == null ? "unbound" : actor.nameNode(rawNN);
      ResponseCommand seen = RESPONSE_COMMANDS.get(command);
      Manager manager = boundManager(dn, rawPool);
      ExportedBlockKeys exported = command instanceof KeyUpdateCommand
          ? ((KeyUpdateCommand) command).getExportedKeys() : null;
      int currentId = currentKeyId(exported);
      int[] ids = keyIds(exported);
      boolean same = seen != null && seen.actor == actor && seen.pool.equals(pool)
          && seen.nn.equals(nn) && seen.rawNN.equals(rawNN)
          && !"unbound".equals(rawDnUuid(dn)) && !"null".equals(rawNN)
          && seen.currentKeyId == currentId
          && Arrays.equals(seen.allKeyIds, ids) && manager != null
          && manager.actor == actor && manager.pool.equals(pool);
      emit("KEY_IMPORT_ATTEMPT", producerFields(actor, pool, nn, rawNN,
          currentId, ids, seen == null ? "UNLINKED" : seen.keyRole, command, dn)
          + ",\"responseCommandMatched\":" + same);
      if (same) {
        faultSite = "BPOfferService.processCommand#applyKeys/" + nn;
        faultKind = producerPoint("FAULT:HDFS_KEY_UPDATE:LOCAL_APPLY",
            faultSite, actor, pool, nn, rawNN, currentId, ids, seen.keyRole, command, dn);
      }
    }
    if (faultKind != null) applyFault(faultKind, faultSite);
  }

  public static synchronized void keyImportAfter(DataNode dn, String rawPool,
                                                 Object nnEndpoint, DatanodeCommand command) {
    Actor actor = DATA_NODES.get(dn);
    String pool = actor == null ? "unbound" : actor.pools.get(rawPool);
    if (pool == null) pool = "unbound";
    String rawNN = String.valueOf(nnEndpoint);
    String nn = actor == null ? "unbound" : actor.nameNode(rawNN);
    ResponseCommand seen = RESPONSE_COMMANDS.get(command);
    Manager manager = boundManager(dn, rawPool);
    ExportedBlockKeys exported = command instanceof KeyUpdateCommand
        ? ((KeyUpdateCommand) command).getExportedKeys() : null;
    int currentId = currentKeyId(exported);
    int[] ids = keyIds(exported);
    boolean same = seen != null && seen.actor == actor && seen.pool.equals(pool)
        && seen.nn.equals(nn) && seen.rawNN.equals(rawNN)
        && !"unbound".equals(rawDnUuid(dn)) && !"null".equals(rawNN)
        && seen.currentKeyId == currentId && Arrays.equals(seen.allKeyIds, ids)
        && manager != null && manager.actor == actor && manager.pool.equals(pool);
    emit("KEY_IMPORT_APPLIED", producerFields(actor, pool, nn, rawNN,
        currentId, ids,
        seen == null ? "UNLINKED" : seen.keyRole, command, dn)
        + ",\"responseCommandMatched\":" + same);
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
    if (!matchesFaultPlan(selected, marker, site, actorKey, pool, ordinal, -1)) return;
    emit("FAULT_MATCHED", fields + ",\"faultType\":" + q(selected[5])
        + ",\"requiredRawKeyId\":" + q(selected[6])
        + ",\"planIndex\":" + nextFault);
    emit("FAULT_APPLIED", fields + ",\"faultType\":" + q(selected[5])
        + ",\"requiredRawKeyId\":" + q(selected[6])
        + ",\"planIndex\":" + nextFault);
    nextFault++;
    applyFault(selected[5], site);
  }
}
