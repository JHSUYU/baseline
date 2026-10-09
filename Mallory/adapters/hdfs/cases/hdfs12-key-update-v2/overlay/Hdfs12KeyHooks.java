package edu.uva.liftlab.mallory.adapters.hdfs;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** HDFS-12 metadata observations. This class never reads BlockKey.getKey(). */
public final class Hdfs12KeyHooks {
  private static final ThreadLocal<Rotation> ROTATION = new ThreadLocal<Rotation>();
  private static final Object KEY_STATE_LOCK = new Object();
  private static final IdentityHashMap<Object, ManagerState> MANAGERS =
      new IdentityHashMap<Object, ManagerState>();
  private static final IdentityHashMap<Object, Long> VALUES =
      new IdentityHashMap<Object, Long>();
  private static long nextManagerId;
  private static long nextValueId;

  private Hdfs12KeyHooks() { }

  public static void rotation(Object manager, boolean changed) {
    ROTATION.remove();
    if (!changed) return;
    try {
      String bpid = string(field(manager, "blockPoolId"));
      int current = keyId(field(manager, "currentKey"));
      int next = keyId(field(manager, "nextKey"));
      ROTATION.set(new Rotation(bpid, current, next));
      emit("nn_rotation_current", bpid, bpid, current, null, -1L, null);
      emit("nn_rotation_next", bpid, bpid, next, null, -1L, null);
    } catch (ReflectiveOperationException | RuntimeException failure) {
      gap("nn_rotation");
    }
  }

  /** Called after the monitor's setter; the rotation and setter share its thread. */
  public static void pending(Object descriptor, boolean value) {
    if (!value) return;
    Rotation rotation = ROTATION.get();
    if (rotation == null) { gap("nn_pending_without_rotation"); return; }
    try {
      String peer = string(invoke(descriptor, "getDatanodeUuid"));
      emit("nn_pending_true", rotation.bpid, rotation.bpid, rotation.next,
          peer, -1L, Boolean.TRUE);
    } catch (ReflectiveOperationException | RuntimeException failure) {
      gap("nn_pending_identity");
    }
  }

  /** Called before setNeedKeyUpdate(false), after command construction. */
  public static void commandPrepared(Object blockManager, Object commands, Object descriptor) {
    try {
      Object manager = field(blockManager, "blockTokenSecretManager");
      String bpid = string(field(manager, "blockPoolId"));
      String peer = string(invoke(descriptor, "getDatanodeUuid"));
      List<?> queued = (List<?>) commands;
      Object exported = invoke(queued.get(queued.size() - 1), "getExportedKeys");
      for (Object key : (Object[]) invoke(exported, "getAllKeys")) {
        if (key != null)
          emit("nn_command_key", bpid, bpid, keyId(key), peer, -1L, Boolean.FALSE);
      }
    } catch (ReflectiveOperationException | RuntimeException failure) {
      gap("nn_command_identity");
    }
  }

  /** Called on normal return from the worker's synchronized addKeys. */
  public static void added(Object manager, Object exported) {
    if (exported == null) return;
    try {
      if (Boolean.TRUE.equals(field(manager, "isMaster"))) return;
      String bpid = string(field(manager, "blockPoolId"));
      @SuppressWarnings("unchecked")
      Map<Integer, Object> actual = (Map<Integer, Object>) field(manager, "allKeys");
      Object[] exportedKeys = (Object[]) invoke(exported, "getAllKeys");
      List<KeyStateRow> states = new ArrayList<KeyStateRow>();
      synchronized (KEY_STATE_LOCK) {
        ManagerState state = managerState(manager);
        Set<Integer> exportedIds = new HashSet<Integer>();
        for (Object key : exportedKeys) {
          if (key == null) continue;
          int id = keyId(key);
          exportedIds.add(id);
          Object value = actual.get(id);
          KeyValue prior = state.keys.get(id);
          long version = prior == null ? 1L : prior.version + 1L;
          boolean matched = value == key;
          state.keys.put(id, new KeyValue(value, version));
          states.add(new KeyStateRow("write", bpid, state.id, id, version,
              valueId(value), matched));
        }
        // removeExpiredKeys runs inside the same manager monitor before the
        // exported puts. Account for removals of previously tracked keys.
        for (Map.Entry<Integer, KeyValue> tracked : state.keys.entrySet()) {
          int id = tracked.getKey();
          if (exportedIds.contains(id)) continue;
          Object value = actual.get(id);
          if (tracked.getValue().value == value) continue;
          long version = tracked.getValue().version + 1L;
          tracked.setValue(new KeyValue(value, version));
          states.add(new KeyStateRow(value == null ? "remove" : "write_gap",
              bpid, state.id, id, version, valueId(value), value == null));
        }
      }
      for (KeyStateRow row : states) {
        if ("write".equals(row.phase))
          emit("dn_add_keys", bpid, bpid, row.keyId, null, -1L, null);
        row.emit();
      }
    } catch (ReflectiveOperationException | RuntimeException failure) {
      gap("dn_add_keys");
    }
  }

