package org.apache.hadoop.hdfs.server.balancer;

import java.io.IOException;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import org.apache.hadoop.hdfs.protocol.DatanodeID;
import org.apache.hadoop.hdfs.protocol.datatransfer.sasl.DataEncryptionKeyFactory;
import org.apache.hadoop.hdfs.security.token.block.BlockKey;
import org.apache.hadoop.hdfs.security.token.block.BlockTokenSecretManager;
import org.apache.hadoop.hdfs.security.token.block.DataEncryptionKey;
import org.apache.hadoop.hdfs.security.token.block.ExportedBlockKeys;
import org.apache.hadoop.hdfs.server.protocol.NamenodeProtocol;
import org.apache.hadoop.ipc.RPC;

/** Observes natural NN/DN key state and faults only Balancer updater RPCs. */
public final class Hdfs55FaithfulProbe {
  private static final boolean INJECT = Boolean.getBoolean("hdfs55f.inject");
  private static final long WAIT_MS = Long.getLong("hdfs55f.waitMs", 80000L);
  private static final int MAX_UPDATER_IO = Integer.getInteger("hdfs55f.maxUpdaterIo", 512);
  private static final long MAX_OUTAGE_MS = Long.getLong("hdfs55f.maxOutageMs", 120000L);
  private static final Map<Integer, Set<Integer>> DN_KEYS = new HashMap<>();
  private static final Map<Integer, String> DN_UUID = new HashMap<>();
  private static final Map<Integer, String> DN_ENDPOINT = new HashMap<>();
  private static final ThreadLocal<String> CLIENT_TARGET = new ThreadLocal<>();
  private static final ThreadLocal<String> SERVER_ENDPOINT = new ThreadLocal<>();
  private static volatile BlockTokenSecretManager nnMaster;
  private static String selectedDnUuid;
  private static String selectedDnEndpoint;
  private static String selectedBlockPool;
  private static int startupCurrent;
  private static int startupNext;
  private static int selectedKey;
  private static int selectedManager;
  private static int selectedNnProxy;
  private static String selectedNnEndpoint;
  private static int updaterFaults;
  private static long firstUpdaterFaultNano;
  private static boolean outageCapLogged;
  private static boolean managerSelected;
  private static boolean moveReleased;

  private Hdfs55FaithfulProbe() { }

  private static void event(String value) {
    System.out.println("CASE55F " + value + " nano=" + System.nanoTime());
  }

  private static String digest(byte[] nonce) {
    if (nonce == null) return "none";
    try {
      byte[] bytes = MessageDigest.getInstance("SHA-256").digest(nonce);
      StringBuilder out = new StringBuilder();
      for (int i = 0; i < 8; i++) out.append(String.format("%02x", bytes[i] & 0xff));
      return out.toString();
    } catch (NoSuchAlgorithmException e) {
      throw new IllegalStateException(e);
    }
  }

  private static boolean sameXferEndpoint(String left, String right) {
    if (left == null || right == null || !left.contains(":") || !right.contains(":"))
      return false;
    return left.substring(left.lastIndexOf(':')).equals(
        right.substring(right.lastIndexOf(':')));
  }

  private static int nextId(ExportedBlockKeys keys) {
    int current = keys.getCurrentKey().getKeyId();
    int next = current;
    long expiry = Long.MIN_VALUE;
    for (BlockKey key : keys.getAllKeys()) {
      if (key != null && key.getKeyId() != current && key.getExpiryDate() > expiry) {
        next = key.getKeyId();
        expiry = key.getExpiryDate();
      }
    }
    return next;
  }

  /** Called after the MiniDFSCluster first becomes active, before file creation. */
  public static synchronized void configure(BlockTokenSecretManager master) {
    if (nnMaster != null) throw new IllegalStateException("faithful setup repeated");
    nnMaster = master;
    ExportedBlockKeys startup = master.exportKeys();
    startupCurrent = startup.getCurrentKey().getKeyId();
    startupNext = nextId(startup);
    master.setKeyUpdateIntervalForTesting(2000L);
    master.setTokenLifetime(2000L);
    event("nn_setup startup_current=" + startupCurrent + " startup_next=" + startupNext
        + " update_ms=2000 lifetime_ms=2000");
  }

