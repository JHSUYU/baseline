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
import java.util.List;
import java.util.Map;
import java.util.WeakHashMap;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.hdfs.server.common.Storage.StorageDirectory;

/** Case-local recorder for exact storage guards and observed I/O identities. */
public final class HdfsStorageProbe {
  private static final String TRACE = System.getProperty("hdfsStorage.independent.trace", "");
  private static final String PLAN = System.getProperty("hdfsStorage.independent.plan", "");
  private static final Map<String, Integer> HITS = new HashMap<>();
  private static final Map<DataNode, Actor> ACTORS =
      Collections.synchronizedMap(new WeakHashMap<DataNode, Actor>());
  private static final Map<StorageDirectory, Actor> STORAGE_ACTORS =
      Collections.synchronizedMap(new WeakHashMap<StorageDirectory, Actor>());
  private static final ThreadLocal<Integer> START_EPISODE = new ThreadLocal<>();
  private static final ThreadLocal<Actor> CURRENT_ACTOR = new ThreadLocal<>();
  private static final ThreadLocal<Boolean> PRIMARY_ACTOR_THREAD = new ThreadLocal<>();
  private static final ThreadLocal<InetSocketAddress> CURRENT_NAMENODE = new ThreadLocal<>();
  private static final ThreadLocal<String> CURRENT_STORAGE = new ThreadLocal<>();
  private static int nextEpisode;
  private static int nextDnObject;
  private static final Map<Integer, Integer> EPISODE_SLOTS = new HashMap<>();
  private static final List<String[]> FAULTS = new ArrayList<>();
  private static int nextFault;
  private static BufferedWriter writer;
  private static long seq;

  private static final class Actor {
    final String key;
    final String dataDirs;
    final int episode;
    final int slot;
    final int objectId;
    Actor(int episode, int slot, String dataDirs, int objectId) {
      this.episode = episode;
      this.slot = slot;
      this.dataDirs = dataDirs;
      this.objectId = objectId;
      this.key = "episode=" + episode + "/dn=" + slot + "/dirs=" + dataDirs;
    }
  }

  /** The deepest MiniDFSCluster.startDataNodes overload is called once per startup. */
  public static synchronized void startEpisode() {
    int episode = ++nextEpisode;
    START_EPISODE.set(episode);
    emit("START_EPISODE", ",\"episode\":" + episode);
  }

  public static void endEpisode() { START_EPISODE.remove(); }

  private static String dataDirs(Configuration conf) {
    String raw = conf == null ? "" : conf.get("dfs.datanode.data.dir", "");
    List<String> dirs = new ArrayList<>();
    for (String item : raw.split(",")) {
      java.util.regex.Matcher m = java.util.regex.Pattern.compile("(?:^|/)dfs/(data[0-9]+)(?:/|$)").matcher(item);
      if (m.find()) dirs.add("dfs/" + m.group(1));
    }
    Collections.sort(dirs);
    return dirs.isEmpty() ? "unbound" : String.join(",", dirs);
  }

  public static DataNode registerDataNode(DataNode dn, Configuration conf) {
    Integer episode = START_EPISODE.get();
    if (dn == null || episode == null) {
      emit("ACTOR_UNBOUND", ",\"reason\":\"missing_start_episode\"");
      return dn;
    }
    Actor actor;
    synchronized (HdfsStorageProbe.class) {
      int slot = EPISODE_SLOTS.containsKey(episode) ? EPISODE_SLOTS.get(episode) + 1 : 1;
      EPISODE_SLOTS.put(episode, slot);
      actor = new Actor(episode, slot, dataDirs(conf), ++nextDnObject);
      ACTORS.put(dn, actor);
    }
    emit("ACTOR_REGISTERED", ",\"actorKey\":" + q(actor.key)
        + ",\"dnObjectId\":" + actor.objectId
        + ",\"dnObjectHash\":" + System.identityHashCode(dn)
        + ",\"configuredDataDirsRaw\":" + q(conf.get("dfs.datanode.data.dir", "")));
    return dn;
  }

  /** BPServiceActor.run supplies its actual DataNode and configured NN address. */
  public static void enterActor(DataNode dn, InetSocketAddress namenode) {
    Actor actor = ACTORS.get(dn);
    CURRENT_ACTOR.set(actor);
    PRIMARY_ACTOR_THREAD.set(Boolean.TRUE);
    CURRENT_NAMENODE.set(namenode);
    CURRENT_STORAGE.remove();
    if (actor == null || "unbound".equals(actor.dataDirs)) {
      emit("ACTOR_UNBOUND", ",\"reason\":\"unregistered_datanode_or_dirs\""
          + ",\"dnObjectId\":" + System.identityHashCode(dn));
    } else {
      emit("ACTOR_ENTER", ",\"actorKey\":" + q(actor.key)
          + ",\"dnObjectId\":" + actor.objectId
          + ",\"namenodeEndpoint\":" + q(namenode));
    }
  }

