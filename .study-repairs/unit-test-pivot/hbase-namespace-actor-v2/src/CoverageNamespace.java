import java.io.File;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.analysis.IMethodCoverage;
import org.jacoco.core.tools.ExecFileLoader;

/** Production-only cumulative method/branch feedback for the namespace JUnit. */
public final class CoverageNamespace {
  private static boolean relevant(String name) {
    return name.equals("org/apache/hadoop/hbase/master/ClusterSchemaServiceImpl")
        || name.equals("org/apache/hadoop/hbase/namespace/NamespaceStateManager")
        || name.equals("org/apache/hadoop/hbase/master/TableNamespaceManager")
        || name.equals("org/apache/hadoop/hbase/ZKNamespaceManager");
  }

  public static void main(String[] args) throws Exception {
    if (args.length < 2) throw new IllegalArgumentException("exec[,exec] server-jar");
    ExecFileLoader data = new ExecFileLoader();
    for (String path : args[0].split(",")) data.load(new File(path));
    CoverageBuilder builder = new CoverageBuilder();
    for (int i = 1; i < args.length; i++)
      new Analyzer(data.getExecutionDataStore(), builder).analyzeAll(new File(args[i]));
    for (IClassCoverage c : builder.getClasses()) {
      String name = c.getName();
      if (!relevant(name)) continue;
      System.out.println("COVERAGE class=" + name + " methods="
          + c.getMethodCounter().getCoveredCount() + " branches="
          + c.getBranchCounter().getCoveredCount() + " lines="
          + c.getLineCounter().getCoveredCount());
      for (IMethodCoverage m : c.getMethods()) {
        if (m.getMethodCounter().getCoveredCount() > 0)
          System.out.println("METHOD class=" + name + " name=" + m.getName()
              + " desc=" + m.getDesc() + " branches="
              + m.getBranchCounter().getCoveredCount());
      }
      for (int line = c.getFirstLine(); line <= c.getLastLine(); line++) {
        int covered = c.getLine(line).getBranchCounter().getCoveredCount();
        if (covered > 0)
          System.out.println("BRANCH class=" + name + " line=" + line
              + " covered=" + covered);
      }
    }
  }
}
