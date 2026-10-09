package org.apache.hadoop.hdfs.hdfs16independent;

import java.net.InetSocketAddress;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.WeakHashMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.apache.hadoop.conf.Configuration;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.hdfs.server.protocol.DatanodeRegistration;

/** Runtime identities for the unchanged two-DataNode MiniDFSCluster JUnit. */
public final class Hdfs16ActorRegistry {
  private static final class Actor {
    final int episode;
    final int slot;
    final String dataDirs;
    final String key;
    volatile String uuid;
    volatile InetSocketAddress namenode;

    Actor(int episode, int slot, String dataDirs) {
      this.episode = episode;
      this.slot = slot;
      this.dataDirs = dataDirs;
      this.key = "episode=" + episode + "/dn=" + slot + "/dirs=" + dataDirs;
    }
  }

  private static final class Registration {
    final Actor actor;
    final String uuid;
    final String rawPool;
    final String pool;
    final boolean manual;

    Registration(Actor actor, String uuid, String rawPool, String pool,
        boolean manual) {
      this.actor = actor;
      this.uuid = uuid;
      this.rawPool = rawPool;
      this.pool = pool;
      this.manual = manual;
    }
  }

  private static final Map<DataNode, Actor> DATA_NODES =
      Collections.synchronizedMap(new WeakHashMap<DataNode, Actor>());
  private static final Map<String, Actor> UUID_ACTORS = new HashMap<String, Actor>();
  private static final Map<Integer, Integer> EPISODE_SLOTS = new HashMap<Integer, Integer>();
  private static final Map<String, String> POOLS = new HashMap<String, String>();
  private static final ThreadLocal<Integer> START_EPISODE = new ThreadLocal<Integer>();
  private static final ThreadLocal<Actor> CURRENT_ACTOR = new ThreadLocal<Actor>();
  private static final ThreadLocal<Registration> CURRENT_REGISTRATION =
      new ThreadLocal<Registration>();
  private static volatile InetSocketAddress namenodeAddress;
  private static volatile String selectedUuid;
  private static volatile String selectedActor;
  private static volatile String selectedPool;
  private static int nextEpisode;

  private Hdfs16ActorRegistry() { }

  public static synchronized void startEpisode() {
    START_EPISODE.set(++nextEpisode);
  }

  public static void endEpisode() {
    START_EPISODE.remove();
  }

  private static String dataDirs(Configuration conf) {
    String raw = conf == null ? "" : conf.get("dfs.datanode.data.dir", "");
    Matcher matcher = Pattern.compile(
        "(?:^|/)dfs/(?:data/)?(data[0-9]+|datanodeMaster)(?:/|,|$)").matcher(raw);
    List<String> normalized = new ArrayList<String>();
    while (matcher.find()) {
      normalized.add("dfs/data/" + matcher.group(1));
    }
    Collections.sort(normalized);
    return normalized.isEmpty() ? "UNBOUND" : String.join(",", normalized);
  }

  /** Called before the DataNode starts its BPServiceActor thread. */
  public static DataNode registerDataNode(DataNode dn, Configuration conf) {
    Integer episode = START_EPISODE.get();
    if (dn == null || episode == null) {
      return dn;
    }
    synchronized (Hdfs16ActorRegistry.class) {
      if (DATA_NODES.containsKey(dn)) {
        return dn;
      }
      int slot = EPISODE_SLOTS.containsKey(episode)
          ? EPISODE_SLOTS.get(episode) + 1 : 1;
      EPISODE_SLOTS.put(episode, slot);
      DATA_NODES.put(dn, new Actor(episode, slot, dataDirs(conf)));
    }
    return dn;
  }

  /** The actual BPServiceActor provides its DataNode object and NN endpoint. */
  public static void enterActor(DataNode dn, InetSocketAddress namenode) {
    Actor actor = DATA_NODES.get(dn);
    CURRENT_ACTOR.set(actor);
    if (actor != null && namenode != null) {
      actor.namenode = namenode;
      namenodeAddress = namenode;
    }
  }

  public static void exitActor() {
    CURRENT_ACTOR.remove();
    CURRENT_REGISTRATION.remove();
  }

  private static boolean isManualTestRegistration() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if ("org.apache.hadoop.hdfs.TestClientProtocolForPipelineRecovery".equals(
              frame.getClassName()) &&
          "testUpdatePipeLineAfterDNReg".equals(frame.getMethodName())) {
        return true;
      }
    }
    return false;
  }

  /** Translator entry supplies the raw UUID before the RPC response door. */
  public static synchronized void beginRegistration(DatanodeRegistration value) {
    if (CURRENT_REGISTRATION.get() != null) {
      throw new IllegalStateException("nested DataNode registration context");
    }
    String uuid = value == null ? null : value.getDatanodeUuid();
    String rawPool = value == null || value.getNamespaceInfo() == null
        ? null : value.getNamespaceInfo().getBlockPoolID();
    String pool = null;
    if (rawPool != null) {
      pool = POOLS.get(rawPool);
      if (pool == null) {
        pool = "BP" + POOLS.size();
        POOLS.put(rawPool, pool);
      }
    }
    Actor actor = CURRENT_ACTOR.get();
    if (actor != null && uuid != null) {
      Actor previous = UUID_ACTORS.get(uuid);
      if (previous != null && previous != actor) {
        throw new IllegalStateException("DataNode UUID mapped to two actors");
      }
      actor.uuid = uuid;
      UUID_ACTORS.put(uuid, actor);
    } else if (uuid != null) {
      actor = UUID_ACTORS.get(uuid);
    }
    boolean manual = isManualTestRegistration();
    Registration context = new Registration(actor, uuid, rawPool, pool, manual);
    CURRENT_REGISTRATION.set(context);
    if (manual) {
      selectedUuid = uuid;
      selectedActor = actor == null ? null : actor.key;
      selectedPool = pool;
    }
  }

  public static void endRegistration() {
    CURRENT_REGISTRATION.remove();
  }

  public static String currentActorKey() {
    Registration registration = CURRENT_REGISTRATION.get();
    if (registration != null) {
      return registration.actor == null ? "UNBOUND" : registration.actor.key;
    }
    Actor actor = CURRENT_ACTOR.get();
    return actor == null ? "CLIENT" : actor.key;
  }

  public static String currentUuid() {
    Registration registration = CURRENT_REGISTRATION.get();
    return registration == null ? null : registration.uuid;
  }

  public static String currentRawPool() {
    Registration registration = CURRENT_REGISTRATION.get();
    return registration == null ? null : registration.rawPool;
  }

  public static String currentPool() {
    Registration registration = CURRENT_REGISTRATION.get();
    return registration == null ? null : registration.pool;
  }

  public static boolean manualRegistration() {
    Registration registration = CURRENT_REGISTRATION.get();
    return registration != null && registration.manual;
  }

  public static String selectedUuid() {
    return selectedUuid;
  }

  public static String selectedActorKey() {
    return selectedActor;
  }

  public static String selectedPool() {
    return selectedPool;
  }

  public static String peerClass(InetSocketAddress remote) {
    if (remote == null) {
      return "LOCAL_NN0";
    }
    InetSocketAddress known = namenodeAddress;
    if (known == null || known.getPort() != remote.getPort()) {
      return "UNBOUND";
    }
    if (known.getAddress() != null && remote.getAddress() != null &&
        !known.getAddress().equals(remote.getAddress())) {
      return "UNBOUND";
    }
    return "NN0";
  }
}