  public static void exitActor() {
    CURRENT_ACTOR.remove();
    PRIMARY_ACTOR_THREAD.remove();
    CURRENT_NAMENODE.remove();
    CURRENT_STORAGE.remove();
  }

  private static String storageKey(StorageDirectory sd) {
    if (sd == null || sd.getRoot() == null) return "unbound";
    String path = sd.getRoot().getAbsolutePath().replace('\\', '/');
    int pos = path.indexOf("/data/dfs/");
    if (pos < 0) return "unbound";
    return path.substring(pos + 6).replaceAll("BP-[^/]+", "BP-ID");
  }

  public static void enterStorage(StorageDirectory sd) {
    CURRENT_STORAGE.set(storageKey(sd));
    Actor mapped = STORAGE_ACTORS.get(sd);
    if (mapped != null) {
      if (CURRENT_ACTOR.get() != mapped) {
        CURRENT_ACTOR.set(mapped);
        PRIMARY_ACTOR_THREAD.set(Boolean.FALSE);
        CURRENT_NAMENODE.remove();
        emit("ACTOR_REJOIN_STORAGE", ",\"actorKey\":" + q(mapped.key));
      }
    } else if (Boolean.TRUE.equals(PRIMARY_ACTOR_THREAD.get()) && CURRENT_ACTOR.get() != null) {
      STORAGE_ACTORS.put(sd, CURRENT_ACTOR.get());
    } else {
      // A reused executor thread must not carry a previous storage task's actor.
      CURRENT_ACTOR.remove();
      PRIMARY_ACTOR_THREAD.set(Boolean.FALSE);
      CURRENT_NAMENODE.remove();
    }
  }

  private static String actorFields() {
    Actor actor = CURRENT_ACTOR.get();
    return ",\"actorKey\":" + q(actor == null ? "unbound" : actor.key)
        + ",\"storageKey\":" + q(CURRENT_STORAGE.get() == null ? "unbound" : CURRENT_STORAGE.get())
        + ",\"dnObjectId\":" + (actor == null ? -1 : actor.objectId)
        + ",\"startupEpisode\":" + (actor == null ? -1 : actor.episode)
        + ",\"dnSlot\":" + (actor == null ? -1 : actor.slot);
  }

  static {
    try {
      if (!TRACE.isEmpty()) writer = new BufferedWriter(new FileWriter(TRACE));
      if (!PLAN.isEmpty()) {
        for (String line : Files.readAllLines(Paths.get(PLAN), StandardCharsets.UTF_8)) {
          if (!line.isEmpty() && !line.startsWith("#")) FAULTS.add(line.split("\t", -1));
        }
      }
      Runtime.getRuntime().addShutdownHook(new Thread(() -> {
        synchronized (HdfsStorageProbe.class) {
          try { if (writer != null) writer.close(); } catch (IOException ignored) { }
        }
      }));
    } catch (IOException ex) { throw new ExceptionInInitializerError(ex); }
  }

  private HdfsStorageProbe() { }

  private static String q(Object s) {
    return "\"" + String.valueOf(s).replace("\\", "\\\\").replace("\"", "\\\"")
        .replace("\n", "\\n").replace("\r", "\\r") + "\"";
  }

  private static void emit(String event, String fields) {
    synchronized (HdfsStorageProbe.class) {
      if (writer == null) return;
      try {
        boolean contextual = event.startsWith("FAULT_") || event.startsWith("TARGET_");
        writer.write("{\"event\":" + q(event) + ",\"seq\":" + (++seq)
            + ",\"thread\":" + q(Thread.currentThread().getName())
            + (contextual ? actorFields() : "") + fields + "}\n");
        writer.flush();
      } catch (IOException ex) { throw new RuntimeException(ex); }
    }
  }

  public static void namespaceCheck(int datanodeId, int namenodeId) {
    emit("TARGET_CHECK", ",\"siteId\":\"BlockPoolSliceStorage.doTransition#L392-IF_ICMPEQ\""
        + ",\"caseId\":\"HDFS-22\",\"equal\":" + (datanodeId == namenodeId)
        + ",\"datanodeNamespaceId\":" + datanodeId + ",\"namenodeNamespaceId\":" + namenodeId);
  }

  public static void blockpoolCheck(int equal) {
    emit("TARGET_CHECK", ",\"siteId\":\"BlockPoolSliceStorage.doTransition#L398-IFNE\""
        + ",\"caseId\":\"HDFS-23\",\"equal\":" + (equal != 0));
  }

