import java.io.File;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.analysis.ILine;
import org.jacoco.core.tools.ExecFileLoader;

/** Counts actual production instructions/branches at the selected source lines. */
public final class CoverageLine27 {
  public static void main(String[] args) throws Exception {
    ExecFileLoader data = new ExecFileLoader();
    for (String path : args[0].split(",")) data.load(new File(path));
    CoverageBuilder builder = new CoverageBuilder();
    for (int i = 1; i < args.length; i++)
      new Analyzer(data.getExecutionDataStore(), builder).analyzeAll(new File(args[i]));
    int methods = 0;
    int branches = 0;
    for (IClassCoverage c : builder.getClasses()) {
      if (!c.getName().equals("org/apache/hadoop/hbase/regionserver/HRegionServer")
          && !c.getName().equals("org/apache/hadoop/hbase/zookeeper/ZKNodeTracker")
          && !c.getName().equals("org/apache/hadoop/hbase/zookeeper/ZKUtil")) continue;
      int coveredMethods = c.getMethodCounter().getCoveredCount();
      int coveredBranches = c.getBranchCounter().getCoveredCount();
      methods += coveredMethods;
      branches += coveredBranches;
      System.out.println("CLASS name=" + c.getName() + " methods=" + coveredMethods
        + " branches=" + coveredBranches);
      if (!c.getName().equals("org/apache/hadoop/hbase/regionserver/HRegionServer")) continue;
      for (int line : new int[] {1051, 1052, 1053}) {
        ILine value = c.getLine(line);
        System.out.println("LINE " + line + " instructions="
          + value.getInstructionCounter().getCoveredCount() + "/"
          + value.getInstructionCounter().getTotalCount() + " branches="
          + value.getBranchCounter().getCoveredCount() + "/"
          + value.getBranchCounter().getTotalCount());
      }
    }
    System.out.println("TOTAL methods=" + methods + " branches=" + branches);
  }
}