  /** Inserted immediately before the selected allKeys.get, after expiry rejection. */
  public static void lookup(Object manager, Object identifier) {
    try {
      String bpid = string(invoke(identifier, "getBlockPoolId"));
      String ownerBpid = string(field(manager, "blockPoolId"));
      int keyId = ((Number) invoke(identifier, "getKeyId")).intValue();
      long expiry = ((Number) invoke(identifier, "getExpiryDate")).longValue();
      Probe.blockKeyObservation("dn_lookup", bpid, ownerBpid, keyId,
          null, null, Probe.captureContext(), tokenId(identifier), expiry, null);
    } catch (ReflectiveOperationException | RuntimeException failure) {
      gap("dn_lookup");
    }
  }

  /** Immediately after the selected Map.get, while retrievePassword holds manager's monitor. */
  public static void lookupResult(Object value, Object manager, Object identifier) {
    try {
      String bpid = string(field(manager, "blockPoolId"));
      int id = ((Number) invoke(identifier, "getKeyId")).intValue();
      KeyStateRow row;
      synchronized (KEY_STATE_LOCK) {
        ManagerState state = managerState(manager);
        KeyValue known = state.keys.get(id);
        boolean matched = known != null && known.value == value;
        row = new KeyStateRow(matched ? "read" : "read_gap", bpid, state.id,
            id, known == null ? -1L : known.version, valueId(value), matched);
      }
      row.emit();
    } catch (ReflectiveOperationException | RuntimeException failure) {
      gap("key_state_read");
    }
  }

  /** Called on the NN's successful identifier/password creation, after key and expiry are set. */
  public static void minted(Object manager, Object identifier) {
    try {
      String bpid = string(invoke(identifier, "getBlockPoolId"));
      String ownerBpid = string(field(manager, "blockPoolId"));
      int keyId = ((Number) invoke(identifier, "getKeyId")).intValue();
      long expiry = ((Number) invoke(identifier, "getExpiryDate")).longValue();
      Probe.blockKeyObservation("nn_token_mint", bpid, ownerBpid, keyId,
          null, null, Probe.captureContext(), tokenId(identifier), expiry, null);
    } catch (ReflectiveOperationException | RuntimeException failure) {
      gap("nn_token_mint");
    }
  }

  /** The UUID joins NN DatanodeDescriptor.peer to a named DN/epoch. */
  public static void dnBound(Object datanode) {
    try (Probe.NodeScope node = Probe.withRegisteredNode(datanode)) {
      try {
        String peer = string(invoke(datanode, "getDatanodeUuid"));
        emit("dn_bind", null, null, -1, peer, -1L, null);
      } catch (ReflectiveOperationException | RuntimeException failure) {
        gap("dn_bind");
      }
    }
  }

  /** At method entry; a matching DOOR_OBSERVED proves the RPC call was reached. */
  public static void heartbeatAttempt(Object actor) {
    try {
      Object bpos = field(actor, "bpos");
      Object dn = field(actor, "dn");
      String bpid = string(invoke(bpos, "getBlockPoolId"));
      String peer = string(invoke(dn, "getDatanodeUuid"));
      Probe.blockKeyObservation("dn_heartbeat_attempt", bpid, bpid, -1, peer,
          "actor@" + System.identityHashCode(actor), Probe.captureContext(),
          null, -1L, null);
    } catch (ReflectiveOperationException | RuntimeException failure) {
      gap("dn_heartbeat_attempt");
    }
  }

