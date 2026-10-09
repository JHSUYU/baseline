import java.io.File;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.analysis.IMethodCoverage;
import org.jacoco.core.tools.ExecFileLoader;
import org.jacoco.core.data.ExecutionData;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

/** Production method/branch coverage from a single graph-free JUnit run. */
public class CoverageReport {
  private static final Set<String> PRODUCTION_CLASSES = new HashSet<String>(Arrays.asList(
    "org/apache/hadoop/hbase/client/HBaseAdmin",
    "org/apache/hadoop/hbase/MetaTableAccessor",
    "org/apache/hadoop/hbase/ipc/AbstractRpcClient",
    "org/apache/hadoop/hbase/client/RpcRetryingCallerImpl",
    "org/apache/hadoop/hbase/client/ConnectionImplementation",
    "org/apache/hadoop/hbase/client/ClientServiceCallable",
    "org/apache/hadoop/hbase/client/MasterCallable"));

  public static void main(String[] args) throws Exception {
    ExecFileLoader data = new ExecFileLoader();
    data.load(new File(args[0]));
    for (ExecutionData execution : data.getExecutionDataStore().getContents()) {
      String name = execution.getName();
      if (!PRODUCTION_CLASSES.contains(name)) continue;
      boolean[] probes = execution.getProbes();
      for (int index = 0; index < probes.length; index++) {
        if (probes[index])
          System.out.println("PROBE class=" + name + " index=" + index);
      }
    }
    CoverageBuilder builder = new CoverageBuilder();
    new Analyzer(data.getExecutionDataStore(), builder).analyzeAll(new File(args[1]));
    for (IClassCoverage c : builder.getClasses()) {
      if (!PRODUCTION_CLASSES.contains(c.getName())) continue;
      System.out.println("COVERAGE class=" + c.getName() +
        " methods=" + c.getMethodCounter().getCoveredCount() +
        " branches=" + c.getBranchCounter().getCoveredCount() +
        " lines=" + c.getLineCounter().getCoveredCount());
      for (IMethodCoverage m : c.getMethods()) {
        if (m.getName().equals("flushAsync")
            || m.getName().equals("isTableEnabled")
            || m.getName().equals("getTableState")
            || m.getName().equals("callMethod")
            || m.getName().equals("callBlockingMethod")
            || m.getName().equals("callWithRetries")
            || m.getName().equals("prepare")
            || m.getName().equals("call")) {
          System.out.println("COVERAGE method=" + c.getName() + "." + m.getName()
            + m.getDesc() + " instructions="
            + m.getInstructionCounter().getCoveredCount() +
            " branches=" + m.getBranchCounter().getCoveredCount() +
            " lines=" + m.getLineCounter().getCoveredCount());
        }
      }
    }
  }
}
