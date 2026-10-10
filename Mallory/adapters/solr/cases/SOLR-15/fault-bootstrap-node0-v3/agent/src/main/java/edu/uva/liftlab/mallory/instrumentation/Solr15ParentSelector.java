package edu.uva.liftlab.mallory.instrumentation;

/** Binds the two source-level parent lookups to their native ZooKeeper paths on one execution. */
final class Solr15ParentSelector {
  static final String SPLIT = "org.apache.solr.cloud.api.collections.SplitShardCmd#split"
      + "(Lorg/apache/solr/common/cloud/ClusterState;"
      + "Lorg/apache/solr/common/cloud/ZkNodeProps;"
      + "Lorg/apache/solr/common/util/NamedList;)Z";
  static final String FIRST = SPLIT + "@164:door:2";
  static final String SECOND = SPLIT + "@523:door:3";
  static final String NATIVE = "org.apache.solr.common.cloud.SolrZkClient#lambda$exists$2"
      + "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;)"
      + "Lorg/apache/zookeeper/data/Stat;@301:door:1";

  private String node;
  private int epoch;
  private String occurrence;
  private String path;
  private boolean firstPending;
  private boolean secondPending;
  private boolean secondApplied;
  private boolean retryApplied;

  private boolean same(String candidateNode, int candidateEpoch, String candidateOccurrence) {
    return node != null && node.equals(candidateNode) && epoch == candidateEpoch
        && occurrence != null && occurrence.equals(candidateOccurrence);
  }

  static boolean liveNodePath(String candidate) {
    return candidate != null && candidate.startsWith("/live_nodes/")
        && candidate.length() > "/live_nodes/".length()
        && candidate.indexOf('/', "/live_nodes/".length()) < 0;
  }

  /** Returns the qualified phase, or null. A different native path cannot consume a fault. */
  String observe(String site, String candidateNode, int candidateEpoch,
                 String candidateOccurrence, String resource) {
    if (FIRST.equals(site)) {
      node = candidateNode;
      epoch = candidateEpoch;
      occurrence = candidateOccurrence;
      path = null;
      firstPending = true;
      secondPending = false;
      secondApplied = false;
      retryApplied = false;
      return null;
    }
    if (SECOND.equals(site)) {
      secondPending = same(candidateNode, candidateEpoch, candidateOccurrence)
          && path != null;
      firstPending = false;
      return null;
    }
    if (!NATIVE.equals(site)) return null;
    if (!same(candidateNode, candidateEpoch, candidateOccurrence)) {
      firstPending = false;
      secondPending = false;
      return null;
    }
    if (firstPending) {
      firstPending = false;
      if (liveNodePath(resource)) path = resource;
      return null;
    }
    if (secondPending) {
      secondPending = false;
      return path.equals(resource) ? "second" : null;
    }
    if (retryApplied) return "after_pair";
    return secondApplied && path.equals(resource) ? "retry" : null;
  }

  void markApplied(String phase) {
    if ("second".equals(phase)) secondApplied = true;
    if ("retry".equals(phase)) retryApplied = true;
  }

  String boundPath() { return path; }
}