  /** Called after the empty target DN has joined and before Balancer starts. */
  public static void selectDestination(String uuid, String endpoint) throws Exception {
    synchronized (Hdfs55FaithfulProbe.class) {
      if (nnMaster == null) throw new IllegalStateException("NN master not configured");
      selectedDnUuid = uuid;
      selectedDnEndpoint = endpoint;
      event("destination uuid=" + uuid + " endpoint=" + endpoint);
    }
    long deadline = System.currentTimeMillis() + WAIT_MS;
    while (System.currentTimeMillis() < deadline) {
      synchronized (Hdfs55FaithfulProbe.class) {
        ExportedBlockKeys keys = nnMaster.exportKeys();
        BlockKey current = keys.getCurrentKey();
        int id = current.getKeyId();
        if (id != startupCurrent && id != startupNext
            && current.getExpiryDate() - System.currentTimeMillis() < 30000L) {
          for (Map.Entry<Integer, String> entry : DN_UUID.entrySet()) {
            if (uuid.equals(entry.getValue()) && DN_KEYS.containsKey(entry.getKey())
                && DN_KEYS.get(entry.getKey()).contains(id)) {
              selectedKey = id;
              event("fresh_key_selected key_id=" + id + " expiry="
                  + current.getExpiryDate() + " dn_uuid=" + uuid
                  + " dn_manager=" + entry.getKey() + " dn_endpoint=" + endpoint);
              return;
            }
          }
        }
      }
      Thread.sleep(50L);
    }
    throw new AssertionError("fresh post-start key not installed on destination DN");
  }

  /** The constructor's first getBlockKeys has succeeded; the updater is separate. */
  public static synchronized void managerConstructed(KeyManager manager,
      NamenodeProtocol namenode, String bpid, ExportedBlockKeys keys) {
    int current = keys.getCurrentKey().getKeyId();
    String nnEndpoint = RPC.getServerAddress(namenode).toString();
    event("manager_constructed manager=" + System.identityHashCode(manager)
        + " nn_proxy=" + System.identityHashCode(namenode)
        + " nn_endpoint=" + nnEndpoint + " bpid=" + bpid
        + " key_id=" + current + " selected_key=" + selectedKey);
    if (selectedKey != 0 && current == selectedKey && !managerSelected) {
      selectedManager = System.identityHashCode(manager);
      selectedNnProxy = System.identityHashCode(namenode);
      selectedNnEndpoint = nnEndpoint;
      selectedBlockPool = bpid;
      managerSelected = true;
      event("manager_selected manager=" + selectedManager + " nn_proxy="
          + selectedNnProxy + " nn_endpoint=" + selectedNnEndpoint
          + " bpid=" + bpid + " key_id=" + selectedKey);
    }
  }

