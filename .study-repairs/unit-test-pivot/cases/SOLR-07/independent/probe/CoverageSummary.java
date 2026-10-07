package baseline.solr07;

import java.io.File;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Collection;
import java.util.Enumeration;
import java.util.HashSet;
import java.util.HashMap;
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

/** Summarize methods and branches for executed Solr production classes only. */
public final class CoverageSummary {
  public static void main(String[] args) throws Exception {
    if (args.length < 3) {
      throw new IllegalArgumentException("dist-directory override-classes jacoco.exec...");
    }
    File dist = new File(args[0]);
    Path overrides = new File(args[1]).toPath();
    ExecFileLoader loader = new ExecFileLoader();
    for (int i = 2; i < args.length; i++) loader.load(new File(args[i]));
    Map<String, ExecutionData> executions = new HashMap<>();
    for (ExecutionData data : loader.getExecutionDataStore().getContents()) {
      executions.put(data.getName(), data);
    }
    CoverageBuilder builder = new CoverageBuilder();
    Analyzer analyzer = new Analyzer(loader.getExecutionDataStore(), builder);
    Set<String> seen = new HashSet<>();
    File[] jars = dist.listFiles();
    if (jars == null) throw new IllegalArgumentException("Missing dist directory: " + dist);
    for (File jar : jars) {
      String fileName = jar.getName();
      if (!fileName.endsWith(".jar") || fileName.startsWith("solr-test-framework-")) continue;
      try (JarFile input = new JarFile(jar)) {
        Enumeration<JarEntry> entries = input.entries();
        while (entries.hasMoreElements()) {
          JarEntry entry = entries.nextElement();
          String resource = entry.getName();
          if (!resource.startsWith("org/apache/solr/") || !resource.endsWith(".class")) continue;
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
    int classes = 0, noMatch = 0, methods = 0, methodTotal = 0, branches = 0, branchTotal = 0;
    int selectedMethods = 0, selectedBranches = 0, selectedBranchTotal = 0;
    Collection<IClassCoverage> results = builder.getClasses();
    for (IClassCoverage cls : results) {
      if (cls.isNoMatch()) { noMatch++; continue; }
      classes++;
      methods += cls.getMethodCounter().getCoveredCount();
      methodTotal += cls.getMethodCounter().getTotalCount();
      branches += cls.getBranchCounter().getCoveredCount();
      branchTotal += cls.getBranchCounter().getTotalCount();
      if (cls.getName().equals("org/apache/solr/cloud/ZkController")) {
        for (IMethodCoverage method : cls.getMethods()) {
          if (method.getName().equals("register") && method.getDesc().startsWith("(Ljava/lang/String;Lorg/apache/solr/core/CoreDescriptor;ZZZ)")) {
            selectedMethods += method.getMethodCounter().getCoveredCount();
            selectedBranches += method.getBranchCounter().getCoveredCount();
            selectedBranchTotal += method.getBranchCounter().getTotalCount();
          }
        }
      }
    }
    System.out.printf("{\"classes\":%d,\"unmatched_classes\":%d,\"covered_methods\":%d,\"methods_total_in_executed_classes\":%d,\"covered_branches\":%d,\"branches_total_in_executed_classes\":%d,\"selected_register_covered\":%d,\"selected_register_branches_covered\":%d,\"selected_register_branches_total\":%d}%n",
        classes, noMatch, methods, methodTotal, branches, branchTotal,
        selectedMethods, selectedBranches, selectedBranchTotal);
  }
}
