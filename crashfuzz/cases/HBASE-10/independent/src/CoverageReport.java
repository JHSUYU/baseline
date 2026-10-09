import java.io.File;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.data.ExecutionData;
import org.jacoco.core.tools.ExecFileLoader;

/** Production probe and method/branch coverage for HBASE-10. */
public class CoverageReport {
  private static final Set<String> CLASSES = new HashSet<String>(Arrays.asList(
    "org/apache/hadoop/hbase/master/assignment/AssignmentManager",
    "org/apache/hadoop/hbase/master/assignment/RegionStateNode",
    "org/apache/hadoop/hbase/master/assignment/TransitRegionStateProcedure",
    "org/apache/hadoop/hbase/master/MasterRpcServices",
    "org/apache/hadoop/hbase/client/HBaseAdmin",
    "org/apache/hadoop/hbase/client/RpcRetryingCallerImpl",
    "org/apache/hadoop/hbase/client/MasterCallable",
    "org/apache/hadoop/hbase/ipc/AbstractRpcClient"));

  public static void main(String[] args) throws Exception {
    ExecFileLoader data = new ExecFileLoader();
    data.load(new File(args[0]));
    for (ExecutionData execution : data.getExecutionDataStore().getContents()) {
      String name = execution.getName();
      if (!CLASSES.contains(name)) continue;
      boolean[] probes = execution.getProbes();
      for (int index = 0; index < probes.length; index++)
        if (probes[index])
          System.out.println("PROBE class=" + name + " index=" + index);
    }
    CoverageBuilder builder = new CoverageBuilder();
    Analyzer analyzer = new Analyzer(data.getExecutionDataStore(), builder);
    for (int i = 1; i < args.length; i++) analyzer.analyzeAll(new File(args[i]));
    for (IClassCoverage c : builder.getClasses()) {
      if (!CLASSES.contains(c.getName())) continue;
      System.out.println("COVERAGE class=" + c.getName()
        + " methods=" + c.getMethodCounter().getCoveredCount()
        + " branches=" + c.getBranchCounter().getCoveredCount()
        + " lines=" + c.getLineCounter().getCoveredCount());
    }
  }
}
