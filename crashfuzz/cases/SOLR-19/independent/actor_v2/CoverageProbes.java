package baseline.solr19v2;

import java.io.File;
import java.util.Enumeration;
import java.util.HashSet;
import java.util.Set;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import org.jacoco.core.data.ExecutionData;
import org.jacoco.core.tools.ExecFileLoader;

/** Stable production JaCoCo probe identities for feedback, including overlays. */
public final class CoverageProbes {
  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("dist-directory jacoco.exec");
    Set<String> production = new HashSet<>();
    File[] jars = new File(args[0]).listFiles();
    if (jars == null) throw new IllegalArgumentException("Missing Solr dist directory");
    for (File jar : jars) {
      String name = jar.getName();
      if (!name.endsWith(".jar") || name.startsWith("solr-test-framework-")) continue;
      try (JarFile input = new JarFile(jar)) {
        Enumeration<JarEntry> entries = input.entries();
        while (entries.hasMoreElements()) {
          String resource = entries.nextElement().getName();
          if (resource.startsWith("org/apache/solr/") && resource.endsWith(".class"))
            production.add(resource.substring(0, resource.length() - 6));
        }
      }
    }
    ExecFileLoader loader = new ExecFileLoader();
    loader.load(new File(args[1]));
    for (ExecutionData data : loader.getExecutionDataStore().getContents()) {
      if (!production.contains(data.getName())) continue;
      String id = Long.toHexString(data.getId());
      boolean[] probes = data.getProbes();
      for (int i = 0; i < probes.length; i++) {
        if (probes[i]) System.out.println(id + "\t" + data.getName() + "\t" + i);
      }
    }
  }
}
