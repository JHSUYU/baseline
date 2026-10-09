package zk05;

import java.io.File;
import org.jacoco.core.data.ExecutionData;
import org.jacoco.core.tools.ExecFileLoader;

/** Emits each covered production JaCoCo probe as class, class ID, probe index. */
public final class CoverageDump {
  public static void main(String[] args) throws Exception {
    ExecFileLoader loader = new ExecFileLoader();
    loader.load(new File(args[0]));
    for (ExecutionData data : loader.getExecutionDataStore().getContents()) {
      if (!data.getName().startsWith("org/apache/zookeeper/")) continue;
      boolean[] probes = data.getProbes();
      for (int i = 0; i < probes.length; i++) {
        if (probes[i]) System.out.println(data.getName() + "\t" + data.getId() + "\t" + i);
      }
    }
  }
}