  /** Exact hook in KeyManager.BlockKeyUpdater.run, before its NN RPC. */
  public static synchronized void beforeUpdaterGetBlockKeys(KeyManager manager,
      NamenodeProtocol namenode) throws IOException {
    if (!INJECT || !managerSelected || System.identityHashCode(manager) != selectedManager
        || System.identityHashCode(namenode) != selectedNnProxy
        || !selectedNnEndpoint.equals(RPC.getServerAddress(namenode).toString())) return;
    long now = System.nanoTime();
    if (firstUpdaterFaultNano == 0L) firstUpdaterFaultNano = now;
    long elapsedMs = (now - firstUpdaterFaultNano) / 1000000L;
    if (updaterFaults >= MAX_UPDATER_IO || elapsedMs >= MAX_OUTAGE_MS) {
      if (!outageCapLogged) {
        outageCapLogged = true;
        event("updater_outage_cap_reached manager=" + selectedManager
            + " nn_proxy=" + selectedNnProxy + " nn_endpoint=" + selectedNnEndpoint
            + " bpid=" + selectedBlockPool + " key_id=" + selectedKey
            + " count=" + updaterFaults + " elapsed_ms=" + elapsedMs
            + " max_calls=" + MAX_UPDATER_IO + " max_outage_ms=" + MAX_OUTAGE_MS);
      }
      return;
    }
    ++updaterFaults;
    event("updater_io_exception ordinal=" + updaterFaults + " manager="
        + selectedManager + " nn_proxy=" + selectedNnProxy + " bpid="
        + selectedBlockPool + " nn_endpoint=" + selectedNnEndpoint
        + " key_id=" + selectedKey
        + " actor=" + Thread.currentThread().getName()
        + " elapsed_ms=" + elapsedMs + " budget_ok=true");
    throw new IOException("HDFS-55 faithful Balancer background updater I/O outage");
  }

  /** The fixed foreground refetch is deliberately outside the outage hook. */
  public static synchronized void foregroundKeysFetched(KeyManager manager,
      NamenodeProtocol namenode, ExportedBlockKeys keys) {
    event("foreground_keys_fetched manager=" + System.identityHashCode(manager)
        + " nn_proxy=" + System.identityHashCode(namenode)
        + " nn_endpoint=" + RPC.getServerAddress(namenode)
        + " current_key=" + keys.getCurrentKey().getKeyId()
        + " bpid=" + selectedBlockPool);
  }

  /** Registered after the actual DN addKeys returns. */
  public static synchronized void dnKeysApplied(String uuid, String endpoint,
      String bpid, BlockTokenSecretManager manager, ExportedBlockKeys keys) {
    int identity = System.identityHashCode(manager);
    DN_UUID.put(identity, uuid);
    DN_ENDPOINT.put(identity, endpoint);
    StringBuilder ids = new StringBuilder();
    for (BlockKey key : keys.getAllKeys()) {
      if (key != null) ids.append(key.getKeyId()).append(',');
    }
    event("dn_add_keys uuid=" + uuid + " endpoint=" + endpoint + " bpid="
        + bpid + " manager=" + identity + " exported_ids=" + ids);
  }

  /** Called within the worker's synchronized addKeys after the map mutation. */
  public static synchronized void dnMapAfterAdd(BlockTokenSecretManager manager,
      String bpid, Set<Integer> actualKeys) {
    int identity = System.identityHashCode(manager);
    DN_KEYS.put(identity, new HashSet<>(actualKeys));
    event("dn_map_after_add manager=" + identity + " bpid=" + bpid
        + " selected_key=" + selectedKey + " selected_present="
        + actualKeys.contains(selectedKey) + " actual_ids=" + actualKeys);
  }

  /** Read-only NN rotation observation after the released map update. */
  public static void nnRotation(BlockTokenSecretManager manager,
      BlockKey current, BlockKey next, Set<Integer> actualKeys) {
    if (manager != nnMaster) return;
    event("nn_rotation current=" + current.getKeyId()
        + " current_expiry=" + current.getExpiryDate()
        + " next=" + next.getKeyId() + " next_expiry=" + next.getExpiryDate()
        + " actual_ids=" + actualKeys);
  }

