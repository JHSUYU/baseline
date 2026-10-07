package research.solrsplit;

import java.io.File;
import java.util.Enumeration;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.tools.ExecFileLoader;

/** Union probe data from completed runs, then inspect original release classes. */
public final class CoverageUnion {
  private CoverageUnion() {}

  public static void main(String[] args) throws Exception {
    int jarMarker = -1;
    for (int i = 0; i < args.length; i++) {
      if ("--jars".equals(args[i])) { jarMarker = i; break; }
    }
    if (jarMarker < 1 || jarMarker == args.length - 1)
      throw new IllegalArgumentException("exec files --jars original jars required");
    ExecFileLoader loader = new ExecFileLoader();
    for (int i = 0; i < jarMarker; i++) loader.load(new File(args[i]));
    CoverageBuilder builder = new CoverageBuilder();
    Analyzer analyzer = new Analyzer(loader.getExecutionDataStore(), builder);
    for (int i = jarMarker + 1; i < args.length; i++) {
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
      System.out.println("C\t" + covered.getName() + "\t"
          + covered.getMethodCounter().getCoveredCount() + "\t"
          + covered.getBranchCounter().getCoveredCount());
    }
  }
}
