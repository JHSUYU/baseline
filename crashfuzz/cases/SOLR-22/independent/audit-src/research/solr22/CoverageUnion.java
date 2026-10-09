package research.solr22;

import java.io.File;
import java.util.Enumeration;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.analysis.IMethodCoverage;
import org.jacoco.core.tools.ExecFileLoader;

/** Merge independent JaCoCo executions and audit original production jars. */
public final class CoverageUnion {
  private CoverageUnion() {}

  public static void main(String[] args) throws Exception {
    if (args.length < 4) throw new IllegalArgumentException("jar count, jars, and exec files required");
    int jarCount = Integer.parseInt(args[0]);
    if (jarCount < 1 || args.length <= jarCount + 1)
      throw new IllegalArgumentException("invalid jar count or no executions");
    ExecFileLoader loader = new ExecFileLoader();
    for (int i = jarCount + 1; i < args.length; i++) loader.load(new File(args[i]));
    CoverageBuilder builder = new CoverageBuilder();
    Analyzer analyzer = new Analyzer(loader.getExecutionDataStore(), builder);
    for (int i = 1; i <= jarCount; i++) {
      try (ZipFile jar = new ZipFile(new File(args[i]))) {
        Enumeration<? extends ZipEntry> entries = jar.entries();
        while (entries.hasMoreElements()) {
          ZipEntry entry = entries.nextElement();
          String name = entry.getName();
          if (name.endsWith(".class") &&
              (name.startsWith("org/apache/solr/") || name.startsWith("org/apache/lucene/"))) {
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
      for (IMethodCoverage method : covered.getMethods()) {
        if (method.getInstructionCounter().getCoveredCount() > 0)
          System.out.println("M\t" + name + "\t" + method.getName() + method.getDesc());
      }
    }
  }
}
