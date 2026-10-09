package baseline.solr05;

import java.io.File;
import java.util.Enumeration;
import java.util.HashSet;
import java.util.Set;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import org.jacoco.core.data.ExecutionData;
import org.jacoco.core.tools.ExecFileLoader;

/** Export stable covered Solr production probe IDs from a JaCoCo run. */
public final class CoverageProbes {
  public static void main(String[] args) throws Exception {
    if (args.length < 1 || args.length > 2)
      throw new IllegalArgumentException("jacoco.exec [dist-directory]");
    String dist = args.length == 2 ? args[1] : "/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist";
    Set<String> production = new HashSet<>();
    File[] jars = new File(dist).listFiles();
    if (jars == null) throw new IllegalArgumentException("Missing Solr dist directory");
    for (File jar : jars) {
      String fileName = jar.getName();
      if (!fileName.endsWith(".jar") || fileName.startsWith("solr-test-framework-")) continue;
      try (JarFile input = new JarFile(jar)) {
        Enumeration<JarEntry> entries = input.entries();
        while (entries.hasMoreElements()) {
          String name = entries.nextElement().getName();
          if (name.endsWith(".class") && name.startsWith("org/apache/solr/"))
            production.add(name.substring(0, name.length() - 6));
        }
      }
    }
    ExecFileLoader loader = new ExecFileLoader();
    loader.load(new File(args[0]));
    for (ExecutionData data : loader.getExecutionDataStore().getContents()) {
      String name = data.getName();
      if (!production.contains(name)) continue;
      String id = Long.toHexString(data.getId());
      boolean[] probes = data.getProbes();
      for (int i = 0; i < probes.length; i++) {
        if (probes[i]) System.out.println(id + "\t" + name + "\t" + i);
      }
    }
  }
}
