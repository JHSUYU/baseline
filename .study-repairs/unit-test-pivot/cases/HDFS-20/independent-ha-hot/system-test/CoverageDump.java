import java.io.File;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.HashSet;
import java.util.Set;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;

import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.analysis.ICounter;
import org.jacoco.core.analysis.IMethodCoverage;
import org.jacoco.core.data.ExecutionData;
import org.jacoco.core.tools.ExecFileLoader;

/** Dump exact JaCoCo probes plus production method and branch counts. */
public final class CoverageDump {
  private static final String BLOCK =
      "org/apache/hadoop/hdfs/server/datanode/BPOfferService";
  private static final String ACTOR =
      "org/apache/hadoop/hdfs/server/datanode/BPServiceActor";
  private static final String EDIT_LOG =
      "org/apache/hadoop/hdfs/server/namenode/EditLogFileOutputStream";

  private static boolean production(String name) {
    return name.startsWith("org/apache/hadoop/hdfs/") &&
        !name.startsWith("org/apache/hadoop/hdfs/hdfs20hotindependent/");
  }

  public static void main(String[] args) throws Exception {
    if (args.length < 4) {
      throw new IllegalArgumentException(
          "Usage: CoverageDump jacoco.exec overrideClasses hdfs.jar hdfs-client.jar ...");
    }
    ExecFileLoader loader = new ExecFileLoader();
    loader.load(new File(args[0]));
    CoverageBuilder builder = new CoverageBuilder();
    Analyzer analyzer = new Analyzer(loader.getExecutionDataStore(), builder);
    Path overrides = Paths.get(args[1]);
    for (String name : new String[] {BLOCK, ACTOR, EDIT_LOG}) {
      Path file = overrides.resolve(name + ".class");
      try (InputStream stream = Files.newInputStream(file)) {
        analyzer.analyzeClass(stream, file.toString());
      }
    }
    for (int arg = 2; arg < args.length; arg++) {
      try (JarFile jar = new JarFile(args[arg])) {
        java.util.Enumeration<JarEntry> entries = jar.entries();
        while (entries.hasMoreElements()) {
          JarEntry entry = entries.nextElement();
          String path = entry.getName();
          if (!path.endsWith(".class") || !production(path) ||
              path.equals(BLOCK + ".class") ||
              path.equals(ACTOR + ".class") ||
              path.equals(EDIT_LOG + ".class")) {
            continue;
          }
          try (InputStream stream = jar.getInputStream(entry)) {
            analyzer.analyzeClass(stream, path);
          }
        }
      }
    }
    Set<String> ids = new HashSet<String>();
    Set<String> analyzedProductionClasses = new HashSet<String>();
    for (IClassCoverage cls : builder.getClasses()) {
      if (production(cls.getName())) {
        analyzedProductionClasses.add(cls.getName());
      }
    }
    for (ExecutionData data : loader.getExecutionDataStore().getContents()) {
      // Execution data also contains the original test JAR.  Only the two
      // source overrides and classes analyzed from production JARs count.
      if (!analyzedProductionClasses.contains(data.getName())) {
        continue;
      }
      boolean[] probes = data.getProbes();
      for (int index = 0; index < probes.length; index++) {
        if (probes[index]) {
          ids.add("PROBE\t" + data.getName() + ":" + index);
        }
      }
    }
    for (IClassCoverage cls : builder.getClasses()) {
      if (!production(cls.getName())) {
        continue;
      }
      for (IMethodCoverage method : cls.getMethods()) {
        if (method.getMethodCounter().getCoveredCount() > 0) {
          ids.add("METHOD\t" + cls.getName() + "." + method.getName() +
              method.getDesc());
        }
        if (method.getFirstLine() == -1) {
          continue;
        }
        for (int line = method.getFirstLine(); line <= method.getLastLine();
             line++) {
          ICounter counter = method.getLine(line).getBranchCounter();
          for (int unit = 1; unit <= counter.getCoveredCount(); unit++) {
            ids.add("BRANCH_UNIT\t" + cls.getName() + "." +
                method.getName() + method.getDesc() + ":" + line + ":" + unit);
          }
        }
      }
    }
    java.util.List<String> ordered = new java.util.ArrayList<String>(ids);
    java.util.Collections.sort(ordered);
    for (String id : ordered) {
      System.out.println(id);
    }
  }
}
