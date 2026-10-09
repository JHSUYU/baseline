import java.io.File;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.tools.ExecFileLoader;

/** Selected HBase client and server production coverage, excluding probe classes. */
public class CoverageReport {
  public static void main(String[] args) throws Exception {
    ExecFileLoader data = new ExecFileLoader();
    for (String path : args[0].split(",")) data.load(new File(path));
    CoverageBuilder builder = new CoverageBuilder();
    Analyzer analyzer = new Analyzer(data.getExecutionDataStore(), builder);
    analyzer.analyzeAll(new File(args[1]));
    analyzer.analyzeAll(new File(args[2]));
    for (IClassCoverage c : builder.getClasses()) {
      String name = c.getName();
      if (!name.equals("org/apache/hadoop/hbase/master/assignment/MergeTableRegionsProcedure")
          && !name.equals("org/apache/hadoop/hbase/master/assignment/RegionStates")
          && !name.equals("org/apache/hadoop/hbase/master/RegionState")
          && !name.equals("org/apache/hadoop/hbase/MetaTableAccessor")
          && !name.equals("org/apache/hadoop/hbase/client/ClientServiceCallable")
          && !name.equals("org/apache/hadoop/hbase/client/RpcRetryingCallerImpl")) continue;
      System.out.println("COVERAGE class=" + name + " methods="
        + c.getMethodCounter().getCoveredCount() + " branches="
        + c.getBranchCounter().getCoveredCount() + " lines="
        + c.getLineCounter().getCoveredCount());
      if (name.endsWith("MergeTableRegionsProcedure")) {
        for (int line : new int[]{488, 495, 498, 500, 502, 503}) {
          System.out.println("COVERAGE line=" + line + " instructions="
            + c.getLine(line).getInstructionCounter().getCoveredCount() + " branches="
            + c.getLine(line).getBranchCounter().getCoveredCount());
        }
      }
    }
  }
}
