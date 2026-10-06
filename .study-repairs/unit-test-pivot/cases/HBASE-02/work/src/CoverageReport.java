import java.io.File;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.analysis.IMethodCoverage;
import org.jacoco.core.tools.ExecFileLoader;

/** Local JaCoCo production coverage, excluding this case's probe classes. */
public class CoverageReport {
  public static void main(String[] args) throws Exception {
    ExecFileLoader data = new ExecFileLoader();
    for (String path : args[0].split(",")) data.load(new File(path));
    CoverageBuilder builder = new CoverageBuilder();
    new Analyzer(data.getExecutionDataStore(), builder).analyzeAll(new File(args[1]));
    for (IClassCoverage c : builder.getClasses()) {
      if (!c.getName().equals("org/apache/hadoop/hbase/client/ConnectionImplementation")
          && !c.getName().equals("org/apache/hadoop/hbase/client/RpcRetryingCallerImpl")
          && !c.getName().equals("org/apache/hadoop/hbase/MetaTableAccessor")) continue;
      System.out.println("COVERAGE class=" + c.getName() + " methods="
        + c.getMethodCounter().getCoveredCount() + " branches="
        + c.getBranchCounter().getCoveredCount() + " lines="
        + c.getLineCounter().getCoveredCount());
      for (IMethodCoverage m : c.getMethods()) {
        if (m.getName().equals("relocateRegion") || m.getName().equals("getTableState")
            || m.getName().equals("callWithRetries")) {
          System.out.println("COVERAGE method=" + c.getName() + "." + m.getName()
            + m.getDesc() + " instructions=" + m.getInstructionCounter().getCoveredCount()
            + " branches=" + m.getBranchCounter().getCoveredCount()
            + " lines=" + m.getLineCounter().getCoveredCount());
        }
      }
      if (c.getName().endsWith("ConnectionImplementation")) {
        System.out.println("COVERAGE line=910 instructions="
          + c.getLine(910).getInstructionCounter().getCoveredCount()
          + " branches=" + c.getLine(910).getBranchCounter().getCoveredCount());
        System.out.println("COVERAGE line=911 instructions="
          + c.getLine(911).getInstructionCounter().getCoveredCount());
      }
    }
  }
}
