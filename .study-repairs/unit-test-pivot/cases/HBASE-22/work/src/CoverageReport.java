import java.io.File;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.tools.ExecFileLoader;

/** Reports cumulative JaCoCo production method and branch coverage. */
public final class CoverageReport {
  public static void main(String[] args) throws Exception {
    ExecFileLoader data = new ExecFileLoader();
    for (String path : args[0].split(",")) data.load(new File(path));
    CoverageBuilder builder = new CoverageBuilder();
    for (int i = 1; i < args.length; i++)
      new Analyzer(data.getExecutionDataStore(), builder).analyzeAll(new File(args[i]));
    for (IClassCoverage c : builder.getClasses()) {
      String name = c.getName();
      if (!name.equals("org/apache/hadoop/hbase/namespace/NamespaceStateManager")
          && !name.equals("org/apache/hadoop/hbase/master/TableNamespaceManager")
          && !name.equals("org/apache/hadoop/hbase/ZKNamespaceManager")
          && !name.equals("org/apache/hadoop/hbase/master/procedure/CreateNamespaceProcedure")) continue;
      System.out.println("COVERAGE class=" + name + " methods="
          + c.getMethodCounter().getCoveredCount() + " branches="
          + c.getBranchCounter().getCoveredCount() + " lines="
          + c.getLineCounter().getCoveredCount());
      for (int line = c.getFirstLine(); line <= c.getLastLine(); line++) {
        if (c.getLine(line).getBranchCounter().getCoveredCount() > 0)
          System.out.println("BRANCH class=" + name + " line=" + line + " covered="
              + c.getLine(line).getBranchCounter().getCoveredCount());
      }
      if (name.endsWith("NamespaceStateManager"))
        System.out.println("TARGET line=172 covered="
            + c.getLine(172).getInstructionCounter().getCoveredCount());
    }
  }
}