  public static void ctimeCheck(int comparison) {
    emit("TARGET_CHECK", ",\"siteId\":\"BlockPoolSliceStorage.loadStorageDirectory#L184-IFEQ\""
        + ",\"caseId\":\"HDFS-25\",\"equal\":" + (comparison == 0));
  }

  public static void storageNamespaceCheck(int datanodeId, int namenodeId) {
    emit("TARGET_CHECK", ",\"siteId\":\"DataStorage.doTransition#L740-IF_ICMPEQ\""
        + ",\"caseId\":\"HDFS-34\",\"equal\":" + (datanodeId == namenodeId)
        + ",\"datanodeNamespaceId\":" + datanodeId + ",\"namenodeNamespaceId\":" + namenodeId);
  }

  public static void clusterCheck(int equal) {
    emit("TARGET_CHECK", ",\"siteId\":\"DataStorage.doTransition#L749-IFNE\""
        + ",\"caseId\":\"HDFS-35\",\"equal\":" + (equal != 0));
  }

  public static void transitionLayoutCheck(int stored, int software) {
    emit("TARGET_CHECK", ",\"siteId\":\"BlockPoolSliceStorage.doTransition#L414-IF_ICMPGT\""
        + ",\"caseId\":\"HDFS-24\",\"storedLayoutVersion\":" + stored
        + ",\"softwareLayoutVersion\":" + software
        + ",\"upgrade\":" + (stored > software));
  }

  public static void transitionCTimeCheck(int comparison) {
    emit("TARGET_CHECK", ",\"siteId\":\"BlockPoolSliceStorage.doTransition#L415-IFGE\""
        + ",\"caseId\":\"HDFS-24\",\"upgrade\":" + (comparison < 0));
  }

  public static void rollbackLayoutCheck(int previous, int software) {
    emit("TARGET_CHECK", ",\"siteId\":\"BlockPoolSliceStorage.doRollback#L619-IF_ICMPLT\""
        + ",\"caseId\":\"HDFS-26\",\"previousLayoutVersion\":" + previous
        + ",\"softwareLayoutVersion\":" + software
        + ",\"reject\":" + (previous < software));
  }

  public static void rollbackCTimeCheck(int comparison) {
    emit("TARGET_CHECK", ",\"siteId\":\"BlockPoolSliceStorage.doRollback#L620-IFLE\""
        + ",\"caseId\":\"HDFS-26\",\"reject\":" + (comparison > 0));
  }

  public static void dataRollbackLayoutCheck(int previous, int software) {
    emit("TARGET_CHECK", ",\"siteId\":\"DataStorage.doRollback#L940-IF_ICMPLT\""
        + ",\"caseId\":\"HDFS-37\",\"previousLayoutVersion\":" + previous
        + ",\"softwareLayoutVersion\":" + software
        + ",\"reject\":" + (previous < software));
  }

  public static void dataRollbackCTimeCheck(int comparison) {
    emit("TARGET_CHECK", ",\"siteId\":\"DataStorage.doRollback#L941-IFLE\""
        + ",\"caseId\":\"HDFS-37\",\"reject\":" + (comparison > 0));
  }

  public static void upgradeNamespaceCheck(int datanodeId, int namenodeId) {
    emit("TARGET_CHECK", ",\"siteId\":\"BlockPoolSliceStorage.doUpgrade#L510-IF_ICMPEQ\""
        + ",\"caseId\":\"HDFS-27\",\"equal\":" + (datanodeId == namenodeId)
        + ",\"datanodeNamespaceId\":" + datanodeId
        + ",\"namenodeNamespaceId\":" + namenodeId);
  }

  public static void targetThrow(String caseId, Throwable ex) {
    emit("TARGET_THROW", ",\"caseId\":" + q(caseId)
        + ",\"exception\":" + q(ex.getClass().getName())
        + ",\"message\":" + q(ex.getMessage()));
  }

  public static void versionRead(StorageDirectory directory) throws IOException {
    enterStorage(directory);
    String path = directory.getRoot().getCanonicalPath();
    int start = path.indexOf("/data/");
    String source = (start < 0 ? directory.getRoot().getName() : path.substring(start + 6))
        .replaceAll("BP-[^/]+", "BP-ID");
    ioFile("FAULT:HDFS_BP_FILE:VERSION_READ", "BlockPoolSliceStorage.readProperties", source, path);
  }

