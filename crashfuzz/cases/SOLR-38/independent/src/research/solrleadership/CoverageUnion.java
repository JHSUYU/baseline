package research.solrleadership;

import java.io.File;
import java.util.Enumeration;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.tools.ExecFileLoader;

/** Union JaCoCo records and count original release-jar methods and branches. */
public final class CoverageUnion {
  private CoverageUnion() {}

  public static void main(String[] args) throws Exception {
    int marker = -1;
    for (int index = 0; index < args.length; index++) {
      if ("--jars".equals(args[index])) { marker = index; break; }
    }
    if (marker < 1 || marker == args.length - 1)
      throw new IllegalArgumentException("exec files --jars original jars required");
    ExecFileLoader loader = new ExecFileLoader();
    for (int index = 0; index < marker; index++) loader.load(new File(args[index]));
    CoverageBuilder builder = new CoverageBuilder();
    Analyzer analyzer = new Analyzer(loader.getExecutionDataStore(), builder);
    for (int index = marker + 1; index < args.length; index++) {
      try (ZipFile jar = new ZipFile(new File(args[index]))) {
        Enumeration<? extends ZipEntry> entries = jar.entries();
        while (entries.hasMoreElements()) {
          ZipEntry entry = entries.nextElement();
          String name = entry.getName();
          if (name.endsWith(".class") &&
              (name.startsWith("org/apache/solr/") ||
               name.startsWith("org/apache/lucene/"))) {
            analyzer.analyzeClass(jar.getInputStream(entry), args[index] + "!" + name);
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
