import java.io.File;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.tools.ExecFileLoader;

/** Reports production coverage around replay RPC and its caller. */
public final class CoverageReport {
  public static void main(String[] args) throws Exception {
    ExecFileLoader data = new ExecFileLoader();
    for (String path : args[0].split(",")) data.load(new File(path));
    CoverageBuilder builder = new CoverageBuilder();
    for (int i = 1; i < args.length; i++)
      new Analyzer(data.getExecutionDataStore(), builder).analyzeAll(new File(args[i]));
    for (IClassCoverage c : builder.getClasses()) {
      String name = c.getName();
      if (!name.equals("org/apache/hadoop/hbase/regionserver/RSRpcServices")
          && !name.equals("org/apache/hadoop/hbase/wal/WALSplitUtil")
          && !name.equals("org/apache/hadoop/hbase/replication/regionserver/RegionReplicaReplicationEndpoint")
          && !name.endsWith("RegionReplicaReplicationEndpoint$RegionReplicaReplayCallable"))
        continue;
      System.out.println("COVERAGE class=" + name + " methods="
          + c.getMethodCounter().getCoveredCount() + " branches="
          + c.getBranchCounter().getCoveredCount() + " lines="
          + c.getLineCounter().getCoveredCount());
      if (name.equals("org/apache/hadoop/hbase/regionserver/RSRpcServices"))
        System.out.println("TARGET line=2260 instructions="
            + c.getLine(2260).getInstructionCounter().getCoveredCount()
            + " branches=" + c.getLine(2260).getBranchCounter().getCoveredCount());
      if (name.equals("org/apache/hadoop/hbase/regionserver/RSRpcServices"))
        System.out.println("TARGET line=2263 instructions="
            + c.getLine(2263).getInstructionCounter().getCoveredCount());
    }
  }
}
