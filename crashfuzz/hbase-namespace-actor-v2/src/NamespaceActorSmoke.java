/** Loads only the instrumented classes; it does not start a HBase cluster. */
public final class NamespaceActorSmoke {
  public static void main(String[] args) throws Exception {
    ClassLoader loader = NamespaceActorSmoke.class.getClassLoader();
    String[] names = {
      "org.apache.hadoop.hbase.zookeeper.ZKWatcher",
      "org.apache.hadoop.hbase.ZKNamespaceManager",
      "org.apache.hadoop.hbase.zookeeper.ZKUtil",
      "org.apache.hadoop.hbase.master.TableNamespaceManager",
      "org.apache.hadoop.hbase.master.ClusterSchemaServiceImpl",
      "org.apache.hadoop.hbase.namespace.NamespaceStateManager"
    };
    for (String name : names) {
      Class.forName(name, false, loader);
      System.out.println("NSACTOR SMOKE_LOADED " + name);
    }
    // Exercise transformed ZKUtil entries without a ZooKeeper connection.
    // Their original body must reject the null watcher, while Advice must
    // cross the package boundary without IllegalAccessError.
    try {
      org.apache.hadoop.hbase.zookeeper.ZKUtil.watchAndCheckExists(null, "/smoke");
    } catch (NullPointerException expected) {
      // The original method dereferences its watcher.
    }
    try {
      org.apache.hadoop.hbase.zookeeper.ZKUtil.deleteNode(null, "/smoke");
    } catch (NullPointerException expected) {
      // The original method dereferences its watcher.
    }
    org.apache.hadoop.hbase.master.TableNamespaceManager.getMaxRegions(
        org.apache.hadoop.hbase.NamespaceDescriptor.create("smoke").build());
    System.out.println("NSACTOR SMOKE_ADVICE_CALLS passed");
    // A synthetic null watcher exercises manager rotation without creating a
    // ZooKeeper client or MiniCluster. The same object must retain its ID;
    // a replacement manager on the same watcher must receive a fresh ID.
    java.lang.reflect.Method register = NamespaceActorAgent.class.getDeclaredMethod(
        "manager", Object.class, org.apache.hadoop.hbase.zookeeper.ZKWatcher.class);
    register.setAccessible(true);
    java.lang.reflect.Field ids = NamespaceActorAgent.class.getDeclaredField("MANAGERS");
    ids.setAccessible(true);
    @SuppressWarnings("unchecked")
    java.util.Map<Object, Integer> map = (java.util.Map<Object, Integer>) ids.get(null);
    Object first = new Object();
    register.invoke(null, first, null);
    int original = map.get(null);
    register.invoke(null, first, null);
    if (map.get(null) != original) throw new AssertionError("Same manager changed ID");
    register.invoke(null, new Object(), null);
    if (map.get(null) <= original) throw new AssertionError("Replacement manager reused ID");
    java.lang.reflect.Method actor = NamespaceActorAgent.class.getDeclaredMethod(
        "actor", org.apache.hadoop.hbase.zookeeper.ZKWatcher.class);
    actor.setAccessible(true);
    Object observed = actor.invoke(null, new Object[] { null });
    java.lang.reflect.Field currentId = observed.getClass().getDeclaredField("manager");
    currentId.setAccessible(true);
    if (currentId.getInt(observed) != 0)
      throw new AssertionError("Replaced watcher did not fail closed");
    System.out.println("NSACTOR SMOKE_MANAGER_ROTATION passed");
  }
}
