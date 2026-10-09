import java.io.File;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.tools.ExecFileLoader;

/** Reports only the production classes selected before the HBASE-17 campaign. */
public final class CoverageReport17 {
  private static final Set<String> CLASSES = new HashSet<>(Arrays.asList(
    "org/apache/hadoop/hbase/master/assignment/TransitRegionStateProcedure",
    "org/apache/hadoop/hbase/master/assignment/RegionStateNode",
    "org/apache/hadoop/hbase/master/assignment/AssignmentManager",
    "org/apache/hadoop/hbase/master/assignment/RegionStateStore",
    "org/apache/hadoop/hbase/master/assignment/RegionRemoteProcedureBase",
    "org/apache/hadoop/hbase/master/procedure/RSProcedureDispatcher",
    "org/apache/hadoop/hbase/master/procedure/ServerCrashProcedure",
    "org/apache/hadoop/hbase/master/region/MasterRegion",
    "org/apache/hadoop/hbase/regionserver/HRegionServer",
    "org/apache/hadoop/hbase/regionserver/RSRpcServices",
    "org/apache/hadoop/hbase/client/HBaseAdmin",
    "org/apache/hadoop/hbase/client/HTable",
    "org/apache/hadoop/hbase/ipc/AbstractRpcClient",
    "org/apache/hadoop/hbase/procedure2/ProcedureExecutor"));

  public static void main(String[] args) throws Exception {
    ExecFileLoader data = new ExecFileLoader();
    for (String path : args[0].split(",")) data.load(new File(path));
    CoverageBuilder builder = new CoverageBuilder();
    for (int i = 1; i < args.length; i++)
      new Analyzer(data.getExecutionDataStore(), builder).analyzeAll(new File(args[i]));
    for (IClassCoverage c : builder.getClasses()) {
      if (!CLASSES.contains(c.getName())) continue;
      System.out.println("COVERAGE class=" + c.getName() + " methods="
        + c.getMethodCounter().getCoveredCount() + " branches="
        + c.getBranchCounter().getCoveredCount() + " lines="
        + c.getLineCounter().getCoveredCount());
      if (c.getName().endsWith("TransitRegionStateProcedure"))
        System.out.println("TARGET line=379 instructions="
          + c.getLine(379).getInstructionCounter().getCoveredCount());
    }
  }
}
