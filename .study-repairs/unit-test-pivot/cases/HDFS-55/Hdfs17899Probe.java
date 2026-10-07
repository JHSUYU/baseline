package org.apache.hadoop.hdfs.server.balancer;

import java.io.IOException;
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

  private Hdfs17899Probe() { }

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
    System.out.println("CASE55 key_guard=" + n
        + " manager=" + System.identityHashCode(manager)
        + " cached_key_id=" + (cached == null ? "none" : cached.keyId)
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
        + " cache_cleared=" + KEY_CLEARED.get());
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
}
