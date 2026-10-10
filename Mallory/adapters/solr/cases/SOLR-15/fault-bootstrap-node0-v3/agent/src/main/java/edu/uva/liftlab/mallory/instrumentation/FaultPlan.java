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
        if (Solr15ParentSelector.NATIVE.equals(fault.point.site) && phase == null) {
          throw new IOException("Native ZooKeeper fault requires pre-injection path selector");
        }
        if ("explicit_resource".equals(phase)) {
          if (!Solr15ParentSelector.NATIVE.equals(fault.point.site)
              || fault.point.node == null || fault.point.epoch == null
              || fault.point.occurrence == null || fault.point.occurrence.isEmpty()
              || fault.point.door_ordinal == null || fault.point.door_ordinal.longValue() <= 0
              || fault.point.resource == null || fault.point.resource.isEmpty()
              || fault.point.resource_role != null) {
            throw new IOException("Explicit native resource requires actor, occurrence, ordinal and path");
          }
        } else if (phase != null && (!Solr15ParentSelector.NATIVE.equals(fault.point.site)
            || fault.point.node == null || fault.point.epoch == null
            || fault.point.hit != null || fault.point.door_ordinal != null
            || !("second".equals(phase) || "retry".equals(phase)
                 || "after_pair".equals(phase)))) {
          throw new IOException("SOLR-15 selector requires native site, actor, epoch and phase");
        }
        if ("after_pair".equals(phase)
            && ((fault.point.resource == null) == (fault.point.resource_role == null)
                || (fault.point.resource != null && fault.point.resource.isEmpty())
                || (fault.point.resource_role != null
                    && !"bound_parent".equals(fault.point.resource_role)))) {
          throw new IOException("After-pair native fault requires one explicit resource selector");
        }
        if (phase == null && (fault.point.resource != null || fault.point.resource_role != null)) {
          throw new IOException("Resource-qualified fault requires runtime selector");
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
                           long hit, long doorOrdinal, String qualifiedPhase,
                           String resource, String boundResource) {
      return !applied && point != null && site.equals(point.site)
          && (point.node == null || point.node.equals(node))
          && (point.epoch == null || point.epoch.intValue() == epoch)
          && (point.occurrence == null || point.occurrence.equals(occurrence))
          && (point.hit == null || point.hit.longValue() == hit)
          && (point.door_ordinal == null || point.door_ordinal.longValue() == doorOrdinal)
          && (point.solr15_parent_lookup == null
              || "explicit_resource".equals(point.solr15_parent_lookup)
              || point.solr15_parent_lookup.equals(qualifiedPhase))
          && (point.resource == null || point.resource.equals(resource))
          && (point.resource_role == null || ("bound_parent".equals(point.resource_role)
              && boundResource != null && boundResource.equals(resource)));
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
    /** Stable literal ZooKeeper path, checked at injection time. */
    public String resource;
    /** Dynamic parent path bound by the first split lookup in this execution. */
    public String resource_role;
  }
}
