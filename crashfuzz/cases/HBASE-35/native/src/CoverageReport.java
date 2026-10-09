import java.io.File;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.tools.ExecFileLoader;

/** Reports the exact source lines of HBaseFsck's anonymous meta visitor. */
public class CoverageReport {
  public static void main(String[] args) throws Exception {
    ExecFileLoader data = new ExecFileLoader();
    for (String path : args[0].split(",")) data.load(new File(path));
    CoverageBuilder builder = new CoverageBuilder();
    for (int i = 1; i < args.length; i++)
      new Analyzer(data.getExecutionDataStore(), builder).analyzeAll(new File(args[i]));
    for (IClassCoverage c : builder.getClasses()) {
      String name = c.getName();
      if (!name.equals("org/apache/hadoop/hbase/util/HBaseFsck$3")
          && !name.equals("org/apache/hadoop/hbase/util/HBaseFsck")
          && !name.equals("org/apache/hadoop/hbase/MetaTableAccessor")
          && !name.equals("org/apache/hadoop/hbase/client/ClientScanner")
          && !name.equals("org/apache/hadoop/hbase/regionserver/RSRpcServices")) continue;
      System.out.println("COVERAGE class=" + c.getName() + " methods="
        + c.getMethodCounter().getCoveredCount() + " branches="
        + c.getBranchCounter().getCoveredCount() + " lines="
        + c.getLineCounter().getCoveredCount());
      if (!name.equals("org/apache/hadoop/hbase/util/HBaseFsck$3")) continue;
      for (int line : new int[]{2688, 2695, 2700, 2714, 2715, 2716, 2717,
                                2718, 2720, 2723}) {
        System.out.println("COVERAGE line=" + line + " instructions="
          + c.getLine(line).getInstructionCounter().getCoveredCount() + " branches="
          + c.getLine(line).getBranchCounter().getCoveredCount());
      }
    }
  }
}
