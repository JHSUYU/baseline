package org.apache.hadoop.hdfs.server.balancer;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.HashSet;
import java.util.Arrays;
import java.util.Set;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import org.apache.hadoop.hdfs.protocol.DatanodeID;
import org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException;
import org.apache.hadoop.hdfs.protocol.datatransfer.sasl.DataEncryptionKeyFactory;
import org.apache.hadoop.hdfs.security.token.block.DataEncryptionKey;

/** Case-local observation of the cached-key check and outbound Balancer I/O. */
public final class Hdfs17899Probe {
  private static final AtomicBoolean KEY_CLEARED = new AtomicBoolean(false);
  private static final AtomicInteger ATTEMPTS = new AtomicInteger();
  private static final AtomicInteger INJECTIONS = new AtomicInteger();
  private static final AtomicInteger CHECKS = new AtomicInteger();
  private static final ThreadLocal<Boolean> LAST_REFRESH = new ThreadLocal<>();
  private static final ThreadLocal<Integer> LAST_MANAGER = new ThreadLocal<>();
  private static final ThreadLocal<Integer> LAST_CACHED_KEY = new ThreadLocal<>();
  private static final Set<Integer> EXACT_PLAN = readExactPlan();
  private static final int RUNTIME_PREFIX_BUDGET =
      Integer.getInteger("hdfs55.runtimePrefixFaults", 0);
  private static final int DN_REJECTION_BUDGET =
      Integer.getInteger("hdfs55.dnRejectCachedKey", 0);
  private static Integer prefixManager;
  private static Integer prefixKeyId;
  private static int prefixApplied;
  private static volatile Integer selectedDnRejectKeyId;
  private static volatile Integer selectedDnRejectManager;
  private static volatile byte[] selectedDnRejectNonce;
  private static int dnRejections;
  private static final ThreadLocal<String> DN_ENDPOINT = new ThreadLocal<>();

  private Hdfs17899Probe() { }

  private static String nonceDigest(byte[] nonce) {
    if (nonce == null) return "none";
    try {
      byte[] hash = MessageDigest.getInstance("SHA-256").digest(nonce);
      StringBuilder out = new StringBuilder();
      for (int i = 0; i < 6; ++i) out.append(String.format("%02x", hash[i] & 0xff));
      return out.toString();
    } catch (NoSuchAlgorithmException e) {
      throw new IllegalStateException(e);
    }
  }

  private static Set<Integer> readExactPlan() {
    String file = System.getProperty("hdfs55.plan");
    if (file == null) return null;
    Set<Integer> ordinals = new HashSet<>();
    try {
      for (String line : Files.readAllLines(Paths.get(file), StandardCharsets.UTF_8)) {
        if (line.trim().isEmpty()) continue;
        String[] fields = line.split("\\t", -1);
        if (fields.length != 3 || !fields[1].equals("balancer-target-dn")
            || !fields[2].equals("cached-reuse")) {
          throw new IllegalArgumentException("invalid exact HDFS-55 plan row: " + line);
        }
        int ordinal = Integer.parseInt(fields[0]);
        if (ordinal < 1 || !ordinals.add(ordinal)) {
          throw new IllegalArgumentException("duplicate or invalid HDFS-55 ordinal " + ordinal);
        }
      }
    } catch (IOException exception) {
      throw new RuntimeException("cannot read HDFS-55 plan " + file, exception);
    }
    return ordinals;
  }

