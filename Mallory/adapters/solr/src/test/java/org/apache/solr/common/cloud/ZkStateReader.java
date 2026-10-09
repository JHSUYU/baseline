package org.apache.solr.common.cloud;

import edu.uva.liftlab.mallory.instrumentation.Probe;

/** Alias watcher shape used to verify the Solr transformer without Solr on the test classpath. */
public final class ZkStateReader {
  public final AliasesManager aliasesManager = new AliasesManager();
  public String watcherNode;

  public void createClusterStateWatchersAndUpdate() {
    try (Probe.NodeScope scope = Probe.withRegisteredNode(aliasesManager)) {
      watcherNode = aliasesManager.setIfNewer("initial");
    }
  }

  public final class AliasesManager {
    public String update() { return setIfNewer("updated"); }
    public String applyModificationAndExportToZk() { return setIfNewer("modified"); }
    public String process(Object event) { return setIfNewer(event); }
    public String setIfNewer(Object aliases) {
      if (aliases == null) failIndirectly();
      return Probe.currentNode();
    }
    private void failIndirectly() { throw new IllegalStateException("implicit"); }
  }
}
