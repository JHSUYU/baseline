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
      for (Fault fault : plan.faults) {
        if (fault.point == null || fault.point.site == null || fault.point.site.isEmpty()) {
          throw new IOException("Every fault requires point.site");
        }
        String phase = fault.point.solr15_parent_lookup;
        if (phase != null && (!Solr15ParentSelector.NATIVE.equals(fault.point.site)
            || fault.point.node == null || fault.point.epoch == null
            || fault.point.hit != null || fault.point.door_ordinal != null
            || !("second".equals(phase) || "retry".equals(phase)))) {
          throw new IOException("SOLR-15 selector requires native site, actor, epoch and phase");
        }
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

    public boolean matches(String site, String node, int epoch, String occurrence,
                           long hit, long doorOrdinal, String qualifiedPhase) {
      return !applied && point != null && site.equals(point.site)
          && (point.node == null || point.node.equals(node))
          && (point.epoch == null || point.epoch.intValue() == epoch)
          && (point.occurrence == null || point.occurrence.equals(occurrence))
          && (point.hit == null || point.hit.longValue() == hit)
          && (point.door_ordinal == null || point.door_ordinal.longValue() == doorOrdinal)
          && (point.solr15_parent_lookup == null
              || point.solr15_parent_lookup.equals(qualifiedPhase));
    }

    public void markApplied() { applied = true; }
  }

  public static final class Point {
    public String site;
    public String node;
    public Integer epoch;
    public String occurrence;
    public Long hit;
    /** Replay identity independent of transport-generated causal tokens. */
    public Long door_ordinal;
    /** Dynamically binds @164 and @523 to a same-execution native /live_nodes path. */
    public String solr15_parent_lookup;
  }
}