  /** Hold only the first move, without changing a key or lookup result. */
  public static void beforeMove(String targetUuid, String endpoint) throws IOException {
    synchronized (Hdfs55FaithfulProbe.class) {
      if (moveReleased || !INJECT) return;
      if (!managerSelected || selectedKey == 0 || !targetUuid.equals(selectedDnUuid)
          || !sameXferEndpoint(endpoint, selectedDnEndpoint)) {
        throw new IOException("faithful first-move identity gate failed");
      }
      event("move_hold target_uuid=" + targetUuid + " endpoint=" + endpoint
          + " manager=" + selectedManager + " key_id=" + selectedKey);
    }
    long deadline = System.currentTimeMillis() + WAIT_MS;
    while (System.currentTimeMillis() < deadline) {
      synchronized (Hdfs55FaithfulProbe.class) {
        ExportedBlockKeys nnKeys = nnMaster.exportKeys();
        int current = nnKeys.getCurrentKey().getKeyId();
        boolean nnHasStale = false;
        for (BlockKey key : nnKeys.getAllKeys()) {
          if (key != null && key.getKeyId() == selectedKey) nnHasStale = true;
        }
        for (Map.Entry<Integer, String> entry : DN_UUID.entrySet()) {
          Set<Integer> actual = DN_KEYS.get(entry.getKey());
          if (targetUuid.equals(entry.getValue()) && actual != null
              && !actual.contains(selectedKey) && actual.contains(current)
              && !nnHasStale && current != selectedKey && updaterFaults > 0) {
            moveReleased = true;
            event("move_release target_uuid=" + targetUuid + " endpoint=" + endpoint
                + " dn_manager=" + entry.getKey() + " stale_key=" + selectedKey
                + " nn_current=" + current + " dn_has_current=true"
                + " dn_has_stale=false nn_has_stale=false updater_io=" + updaterFaults);
            return;
          }
        }
      }
      try { Thread.sleep(50L); }
      catch (InterruptedException e) { Thread.currentThread().interrupt();
        throw new IOException("faithful move gate interrupted", e); }
    }
    throw new IOException("faithful move gate timed out before natural DN prune");
  }

  public static void beforeSocketSend(DataEncryptionKeyFactory factory,
      DatanodeID target) {
    if (!(factory instanceof KeyManager)) return;
    CLIENT_TARGET.set(target.getXferAddr());
    event("socket_send manager=" + System.identityHashCode(factory)
        + " target_uuid=" + target.getDatanodeUuid()
        + " target_endpoint=" + target.getXferAddr());
  }

  public static void observeKeyCheck(KeyManager manager,
      DataEncryptionKey cached, boolean refresh) {
    event("key_guard manager=" + System.identityHashCode(manager)
        + " cached_key_id=" + (cached == null ? "none" : cached.keyId)
        + " cached_nonce_digest=" + (cached == null ? "none" : digest(cached.nonce))
        + " refresh=" + refresh + " target_endpoint=" + CLIENT_TARGET.get());
  }

  public static void observeKeyDecision(KeyManager manager,
      DataEncryptionKey key, boolean refresh) {
    event("key_decision manager=" + System.identityHashCode(manager)
        + " key_id=" + (key == null ? "none" : key.keyId)
        + " nonce_digest=" + (key == null ? "none" : digest(key.nonce))
        + " refresh=" + refresh + " target_endpoint=" + CLIENT_TARGET.get());
  }

  public static void enterDnPeer(String endpoint) {
    SERVER_ENDPOINT.set(endpoint);
  }

  /** Exact post-get observation; never writes the map or changes the branch. */
  public static synchronized void observeAllKeys(BlockTokenSecretManager manager,
      String bpid, int keyId, byte[] nonce, boolean present) {
    int identity = System.identityHashCode(manager);
    event("dn_allkeys manager=" + identity + " dn_uuid=" + DN_UUID.get(identity)
        + " dn_endpoint=" + DN_ENDPOINT.get(identity)
        + " peer_endpoint=" + SERVER_ENDPOINT.get() + " bpid=" + bpid
        + " key_id=" + keyId + " nonce_digest=" + digest(nonce)
        + " present=" + present);
  }

  public static void markDnInvalidKeyResponse(String message) {
    event("dn_wire_error_response=INVALID_KEY peer_endpoint="
        + SERVER_ENDPOINT.get() + " message=" + message);
  }

  public static void markKeyCleared() {
    event("balancer_key_cache_cleared=true");
  }
}
