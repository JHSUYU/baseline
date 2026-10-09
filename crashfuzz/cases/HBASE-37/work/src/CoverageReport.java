import java.io.File;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.tools.ExecFileLoader;

/** Relevant production method/branch coverage and the exact source-line outcome. */
public final class CoverageReport {
  public static void main(String[] args) throws Exception {
    ExecFileLoader data = new ExecFileLoader();
    for (String path : args[0].split(",")) data.load(new File(path));
    CoverageBuilder builder = new CoverageBuilder();
    for (int i = 1; i < args.length; i++)
      new Analyzer(data.getExecutionDataStore(), builder).analyzeAll(new File(args[i]));
    for (IClassCoverage c : builder.getClasses()) {
      String name = c.getName();
      if (!name.equals("org/apache/hadoop/hbase/zookeeper/MasterAddressTracker")
          && !name.equals("org/apache/hadoop/hbase/zookeeper/ZKUtil")
          && !name.equals("org/apache/hadoop/hbase/zookeeper/RecoverableZooKeeper")
          && !name.equals("org/apache/hadoop/hbase/master/ActiveMasterManager")
          && !name.equals("org/apache/hadoop/hbase/master/HMaster")) continue;
      System.out.println("COVERAGE class=" + name + " methods="
          + c.getMethodCounter().getCoveredCount() + " branches="
          + c.getBranchCounter().getCoveredCount() + " lines="
          + c.getLineCounter().getCoveredCount());
      if (name.equals("org/apache/hadoop/hbase/zookeeper/MasterAddressTracker")) {
        System.out.println("TARGET line=205 instructions="
            + c.getLine(205).getInstructionCounter().getCoveredCount()
            + " branches=" + c.getLine(205).getBranchCounter().getCoveredCount());
        System.out.println("TARGET line=206 instructions="
            + c.getLine(206).getInstructionCounter().getCoveredCount());
      }
    }
  }
}
