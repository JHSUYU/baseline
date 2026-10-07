package org.apache.hadoop.hdfs.server.balancer;

import java.io.IOException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import org.apache.hadoop.hdfs.protocol.DatanodeID;
import org.apache.hadoop.hdfs.protocol.datatransfer.InvalidEncryptionKeyException;
import org.apache.hadoop.hdfs.protocol.datatransfer.sasl.DataEncryptionKeyFactory;
import org.apache.hadoop.hdfs.security.token.block.DataEncryptionKey;

/** Stateful I/O-boundary fault modeling a stale Balancer cached DEK. */
public final class Hdfs17899Probe {
  private static final AtomicBoolean KEY_CLEARED = new AtomicBoolean(false);
  private static final AtomicInteger ATTEMPTS = new AtomicInteger();

  private Hdfs17899Probe() { }

  private static boolean inBalancerMove() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (frame.getClassName().equals(
          "org.apache.hadoop.hdfs.server.balancer.Dispatcher$PendingMove")
          && frame.getMethodName().equals("dispatch")) return true;
    }
    return false;
  }

  public static void beforeSocketSend(DataEncryptionKeyFactory factory,
      DatanodeID target) throws IOException {
    if (!inBalancerMove()) return;
    int n = ATTEMPTS.incrementAndGet();
    DataEncryptionKey key = factory.newDataEncryptionKey();
    System.out.println("CONTROL balancer_sasl_attempt=" + n
        + " target=" + target.getXferAddr()
        + " key_id=" + (key == null ? "none" : key.keyId)
        + " cache_cleared=" + KEY_CLEARED.get());
    if (Boolean.getBoolean("hdfs17899.inject") && !KEY_CLEARED.get()) {
      System.out.println("CONTROL injected_invalid_key_at_balancer_sasl=" + n);
      throw new InvalidEncryptionKeyException(
          "control stale Balancer data encryption key");
    }
  }

  public static void markKeyCleared() {
    KEY_CLEARED.set(true);
    System.out.println("CONTROL balancer_key_cache_cleared=true");
  }
}
