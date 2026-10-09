import java.io.File;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.tools.ExecFileLoader;

/** JaCoCo coverage of the selected original production method. */
public class CoverageReport {
  public static void main(String[] args) throws Exception {
    ExecFileLoader data = new ExecFileLoader();
    data.load(new File(args[0]));
    CoverageBuilder builder = new CoverageBuilder();
    new Analyzer(data.getExecutionDataStore(), builder).analyzeAll(new File(args[1]));
    for (IClassCoverage c : builder.getClasses()) {
      if (!c.getName().equals(
          "org/apache/hadoop/hbase/security/token/AuthenticationTokenSecretManager")) continue;
      System.out.println("COVERAGE class=" + c.getName() + " methods="
        + c.getMethodCounter().getCoveredCount() + " branches="
        + c.getBranchCounter().getCoveredCount() + " lines="
        + c.getLineCounter().getCoveredCount());
      for (int line : new int[]{132, 134, 137, 138, 139, 141, 153, 157, 159, 160, 163}) {
        System.out.println("COVERAGE line=" + line + " instructions="
          + c.getLine(line).getInstructionCounter().getCoveredCount() + " branches="
          + c.getLine(line).getBranchCounter().getCoveredCount());
      }
    }
  }
}
