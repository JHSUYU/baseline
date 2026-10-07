import java.io.File;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.tools.ExecFileLoader;

/** Aggregate JaCoCo production coverage for the independent upstream stage. */
public final class UpstreamCoverageReport {
  private static final Set<String> CLASSES = new HashSet<>(Arrays.asList(
    "org/apache/hadoop/hbase/regionserver/handler/RegionReplicaFlushHandler",
    "org/apache/hadoop/hbase/client/FlushRegionCallable",
    "org/apache/hadoop/hbase/MetaTableAccessor",
    "org/apache/hadoop/hbase/client/ConnectionImplementation",
    "org/apache/hadoop/hbase/client/ScannerCallable",
    "org/apache/hadoop/hbase/client/ClientServiceCallable",
    "org/apache/hadoop/hbase/regionserver/HRegionServer",
    "org/apache/hadoop/hbase/regionserver/RSRpcServices",
    "org/apache/hadoop/hbase/regionserver/wal/WALUtil"));

  public static void main(String[] args) throws Exception {
    ExecFileLoader data = new ExecFileLoader();
    for (String path : args[0].split(",")) data.load(new File(path));
    CoverageBuilder builder = new CoverageBuilder();
    for (int i = 1; i < args.length; i++) {
      new Analyzer(data.getExecutionDataStore(), builder).analyzeAll(new File(args[i]));
    }
    for (IClassCoverage c : builder.getClasses()) {
      if (!CLASSES.contains(c.getName())) continue;
      System.out.println("COVERAGE class=" + c.getName() + " methods="
        + c.getMethodCounter().getCoveredCount() + " branches="
        + c.getBranchCounter().getCoveredCount() + " lines="
        + c.getLineCounter().getCoveredCount());
      if (c.getName().endsWith("RegionReplicaFlushHandler")) {
        System.out.println("TARGET line=136 instructions="
          + c.getLine(136).getInstructionCounter().getCoveredCount()
          + " branches=" + c.getLine(136).getBranchCounter().getCoveredCount());
      }
    }
  }
}
