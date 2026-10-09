import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.Map;

/**
 * Dependency-free prototype for a role-bound I/O door. A caller must report
 * Solr's actual amILeader() decision, not infer leadership from a node name.
 */
public final class RoleBindingRegistry {
  public static final String ROLE = "overseer-leader";
  public static final String SITE =
      "org.apache.solr.cloud.OverseerTaskProcessor#run()V@246:door:1";

  private final IdentityHashMap<Object, Actor> leaders = new IdentityHashMap<Object, Actor>();
  private final Map<String, Long> roleOrdinals = new HashMap<String, Long>();

  public synchronized void reset() {
    leaders.clear();
    roleOrdinals.clear();
  }

  public synchronized void decision(Object processor, String status, String node,
                                    int epoch, String leaderId) {
    if (processor == null) return;
    // DONT_KNOW must revoke a previous YES. Stale leadership is never assumed.
    if (!"YES".equals(status) || !named(node) || epoch < 0 || !named(leaderId)) {
      leaders.remove(processor);
      return;
    }
    leaders.put(processor, new Actor(node, epoch, leaderId));
  }

  public synchronized void exit(Object processor) {
    leaders.remove(processor);
  }

  /**
   * Resolve at the exact callsite. The current processor must itself have a
   * positive leader decision, and all positive decisions must point to the
   * same physical node and epoch. An unresolved call has no role ordinal.
   */
  public synchronized Resolution atDoor(Object processor, String node, int epoch,
                                         String site) {
    if (!SITE.equals(site) || processor == null) return Resolution.unresolved("wrong_site_or_source");
    Actor current = leaders.get(processor);
    if (current == null) return Resolution.unresolved("source_not_observed_leader");
    if (!current.node.equals(node) || current.epoch != epoch)
      return Resolution.unresolved("current_physical_identity_mismatch");
    for (Actor candidate : leaders.values()) {
      if (!candidate.node.equals(current.node) || candidate.epoch != current.epoch)
        return Resolution.unresolved("ambiguous_physical_leader");
      if (!candidate.leaderId.equals(current.leaderId))
        return Resolution.unresolved("ambiguous_leader_id");
    }
    long ordinal = roleOrdinals.containsKey(site) ? roleOrdinals.get(site) + 1 : 1;
    roleOrdinals.put(site, ordinal);
    return Resolution.bound(current.node, current.epoch, current.leaderId, ordinal);
  }

  /** A plan carries a role ordinal, never a wildcard physical node. */
  public static boolean matches(Resolution resolution, String planRole,
                                String planSite, long planRoleOrdinal) {
    return resolution.bound && ROLE.equals(planRole) && SITE.equals(planSite)
        && planRoleOrdinal > 0 && planRoleOrdinal == resolution.roleOrdinal;
  }

  private static boolean named(String value) {
    return value != null && !value.isEmpty() && !"unknown".equals(value);
  }

  private static final class Actor {
    final String node;
    final int epoch;
    final String leaderId;

    Actor(String node, int epoch, String leaderId) {
      this.node = node;
      this.epoch = epoch;
      this.leaderId = leaderId;
    }
  }

  public static final class Resolution {
    public final boolean bound;
    public final String reason;
    public final String physicalNode;
    public final int physicalEpoch;
    public final String leaderId;
    public final long roleOrdinal;

    private Resolution(boolean bound, String reason, String physicalNode,
                       int physicalEpoch, String leaderId, long roleOrdinal) {
      this.bound = bound;
      this.reason = reason;
      this.physicalNode = physicalNode;
      this.physicalEpoch = physicalEpoch;
      this.leaderId = leaderId;
      this.roleOrdinal = roleOrdinal;
    }

    static Resolution unresolved(String reason) {
      return new Resolution(false, reason, null, -1, null, 0);
    }

    static Resolution bound(String node, int epoch, String leaderId, long roleOrdinal) {
      return new Resolution(true, null, node, epoch, leaderId, roleOrdinal);
    }
  }
}
