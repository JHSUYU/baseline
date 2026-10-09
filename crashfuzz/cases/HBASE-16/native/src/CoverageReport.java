import java.io.File;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.tools.ExecFileLoader;

/** Selected original HBase server production coverage, excluding probe classes. */
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
      if (!name.equals("org/apache/hadoop/hbase/master/assignment/TransitRegionStateProcedure")
          && !name.equals("org/apache/hadoop/hbase/master/assignment/RegionStateNode")
          && !name.equals("org/apache/hadoop/hbase/master/assignment/CloseRegionProcedure")
          && !name.equals("org/apache/hadoop/hbase/master/assignment/RegionRemoteProcedureBase")
          && !name.equals("org/apache/hadoop/hbase/master/procedure/RSProcedureDispatcher")
          && !name.startsWith("org/apache/hadoop/hbase/master/procedure/RSProcedureDispatcher$ExecuteProceduresRemoteCall")
          && !name.equals("org/apache/hadoop/hbase/client/HBaseAdmin")
          && !name.equals("org/apache/hadoop/hbase/client/MasterCallable")
          && !name.equals("org/apache/hadoop/hbase/client/RpcRetryingCallerImpl")) continue;
      System.out.println("COVERAGE class=" + name + " methods="
        + c.getMethodCounter().getCoveredCount() + " branches="
        + c.getBranchCounter().getCoveredCount() + " lines="
        + c.getLineCounter().getCoveredCount());
      if (name.endsWith("TransitRegionStateProcedure")) {
        for (int line : new int[]{355, 366, 370, 371}) {
          System.out.println("COVERAGE line=" + line + " instructions="
            + c.getLine(line).getInstructionCounter().getCoveredCount() + " branches="
            + c.getLine(line).getBranchCounter().getCoveredCount());
        }
      }
    }
  }
}