  public static void dataVersionRead(StorageDirectory directory) throws IOException {
    enterStorage(directory);
    String path = directory.getRoot().getCanonicalPath();
    int start = path.indexOf("/data/");
    String source = (start < 0 ? directory.getRoot().getName() : path.substring(start + 6))
        .replaceAll("BP-[^/]+", "BP-ID");
    ioFile("FAULT:HDFS_BP_FILE:DN_VERSION_READ", "DataStorage.readProperties", source, path);
  }

  public static void previousVersionRead(StorageDirectory directory) throws IOException {
    enterStorage(directory);
    String path = directory.getRoot().getCanonicalPath();
    int start = path.indexOf("/data/");
    String source = (start < 0 ? directory.getRoot().getName() : path.substring(start + 6))
        .replaceAll("BP-[^/]+", "BP-ID");
    ioFile("FAULT:HDFS_BP_FILE:PREVIOUS_VERSION_READ",
        "BlockPoolSliceStorage.readPreviousVersionProperties", source, path);
  }

  public static void dataPreviousVersionRead(StorageDirectory directory) throws IOException {
    enterStorage(directory);
    String path = directory.getRoot().getCanonicalPath();
    int start = path.indexOf("/data/");
    String source = (start < 0 ? directory.getRoot().getName() : path.substring(start + 6))
        .replaceAll("BP-[^/]+", "BP-ID");
    ioFile("FAULT:HDFS_BP_FILE:DN_PREVIOUS_VERSION_READ",
        "DataStorage.readPreviousVersionProperties", source, path);
  }

  public static void ipcResponse(InetSocketAddress endpoint) throws IOException {
    Actor actor = CURRENT_ACTOR.get();
    InetSocketAddress namenode = CURRENT_NAMENODE.get();
    boolean mapped = actor != null && namenode != null && namenode.equals(endpoint);
    String source = mapped ? actor.key + "/peer=NN0" : "unbound";
    io("FAULT:HDFS_BP_RPC:RESPONSE", "Client.getRpcResponse", source,
        ",\"endpointRaw\":" + q(endpoint)
        + ",\"actorNamenodeRaw\":" + q(namenode)
        + ",\"peerRole\":" + q(mapped ? "NN0" : "unbound"));
  }

  private static void ioFile(String marker, String site, String source, String rawPath)
      throws IOException {
    Actor actor = CURRENT_ACTOR.get();
    String storage = CURRENT_STORAGE.get();
    String keyed = actor != null && !"unbound".equals(actor.dataDirs)
        && storage != null && !"unbound".equals(storage)
        ? actor.key + "/storage=" + storage : "unbound";
    io(marker, site, keyed, ",\"filePathRaw\":" + q(rawPath)
        + ",\"filePathNormalized\":" + q(source));
  }

  private static void io(String marker, String site, String source, String rawFields)
      throws IOException {
    String key = marker + "|" + site + "|" + source;
    int ordinal;
    String kind = null;
    int matchedIndex = -1;
    synchronized (HdfsStorageProbe.class) {
      ordinal = HITS.containsKey(key) ? HITS.get(key) + 1 : 1;
      HITS.put(key, ordinal);
      String fields = ",\"marker\":" + q(marker) + ",\"siteId\":" + q(site)
          + ",\"sourceKey\":" + q(source) + ",\"occurrence\":" + q(source + "/" + site)
          + ",\"hitOrdinal\":" + ordinal + rawFields;
      emit("FAULT_POINT_OBSERVED", fields);
      // A plan step is consumed only in sequence, with a bound actor and peer.
      if (!"unbound".equals(source) && nextFault < FAULTS.size()) {
        String[] fault = FAULTS.get(nextFault);
        if (fault.length >= 6 && fault[0].equals(marker) && fault[1].equals(site)
            && fault[2].equals(source) && Integer.parseInt(fault[3]) == ordinal) {
          matchedIndex = nextFault++;
          kind = fault[5];
          fault[4] = "applied";
          emit("FAULT_MATCHED", fields + ",\"faultIndex\":" + matchedIndex
              + ",\"faultType\":" + q(kind));
          emit("FAULT_APPLIED", fields + ",\"faultIndex\":" + matchedIndex
              + ",\"faultType\":" + q(kind));
        }
      }
    }
    if (kind != null) {
      String message = "HDFS storage V2 injected " + kind + " at " + site + ":" + ordinal;
      if (kind.equals("SocketTimeoutException")) throw new java.net.SocketTimeoutException(message);
      if (kind.equals("EOFException")) throw new java.io.EOFException(message);
      if (kind.equals("FileNotFoundException")) throw new java.io.FileNotFoundException(message);
      if (!kind.equals("IOException")) throw new IllegalArgumentException("Unknown fault: " + kind);
      throw new IOException(message);
    }
  }
}