  private static void emit(String phase, String bpid, String ownerBpid,
                           int keyId, String peer, long expiry, Boolean pending) {
    Probe.blockKeyObservation(phase, bpid, ownerBpid, keyId, peer, null,
        Probe.captureContext(), null, expiry, pending);
  }

  private static void gap(String phase) {
    emit("identity_gap_" + phase, null, null, -1, null, -1L, null);
  }

  private static ManagerState managerState(Object manager) {
    ManagerState state = MANAGERS.get(manager);
    if (state == null) {
      state = new ManagerState(++nextManagerId);
      MANAGERS.put(manager, state);
    }
    return state;
  }

  private static long valueId(Object value) {
    if (value == null) return 0L;
    Long id = VALUES.get(value);
    if (id == null) {
      id = ++nextValueId;
      VALUES.put(value, id);
    }
    return id.longValue();
  }

  private static final class ManagerState {
    final long id;
    final Map<Integer, KeyValue> keys = new HashMap<Integer, KeyValue>();
    ManagerState(long id) { this.id = id; }
  }

  private static final class KeyValue {
    final Object value;
    final long version;
    KeyValue(Object value, long version) { this.value = value; this.version = version; }
  }

  private static final class KeyStateRow {
    final String phase, bpid;
    final long managerId, version, valueId;
    final int keyId;
    final boolean matched;
    KeyStateRow(String phase, String bpid, long managerId, int keyId,
                long version, long valueId, boolean matched) {
      this.phase = phase;
      this.bpid = bpid;
      this.managerId = managerId;
      this.keyId = keyId;
      this.version = version;
      this.valueId = valueId;
      this.matched = matched;
    }
    void emit() {
      String token = "manager:" + managerId + ":key:" + keyId + ":version:" + version;
      Probe.blockKeyState(phase, bpid, managerId, keyId, version, valueId,
          token, matched);
    }
  }

  private static int keyId(Object key) throws ReflectiveOperationException {
    return ((Number) invoke(key, "getKeyId")).intValue();
  }

  private static String tokenId(Object identifier) throws ReflectiveOperationException {
    try {
      byte[] bytes = (byte[]) invoke(identifier, "getBytes");
      byte[] hash = MessageDigest.getInstance("SHA-256").digest(bytes);
      StringBuilder result = new StringBuilder(hash.length * 2);
      for (byte value : hash) {
        int unsigned = value & 0xff;
        result.append(Character.forDigit(unsigned >>> 4, 16));
        result.append(Character.forDigit(unsigned & 15, 16));
      }
      return result.toString();
    } catch (NoSuchAlgorithmException failure) {
      throw new IllegalStateException("SHA-256 unavailable", failure);
    }
  }

  private static String string(Object value) {
    return value == null ? null : value.toString();
  }

  private static Object field(Object owner, String name) throws ReflectiveOperationException {
    if (owner == null) throw new NoSuchFieldException(name);
    for (Class<?> type = owner.getClass(); type != null; type = type.getSuperclass()) {
      try {
        Field member = type.getDeclaredField(name);
        member.setAccessible(true);
        return member.get(owner);
      } catch (NoSuchFieldException ignored) { }
    }
    throw new NoSuchFieldException(name);
  }

  private static Object invoke(Object owner, String name) throws ReflectiveOperationException {
    if (owner == null) throw new NoSuchMethodException(name);
    for (Class<?> type = owner.getClass(); type != null; type = type.getSuperclass()) {
      try {
        Method method = type.getDeclaredMethod(name);
        method.setAccessible(true);
        return method.invoke(owner);
      } catch (NoSuchMethodException ignored) { }
    }
    throw new NoSuchMethodException(name);
  }

  private static final class Rotation {
    final String bpid;
    final int current;
    final int next;
    Rotation(String bpid, int current, int next) {
      this.bpid = bpid;
      this.current = current;
      this.next = next;
    }
  }
}
