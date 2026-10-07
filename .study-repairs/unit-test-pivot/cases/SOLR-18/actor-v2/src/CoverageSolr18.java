package research.solr18;

import java.io.File;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import org.jacoco.core.analysis.Analyzer;
import org.jacoco.core.analysis.CoverageBuilder;
import org.jacoco.core.analysis.IClassCoverage;
import org.jacoco.core.analysis.ICounter;
import org.jacoco.core.analysis.IMethodCoverage;
import org.jacoco.core.data.ExecutionData;
import org.jacoco.core.tools.ExecFileLoader;

/** Stable production Solr probe, method, and line coverage for campaign feedback. */
public final class CoverageSolr18 {
  public static void main(String[] args) throws Exception {
    if (args.length != 4) throw new IllegalArgumentException("jacoco.exec overlay solrj.jar solr-core.jar");
    Path exec = Paths.get(args[0]);
    Path output = exec.getParent();
    ExecFileLoader loader = new ExecFileLoader();
    loader.load(new File(args[0]));
    List<String> probes = new ArrayList<>();
    List<String> methods = new ArrayList<>();
    List<String> lines = new ArrayList<>();
    try (ZipFile solrj = new ZipFile(args[2]); ZipFile core = new ZipFile(args[3])) {
      for (ExecutionData data : loader.getExecutionDataStore().getContents()) {
        String name = data.getName();
        if (!name.startsWith("org/apache/solr/") || name.contains("$MockitoMock$")) continue;
        ZipEntry solrjEntry = solrj.getEntry(name + ".class");
        ZipEntry coreEntry = core.getEntry(name + ".class");
        if (solrjEntry == null && coreEntry == null) continue;
        boolean[] bits = data.getProbes();
        for (int i = 0; i < bits.length; i++) if (bits[i]) probes.add(name + "#" + i);
        byte[] bytes;
        Path patched = Paths.get(args[1], name + ".class");
        if (Files.isRegularFile(patched)) bytes = Files.readAllBytes(patched);
        else {
          ZipFile jar = solrjEntry != null ? solrj : core;
          ZipEntry entry = solrjEntry != null ? solrjEntry : coreEntry;
          bytes = new byte[(int) entry.getSize()];
          try (InputStream input = jar.getInputStream(entry)) {
            int offset = 0, count;
            while (offset < bytes.length && (count = input.read(bytes, offset, bytes.length - offset)) > 0)
              offset += count;
          }
        }
        try {
          CoverageBuilder builder = new CoverageBuilder();
          new Analyzer(loader.getExecutionDataStore(), builder).analyzeClass(bytes, name);
          for (IClassCoverage coverage : builder.getClasses()) {
            for (IMethodCoverage method : coverage.getMethods()) {
              if (method.getInstructionCounter().getCoveredCount() == 0) continue;
              methods.add(name + "#" + method.getName() + method.getDesc());
              if (method.getFirstLine() >= 0) {
                for (int line = method.getFirstLine(); line <= method.getLastLine(); line++) {
                  int status = method.getLine(line).getStatus();
                  if (status != ICounter.NOT_COVERED && status != ICounter.EMPTY)
                    lines.add(name + ":" + line);
                }
              }
            }
          }
        } catch (IllegalStateException ignored) { /* dependency class mismatch */ }
      }
    }
    Collections.sort(probes);
    Collections.sort(methods);
    Collections.sort(lines);
    Files.write(output.resolve("covered_probes.txt"), probes);
    Files.write(output.resolve("covered_methods.txt"), methods);
    Files.write(output.resolve("covered_lines.txt"), lines);
  }
}
