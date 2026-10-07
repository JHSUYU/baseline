package research.solrsplit;

import java.io.File;
import java.util.Enumeration;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.data.ExecutionData;
import org.jacoco.core.tools.ExecFileLoader;

/** Read JaCoCo probes and branch counters from original unmodified jars. */
public final class Coverage {
  private Coverage() {}

  public static void main(String[] args) throws Exception {
    if (args.length < 1) throw new IllegalArgumentException("exec file required");
    ExecFileLoader loader = new ExecFileLoader();
    loader.load(new File(args[0]));
    for (ExecutionData data : loader.getExecutionDataStore().getContents()) {
      String name = data.getName();
      if (!(name.startsWith("org/apache/solr/") || name.startsWith("org/apache/lucene/"))) continue;
      boolean[] probes = data.getProbes();
      for (int index = 0; index < probes.length; index++) {
        if (probes[index]) System.out.println("P\t" + Long.toHexString(data.getId())
            + "\t" + name + "\t" + index);
      }
    }
    if (args.length > 1) {
      CoverageBuilder builder = new CoverageBuilder();
      Analyzer analyzer = new Analyzer(loader.getExecutionDataStore(), builder);
      for (int i = 1; i < args.length; i++) {
        try (ZipFile jar = new ZipFile(new File(args[i]))) {
          Enumeration<? extends ZipEntry> entries = jar.entries();
          while (entries.hasMoreElements()) {
            ZipEntry entry = entries.nextElement();
            String name = entry.getName();
            if (name.endsWith(".class") &&
                (name.startsWith("org/apache/solr/") ||
                 name.startsWith("org/apache/lucene/"))) {
              analyzer.analyzeClass(jar.getInputStream(entry), args[i] + "!" + name);
            }
          }
        }
      }
      for (IClassCoverage covered : builder.getClasses()) {
        String name = covered.getName();
        if (!(name.startsWith("org/apache/solr/") || name.startsWith("org/apache/lucene/"))) continue;
        System.out.println("B\t" + name + "\t"
            + covered.getBranchCounter().getCoveredCount() + "\t"
            + covered.getBranchCounter().getTotalCount());
      }
    }
  }
}
