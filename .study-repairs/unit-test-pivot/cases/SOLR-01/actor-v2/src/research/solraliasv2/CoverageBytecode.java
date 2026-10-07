package research.solraliasv2;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;

/** Reconstruct the exact production bytecode seen by JaCoCo after our agent. */
public final class CoverageBytecode {
  private CoverageBytecode() {}

  public static void main(String[] args) throws IOException {
    if (args.length != 2) throw new IllegalArgumentException("dist-dir output-dir");
    Path dist = Paths.get(args[0]);
    Path output = Paths.get(args[1]);
    // Probe.initialize loads CloudHttp2SolrClient (and its BaseCloud parent)
    // before the transformer is registered. The absent REQUEST_ENTER events
    // confirm BaseCloud was not woven in the actual JVM; analyze its original
    // Solr JAR bytecode. BASE and JETTY are transformed later.
    for (String name : new String[] {Agent.BASE, Agent.JETTY}) {
      String resource = name + ".class";
      String jarName = name.equals(Agent.JETTY)
          ? "solr-core-8.11.4.jar" : "solr-solrj-8.11.4.jar";
      try (JarFile jar = new JarFile(dist.resolve(jarName).toFile())) {
        JarEntry entry = jar.getJarEntry(resource);
        if (entry == null) throw new IllegalArgumentException(jarName + " lacks " + resource);
        byte[] original = new byte[(int) entry.getSize()];
        try (java.io.InputStream stream = jar.getInputStream(entry)) {
          int offset = 0;
          while (offset < original.length) {
            int count = stream.read(original, offset, original.length - offset);
            if (count < 0) throw new IOException("short read: " + resource);
            offset += count;
          }
        }
        byte[] transformed = Agent.weave(name, original);
        if (transformed == null) throw new IllegalStateException("no hooks: " + name);
        Path target = output.resolve(resource);
        Files.createDirectories(target.getParent());
        Files.write(target, transformed);
        System.out.println(name + " " + transformed.length);
      }
    }
  }
}
