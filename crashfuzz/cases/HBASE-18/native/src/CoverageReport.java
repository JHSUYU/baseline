import java.io.File;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.tools.ExecFileLoader;

/** Reports selected original HBase production coverage and exact target lines. */
public class CoverageReport {
  public static void main(String[] args) throws Exception {
    ExecFileLoader data = new ExecFileLoader();
    for (String path : args[0].split(",")) data.load(new File(path));
    CoverageBuilder builder = new CoverageBuilder();
    new Analyzer(data.getExecutionDataStore(), builder).analyzeAll(new File(args[1]));
    for (IClassCoverage c : builder.getClasses()) {
      String name = c.getName();
      if (!name.equals("org/apache/hadoop/hbase/master/assignment/TransitRegionStateProcedure")
          && !name.equals("org/apache/hadoop/hbase/master/assignment/OpenRegionProcedure")
          && !name.equals("org/apache/hadoop/hbase/master/assignment/AssignmentManager")
          && !name.equals("org/apache/hadoop/hbase/master/assignment/RegionStates")
          && !name.equals("org/apache/hadoop/hbase/master/assignment/RegionStateNode")
          && !name.equals("org/apache/hadoop/hbase/master/assignment/RegionRemoteProcedureBase")
          && !name.equals("org/apache/hadoop/hbase/master/procedure/RSProcedureDispatcher")
          && !name.startsWith("org/apache/hadoop/hbase/master/procedure/RSProcedureDispatcher$ExecuteProceduresRemoteCall")) continue;
      System.out.println("COVERAGE class=" + c.getName() + " methods="
        + c.getMethodCounter().getCoveredCount() + " branches="
        + c.getBranchCounter().getCoveredCount() + " lines="
        + c.getLineCounter().getCoveredCount());
      if (name.endsWith("TransitRegionStateProcedure")) {
        for (int line : new int[]{284, 287, 302, 317, 323, 325}) {
          System.out.println("COVERAGE line=" + line + " instructions="
            + c.getLine(line).getInstructionCounter().getCoveredCount() + " branches="
            + c.getLine(line).getBranchCounter().getCoveredCount());
        }
      }
    }
  }
}
