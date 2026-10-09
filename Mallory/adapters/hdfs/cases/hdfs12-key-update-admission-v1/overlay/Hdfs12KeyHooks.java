package edu.uva.liftlab.mallory.adapters.hdfs;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.List;

/** HDFS-12 metadata observations. This class never reads BlockKey.getKey(). */
public final class Hdfs12KeyHooks {
  private static final ThreadLocal<Rotation> ROTATION = new ThreadLocal<Rotation>();

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
      for (Object key : (Object[]) invoke(exported, "getAllKeys")) {
        if (key != null)
          emit("dn_add_keys", bpid, bpid, keyId(key), null, -1L, null);
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
    Method method = owner.getClass().getMethod(name);
    return method.invoke(owner);
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
