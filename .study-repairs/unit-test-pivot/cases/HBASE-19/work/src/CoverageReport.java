import java.io.File;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.tools.ExecFileLoader;

/** Combined production coverage for the two guards and their descriptor I/O. */
public final class CoverageReport {
  public static void main(String[] args) throws Exception {
    ExecFileLoader data = new ExecFileLoader();
    for (String path : args[0].split(",")) data.load(new File(path));
    CoverageBuilder builder = new CoverageBuilder();
    for (int i = 1; i < args.length; i++)
      new Analyzer(data.getExecutionDataStore(), builder).analyzeAll(new File(args[i]));
    for (IClassCoverage c : builder.getClasses()) {
      String name = c.getName();
      if (!name.equals("org/apache/hadoop/hbase/master/procedure/ModifyTableProcedure")
          && !name.equals("org/apache/hadoop/hbase/master/procedure/AbstractStateMachineTableProcedure")
          && !name.equals("org/apache/hadoop/hbase/util/FSTableDescriptors")) continue;
      System.out.println("COVERAGE class=" + name + " methods="
          + c.getMethodCounter().getCoveredCount() + " branches="
          + c.getBranchCounter().getCoveredCount() + " lines="
          + c.getLineCounter().getCoveredCount());
      for (int line = c.getFirstLine(); line <= c.getLastLine(); line++) {
        if (c.getLine(line).getBranchCounter().getCoveredCount() > 0)
          System.out.println("BRANCH class=" + name + " line=" + line + " covered="
              + c.getLine(line).getBranchCounter().getCoveredCount());
      }
      if (name.endsWith("ModifyTableProcedure")) {
        System.out.println("TARGET line=135 instructions="
            + c.getLine(135).getInstructionCounter().getCoveredCount());
        System.out.println("TARGET line=139 instructions="
            + c.getLine(139).getInstructionCounter().getCoveredCount());
      }
    }
  }
}
