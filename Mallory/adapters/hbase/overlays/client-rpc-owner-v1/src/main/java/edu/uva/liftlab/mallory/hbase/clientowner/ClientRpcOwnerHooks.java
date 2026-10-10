package edu.uva.liftlab.mallory.hbase.clientowner;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.lang.reflect.Field;
import java.util.Collections;
import java.util.Map;
import java.util.WeakHashMap;

/**
 * The only admitted client owner is the connection returned by HBaseTestingUtility.
 * A private RpcClient field carries that exact connection's I/O ownership across threads.
 */
public final class ClientRpcOwnerHooks {
  private static final Map<Object, Boolean> TEST_RPC_CLIENTS =
      Collections.synchronizedMap(new WeakHashMap<Object, Boolean>());

  private ClientRpcOwnerHooks() { }

  public static void registerTestConnection(Object connection) {
    if (connection == null ||
        !"org.apache.hadoop.hbase.client.ConnectionImplementation".equals(
            connection.getClass().getName())) return;
    try {
      Field ownerField = connection.getClass().getDeclaredField("rpcClient");
      ownerField.setAccessible(true);
      Object rpcClient = ownerField.get(connection);
      if (rpcClient == null ||
          !isAbstractRpcClient(rpcClient.getClass())) return;
      synchronized (TEST_RPC_CLIENTS) {
        if (TEST_RPC_CLIENTS.containsKey(rpcClient)) return;
        // Probe rejects a conflicting identity. Do not put the receiver in the
        // local set until its explicit test-client registration has succeeded.
        Probe.registerNode(rpcClient, "client", 0);
        TEST_RPC_CLIENTS.put(rpcClient, Boolean.TRUE);
      }
    } catch (ReflectiveOperationException | RuntimeException failure) {
      System.err.println("Mallory HBase test RpcClient owner gap: " + failure);
    }
  }

  private static boolean isAbstractRpcClient(Class<?> type) {
    for (Class<?> current = type; current != null; current = current.getSuperclass()) {
      if ("org.apache.hadoop.hbase.ipc.AbstractRpcClient".equals(current.getName()))
        return true;
    }
    return false;
  }

  /** Unregistered internal clients keep the prior actor and gain no invented client identity. */
  public static Probe.NodeScope enterKnownRpcClient(Object rpcClient) {
    synchronized (TEST_RPC_CLIENTS) {
      if (!TEST_RPC_CLIENTS.containsKey(rpcClient)) return null;
    }
    return Probe.withRegisteredNode(rpcClient);
  }

  public static void closeScope(Probe.NodeScope scope) {
    if (scope != null) scope.close();
  }
}
