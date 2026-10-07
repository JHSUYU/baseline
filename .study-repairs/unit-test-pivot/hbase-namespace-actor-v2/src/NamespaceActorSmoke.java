/** Loads only the instrumented classes; it does not start a HBase cluster. */
public final class NamespaceActorSmoke {
  public static void main(String[] args) throws Exception {
    ClassLoader loader = NamespaceActorSmoke.class.getClassLoader();
    String[] names = {
      "org.apache.hadoop.hbase.zookeeper.ZKWatcher",
      "org.apache.hadoop.hbase.ZKNamespaceManager",
      "org.apache.hadoop.hbase.zookeeper.ZKUtil",
      "org.apache.hadoop.hbase.master.ClusterSchemaServiceImpl",
      "org.apache.hadoop.hbase.namespace.NamespaceStateManager"
    };
    for (String name : names) {
      Class.forName(name, false, loader);
      System.out.println("NSACTOR SMOKE_LOADED " + name);
    }
  }
}
