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
                           long hit, long doorOrdinal, String resource) {
      return !applied && point != null && site.equals(point.site)
          && (point.node == null || point.node.equals(node))
          && (point.epoch == null || point.epoch.intValue() == epoch)
          && (point.occurrence == null || point.occurrence.equals(occurrence))
          && (point.hit == null || point.hit.longValue() == hit)
          && (point.door_ordinal == null || point.door_ordinal.longValue() == doorOrdinal)
          && (point.resource == null || point.resource.equals(resource));
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
    /** Exact I/O resource required before a fault may consume this plan. */
    public String resource;
  }
}
