import java.io.File;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.tools.ExecFileLoader;

/** Production coverage for the target handler and its real flush RPC caller. */
public final class CoverageReport {
  public static void main(String[] args) throws Exception {
    ExecFileLoader data = new ExecFileLoader();
    for (String path : args[0].split(",")) data.load(new File(path));
    CoverageBuilder builder = new CoverageBuilder();
    for (int i = 1; i < args.length; i++) {
      new Analyzer(data.getExecutionDataStore(), builder).analyzeAll(new File(args[i]));
    }
    for (IClassCoverage c : builder.getClasses()) {
      String name = c.getName();
      if (!name.equals("org/apache/hadoop/hbase/regionserver/handler/RegionReplicaFlushHandler")
          && !name.equals("org/apache/hadoop/hbase/client/FlushRegionCallable")) continue;
      System.out.println("COVERAGE class=" + name + " methods="
        + c.getMethodCounter().getCoveredCount() + " branches="
        + c.getBranchCounter().getCoveredCount() + " lines="
        + c.getLineCounter().getCoveredCount());
      if (name.endsWith("RegionReplicaFlushHandler")) {
        System.out.println("TARGET line=136 instructions="
          + c.getLine(136).getInstructionCounter().getCoveredCount()
          + " branches=" + c.getLine(136).getBranchCounter().getCoveredCount());
      }
    }
  }
}