  private static boolean inBalancerMove() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (frame.getClassName().equals(
          "org.apache.hadoop.hdfs.server.balancer.Dispatcher$PendingMove")
          && frame.getMethodName().equals("dispatch")) return true;
    }
    return false;
  }

  public static void observeKeyCheck(KeyManager manager,
      DataEncryptionKey cached, boolean refresh) {
    if (!inBalancerMove()) return;
    int n = CHECKS.incrementAndGet();
    LAST_REFRESH.set(refresh);
    LAST_MANAGER.set(System.identityHashCode(manager));
    LAST_CACHED_KEY.set(cached == null ? null : cached.keyId);
    System.out.println("CASE55 key_guard=" + n
        + " manager=" + System.identityHashCode(manager)
        + " cached_key_id=" + (cached == null ? "none" : cached.keyId)
        + " cached_nonce_digest=" + (cached == null ? "none" : nonceDigest(cached.nonce))
        + " refresh=" + refresh
        + " after_fault=" + (INJECTIONS.get() > 0));
  }

  public static void beforeSocketSend(DataEncryptionKeyFactory factory,
      DatanodeID target) throws IOException {
    if (!inBalancerMove()) return;
    int n = ATTEMPTS.incrementAndGet();
    DataEncryptionKey key = factory.newDataEncryptionKey();
    System.out.println("CASE55 balancer_sasl_attempt=" + n
        + " target=" + target.getXferAddr()
        + " key_id=" + (key == null ? "none" : key.keyId)
        + " nonce_digest=" + (key == null ? "none" : nonceDigest(key.nonce))
        + " cache_cleared=" + KEY_CLEARED.get());
    if (DN_REJECTION_BUDGET > 0) {
      boolean cachedReuse = key != null && Boolean.FALSE.equals(LAST_REFRESH.get())
          && LAST_MANAGER.get() != null
          && LAST_MANAGER.get() == System.identityHashCode(factory)
          && LAST_CACHED_KEY.get() != null
          && LAST_CACHED_KEY.get() == key.keyId;
      if (cachedReuse) {
        synchronized (Hdfs17899Probe.class) {
          if (selectedDnRejectKeyId == null) {
            selectedDnRejectKeyId = key.keyId;
            selectedDnRejectManager = System.identityHashCode(factory);
            selectedDnRejectNonce = key.nonce.clone();
            System.out.println("CASE55 dn_wire_selected_manager=" + selectedDnRejectManager
                + " key_id=" + selectedDnRejectKeyId
                + " nonce_digest=" + nonceDigest(selectedDnRejectNonce)
                + " first_target=" + target.getXferAddr()
                + " first_attempt=" + n);
          }
          if (selectedDnRejectManager == System.identityHashCode(factory)
              && selectedDnRejectKeyId == key.keyId) {
            System.out.println("CASE55 dn_wire_balancer_attempt=" + n
                + " manager=" + selectedDnRejectManager
                + " key_id=" + selectedDnRejectKeyId
                + " target=" + target.getXferAddr());
          }
        }
      }
      return;
    }
    if (RUNTIME_PREFIX_BUDGET > 0) {
      boolean cachedReuse = key != null && Boolean.FALSE.equals(LAST_REFRESH.get())
          && LAST_MANAGER.get() != null
          && LAST_MANAGER.get() == System.identityHashCode(factory)
          && LAST_CACHED_KEY.get() != null
          && LAST_CACHED_KEY.get() == key.keyId;
      if (!cachedReuse || KEY_CLEARED.get()) return;
      synchronized (Hdfs17899Probe.class) {
        if (prefixManager == null) {
          prefixManager = System.identityHashCode(factory);
          prefixKeyId = key.keyId;
          System.out.println("CASE55 runtime_prefix_selected_manager=" + prefixManager
              + " key_id=" + prefixKeyId + " first_attempt=" + n);
        }
        if (prefixManager != System.identityHashCode(factory)
            || prefixKeyId != key.keyId || prefixApplied >= RUNTIME_PREFIX_BUDGET) return;
        ++prefixApplied;
        INJECTIONS.incrementAndGet();
        System.out.println("CASE55 runtime_prefix_fault=" + prefixApplied
            + " attempt=" + n + " role=balancer-target-dn"
            + " manager=" + prefixManager + " target=" + target.getXferAddr()
            + " key_id=" + prefixKeyId + " refresh=false");
        throw new InvalidEncryptionKeyException(
            "case HDFS-55 runtime-prefix cached-key rejection");
      }
    }
    if (EXACT_PLAN != null) {
      if (!EXACT_PLAN.contains(n)) return;
      boolean identityMatched = key != null
          && Boolean.FALSE.equals(LAST_REFRESH.get())
          && LAST_MANAGER.get() != null
          && LAST_MANAGER.get() == System.identityHashCode(factory)
          && LAST_CACHED_KEY.get() != null
          && LAST_CACHED_KEY.get() == key.keyId;
      if (!identityMatched) {
        System.out.println("CASE55 fault_plan_nonmatch=" + n
            + " target=" + target.getXferAddr()
            + " key_id=" + (key == null ? "none" : key.keyId)
            + " guard_refresh=" + LAST_REFRESH.get()
            + " guard_manager=" + LAST_MANAGER.get()
            + " factory_manager=" + System.identityHashCode(factory)
            + " guard_cached_key=" + LAST_CACHED_KEY.get()
            + " reason=cached_key_or_manager_identity");
        return;
      }
      System.out.println("CASE55 fault_matched=" + n
          + " role=balancer-target-dn"
          + " manager=" + System.identityHashCode(factory)
          + " target=" + target.getXferAddr()
          + " key_id=" + key.keyId + " refresh=false");
      INJECTIONS.incrementAndGet();
      System.out.println("CASE55 injected_invalid_key_at_balancer_sasl=" + n);
      throw new InvalidEncryptionKeyException(
          "case HDFS-55 exact-plan stale Balancer data encryption key");
    }
    int first = Integer.getInteger("hdfs55.firstAttempt", 1);
    int budget = Integer.getInteger("hdfs55.maxFaults", 24);
    if (Boolean.getBoolean("hdfs17899.inject") && !KEY_CLEARED.get()
        && n >= first && INJECTIONS.get() < budget) {
      INJECTIONS.incrementAndGet();
      System.out.println("CASE55 injected_invalid_key_at_balancer_sasl=" + n);
      throw new InvalidEncryptionKeyException(
          "case HDFS-55 stale Balancer data encryption key");
    }
  }

  public static void markKeyCleared() {
    KEY_CLEARED.set(true);
    System.out.println("CASE55 balancer_key_cache_cleared=true");
  }

  /** Called on a DataXceiver's server-side SASL handshake thread. */
  public static void enterDnPeer(String localAddress) {
    if (DN_REJECTION_BUDGET > 0) DN_ENDPOINT.set(localAddress);
  }

  /** Models a DN rejecting the Balancer's exact cached DEK identity. */
  public static void maybeRejectDnKey(int keyId, String blockPoolId, byte[] nonce)
      throws InvalidEncryptionKeyException {
    if (DN_REJECTION_BUDGET <= 0 || selectedDnRejectKeyId == null
        || selectedDnRejectKeyId != keyId || selectedDnRejectNonce == null
        || !Arrays.equals(selectedDnRejectNonce, nonce)) return;
    synchronized (Hdfs17899Probe.class) {
      if (dnRejections >= DN_REJECTION_BUDGET) return;
      ++dnRejections;
      INJECTIONS.incrementAndGet();
      System.out.println("CASE55 dn_wire_reject=" + dnRejections
          + " role=target-datanode"
          + " manager=" + selectedDnRejectManager
          + " server_endpoint=" + DN_ENDPOINT.get()
          + " key_id=" + keyId
          + " nonce_digest=" + nonceDigest(nonce)
          + " block_pool=" + blockPoolId);
      throw new InvalidEncryptionKeyException(
          "case HDFS-55 DataNode rejected stale Balancer key " + keyId);
    }
  }

  public static void markDnInvalidKeyResponse(String message) {
    if (DN_REJECTION_BUDGET > 0) {
      System.out.println("CASE55 dn_wire_error_response=INVALID_KEY"
          + " server_endpoint=" + DN_ENDPOINT.get()
          + " message=" + message);
    }
  }
}
