package research.solrleadership;

import java.io.File;
import org.jacoco.core.data.ExecutionData;
import org.jacoco.core.tools.ExecFileLoader;

/** Emits covered JaCoCo probes; the Python adapter filters to original production classes. */
public final class Coverage {
  private Coverage() {}

  public static void main(String[] args) throws Exception {
    if (args.length != 1) throw new IllegalArgumentException("exec file required");
    ExecFileLoader loader = new ExecFileLoader();
    loader.load(new File(args[0]));
    for (ExecutionData data : loader.getExecutionDataStore().getContents()) {
      String name = data.getName();
      if (!(name.startsWith("org/apache/solr/") || name.startsWith("org/apache/lucene/")))
        continue;
      boolean[] probes = data.getProbes();
      for (int index = 0; index < probes.length; index++) {
        if (probes[index]) System.out.println("P\t" + Long.toHexString(data.getId())
            + "\t" + name + "\t" + index);
      }
    }
  }
}
