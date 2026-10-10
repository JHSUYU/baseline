package edu.uva.liftlab.mallory.instrumentation;

/** Resolves the selected alias write to a named, active routed-alias command. */
public final class AliasRoleBindingRegistry {
  public static final String ROLE = "maintain-routed-alias-write";
  public static final String SITE = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#applyModificationAndExportToZk(Ljava/util/function/UnaryOperator;)V@2259:door:1";
  public static final String REGION = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#applyModificationAndExportToZk(Ljava/util/function/UnaryOperator;)V";
  public static final String PARENT_REGION = "org.apache.solr.cloud.api.collections.MaintainRoutedAliasCmd#call(Lorg/apache/solr/common/cloud/ClusterState;Lorg/apache/solr/common/cloud/ZkNodeProps;Lorg/apache/solr/common/util/NamedList;)V";

  private long nextOrdinal;

  public synchronized void reset() { nextOrdinal = 0; }

  public synchronized Resolution atDoor(String site, String node, int epoch,
                                        String region, String occurrence,
                                        String parentOccurrence) {
    if (!SITE.equals(site)) return Resolution.unresolved("wrong_site");
    if (!REGION.equals(region)) return Resolution.unresolved("wrong_region");
    if (node == null || node.isEmpty() || "unknown".equals(node) || epoch < 0)
      return Resolution.unresolved("unnamed_actor");
    if (occurrence == null || !occurrence.startsWith(node + ":" + epoch + ":" + REGION + ":"))
      return Resolution.unresolved("region_actor_mismatch");
    if (parentOccurrence == null ||
        !parentOccurrence.startsWith(node + ":" + epoch + ":" + PARENT_REGION + ":"))
      return Resolution.unresolved("missing_or_mismatched_maintain_command");
    return Resolution.bound(node, epoch, occurrence, parentOccurrence, ++nextOrdinal);
  }

  public static final class Resolution {
    public final boolean bound;
    public final String reason;
    public final String physicalNode;
    public final int physicalEpoch;
    public final String sourceOccurrence;
    public final String parentOccurrence;
    public final long roleOrdinal;

    private Resolution(boolean bound, String reason, String node, int epoch,
                       String occurrence, String parentOccurrence, long ordinal) {
      this.bound = bound;
      this.reason = reason;
      this.physicalNode = node;
      this.physicalEpoch = epoch;
      this.sourceOccurrence = occurrence;
      this.parentOccurrence = parentOccurrence;
      this.roleOrdinal = ordinal;
    }

    private static Resolution unresolved(String reason) {
      return new Resolution(false, reason, null, -1, null, null, 0);
    }

    private static Resolution bound(String node, int epoch, String occurrence,
                                    String parentOccurrence, long ordinal) {
      return new Resolution(true, null, node, epoch, occurrence, parentOccurrence, ordinal);
    }
  }
}
