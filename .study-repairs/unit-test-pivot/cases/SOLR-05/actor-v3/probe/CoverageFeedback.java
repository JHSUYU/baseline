package baseline.solr05v2;

import java.io.File;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.analysis.IMethodCoverage;
import org.jacoco.core.data.ExecutionData;
import org.jacoco.core.tools.ExecFileLoader;

/** Per-method production coverage and covered branch counts for extension decisions. */
public final class CoverageFeedback {
  public static void main(String[] args) throws Exception {
    if (args.length != 3)
      throw new IllegalArgumentException("dist-directory override-classes jacoco.exec");
    File dist = new File(args[0]);
    Path overrides = new File(args[1]).toPath();
    ExecFileLoader loader = new ExecFileLoader();
    loader.load(new File(args[2]));
    Map<String, ExecutionData> executions = new HashMap<>();
    for (ExecutionData data : loader.getExecutionDataStore().getContents())
      executions.put(data.getName(), data);
    CoverageBuilder builder = new CoverageBuilder();
    Analyzer analyzer = new Analyzer(loader.getExecutionDataStore(), builder);
    Set<String> seen = new HashSet<>();
    File[] jars = dist.listFiles();
    if (jars == null) throw new IllegalArgumentException("Missing Solr dist: " + dist);
    for (File jar : jars) {
      if (!jar.getName().endsWith(".jar") || jar.getName().startsWith("solr-test-framework-"))
        continue;
      try (JarFile input = new JarFile(jar)) {
        Enumeration<JarEntry> entries = input.entries();
        while (entries.hasMoreElements()) {
          JarEntry entry = entries.nextElement();
          String resource = entry.getName();
          if (!resource.startsWith("org/apache/solr/") || !resource.endsWith(".class"))
            continue;
          String name = resource.substring(0, resource.length() - 6);
          if (!seen.add(name)) continue;
          ExecutionData data = executions.get(name);
          if (data == null) continue;
          boolean covered = false;
          for (boolean probe : data.getProbes()) if (probe) { covered = true; break; }
          if (!covered) continue;
          Path override = overrides.resolve(resource);
          if (Files.exists(override)) {
            try (InputStream stream = Files.newInputStream(override)) {
              analyzer.analyzeClass(stream, override.toString());
            }
          } else {
            try (InputStream stream = input.getInputStream(entry)) {
              analyzer.analyzeClass(stream, jar.getName() + "!" + resource);
            }
          }
        }
      }
    }
    for (IClassCoverage cls : builder.getClasses()) {
      if (cls.isNoMatch()) continue;
      for (IMethodCoverage method : cls.getMethods()) {
        if (method.getMethodCounter().getCoveredCount() == 0) continue;
        String id = cls.getName() + "#" + method.getName() + method.getDesc();
        System.out.println(id + "\t" + method.getBranchCounter().getCoveredCount());
      }
    }
  }
}
