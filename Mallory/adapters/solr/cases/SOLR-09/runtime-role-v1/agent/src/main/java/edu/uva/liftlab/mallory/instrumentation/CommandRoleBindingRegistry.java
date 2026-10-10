package edu.uva.liftlab.mallory.instrumentation;

/** Resolves the selected wait call to a named, active deleteCore command. */
public final class CommandRoleBindingRegistry {
  public static final String ROLE = "delete-replica-deletecore";
  public static final String SITE = "org.apache.solr.cloud.api.collections.OverseerCollectionMessageHandler#waitForCoreNodeGone(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;I)Z@434:door:1";
  public static final String REGION = "org.apache.solr.cloud.api.collections.DeleteReplicaCmd#deleteCore(Lorg/apache/solr/common/cloud/Slice;Ljava/lang/String;Ljava/lang/String;Lorg/apache/solr/common/cloud/ZkNodeProps;Ljava/lang/String;Lorg/apache/solr/common/util/NamedList;Ljava/lang/Runnable;Z)V";

  private long nextOrdinal;

  public synchronized void reset() { nextOrdinal = 0; }

  public synchronized Resolution atDoor(String site, String node, int epoch,
                                        String region, String occurrence) {
    if (!SITE.equals(site)) return Resolution.unresolved("wrong_site");
    if (!REGION.equals(region)) return Resolution.unresolved("wrong_region");
    if (node == null || node.isEmpty() || "unknown".equals(node) || epoch < 0)
      return Resolution.unresolved("unnamed_actor");
    if (occurrence == null || !occurrence.startsWith(node + ":" + epoch + ":" + REGION + ":"))
      return Resolution.unresolved("region_actor_mismatch");
    return Resolution.bound(node, epoch, occurrence, ++nextOrdinal);
  }

  public static final class Resolution {
    public final boolean bound;
    public final String reason;
    public final String physicalNode;
    public final int physicalEpoch;
    public final String sourceOccurrence;
    public final long roleOrdinal;

    private Resolution(boolean bound, String reason, String node, int epoch,
                       String occurrence, long ordinal) {
      this.bound = bound;
      this.reason = reason;
      this.physicalNode = node;
      this.physicalEpoch = epoch;
      this.sourceOccurrence = occurrence;
      this.roleOrdinal = ordinal;
    }

    private static Resolution unresolved(String reason) {
      return new Resolution(false, reason, null, -1, null, 0);
    }

    private static Resolution bound(String node, int epoch, String occurrence, long ordinal) {
      return new Resolution(true, null, node, epoch, occurrence, ordinal);
    }
  }
}
