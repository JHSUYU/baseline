package edu.uva.liftlab.mallory.instrumentation;

import com.google.gson.Gson;
import java.io.File;
import java.io.FileReader;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

/** Exact, one-shot fault decisions for a single trial. Missing fields are wildcards. */
public final class FaultPlan {
  public int schema_version = 1;
  public List<Fault> faults = new ArrayList<Fault>();

  public static FaultPlan load(File file) throws IOException {
    if (file == null) return new FaultPlan();
    FileReader reader = new FileReader(file);
    try {
      FaultPlan plan = new Gson().fromJson(reader, FaultPlan.class);
      if (plan == null || plan.schema_version != 1) throw new IOException("Unsupported fault plan schema");
      if (plan.faults == null) plan.faults = new ArrayList<Fault>();
      for (int index = 0; index < plan.faults.size(); index++) {
        Fault fault = plan.faults.get(index);
        if (fault.point == null || fault.point.site == null || fault.point.site.isEmpty()) {
          throw new IOException("Every fault requires point.site");
        }
        if (fault.point.after_fault != null &&
            (fault.point.after_fault.intValue() < 0 || fault.point.after_fault.intValue() >= index))
          throw new IOException("point.after_fault must refer to an earlier fault");
        if (fault.point.same_node_as != null &&
            (fault.point.same_node_as.intValue() < 0 || fault.point.same_node_as.intValue() >= index))
          throw new IOException("point.same_node_as must refer to an earlier fault");
        if (fault.point.relative_hit != null &&
            (fault.point.after_fault == null || fault.point.relative_hit.longValue() <= 0))
          throw new IOException("point.relative_hit requires after_fault and must be positive");
      }
      return plan;
    } finally { reader.close(); }
  }

  public static final class Fault {
    public String fault_id;
    public Point point;
    public String fault_type;
    public String exception_class;
    private transient boolean applied;
    private transient String appliedNode;
    private transient int appliedEpoch;
    private transient long eligibleHits;

    public boolean matches(String site, String node, int epoch, String occurrence,
                           long hit, long doorOrdinal) {
      return !applied && point != null && site.equals(point.site)
          && (point.node == null || point.node.equals(node))
          && (point.epoch == null || point.epoch.intValue() == epoch)
          && (point.occurrence == null || point.occurrence.equals(occurrence))
          && (point.hit == null || point.hit.longValue() == hit)
          && (point.door_ordinal == null || point.door_ordinal.longValue() == doorOrdinal);
    }

    public void markApplied() { applied = true; }

    public void markApplied(String node, int epoch) {
      applied = true;
      appliedNode = node;
      appliedEpoch = epoch;
    }
  }

  /** Optional role-relative selectors for a directed multi-fault replay. */
  public boolean matches(int index, String site, String node, int epoch,
                         String occurrence, long hit, long doorOrdinal) {
    Fault fault = faults.get(index);
    Point point = fault.point;
    if (point.after_fault != null && !faults.get(point.after_fault.intValue()).applied) return false;
    if (point.same_node_as != null) {
      Fault earlier = faults.get(point.same_node_as.intValue());
      if (!earlier.applied || !node.equals(earlier.appliedNode) || epoch != earlier.appliedEpoch)
        return false;
    }
    if (!fault.matches(site, node, epoch, occurrence, hit, doorOrdinal)) return false;
    if (point.relative_hit != null) {
      fault.eligibleHits++;
      return fault.eligibleHits == point.relative_hit.longValue();
    }
    return true;
  }

  public static final class Point {
    public String site;
    public String node;
    public Integer epoch;
    public String occurrence;
    public Long hit;
    /** Replay identity independent of transport-generated causal tokens. */
    public Long door_ordinal;
    /** Gate this fault until the referenced earlier fault has applied. */
    public Integer after_fault;
    /** Require the same concrete node and epoch as the referenced fault. */
    public Integer same_node_as;
    /** Count matching doors after after_fault instead of using an absolute ordinal. */
    public Long relative_hit;
  }
}
