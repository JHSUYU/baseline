import java.io.File;
import java.io.FileOutputStream;
import java.io.PrintStream;
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

/** Enumerate stable JaCoCo probe IDs for feedback across original-JUnit runs. */
public final class CoverageHdfs19 {
  public static void main(String[] args) throws Exception {
    if (args.length != 1 && args.length != 5) throw new IllegalArgumentException("jacoco.exec [overlay hdfs.jar hdfs-client.jar common.jar]");
    ExecFileLoader loader = new ExecFileLoader();
    loader.load(new File(args[0]));
    List<String> covered = new ArrayList<>();
    for (ExecutionData data : loader.getExecutionDataStore().getContents()) {
      if (!(data.getName().startsWith("org/apache/hadoop/hdfs/")
          || data.getName().startsWith("org/apache/hadoop/ipc/"))) continue;
      boolean[] probes = data.getProbes();
      for (int i = 0; i < probes.length; i++) {
        if (probes[i]) covered.add(data.getName() + "#" + i);
      }
    }
    Collections.sort(covered);
    for (String id : covered) System.out.println(id);
    if (args.length == 5) {
      try (ZipFile hdfs = new ZipFile(args[2]); ZipFile client = new ZipFile(args[3]);
           ZipFile common = new ZipFile(args[4])) {
        List<String> methods = new ArrayList<>();
        List<String> branches = new ArrayList<>();
        List<String> lines = new ArrayList<>();
        for (ExecutionData data : loader.getExecutionDataStore().getContents()) {
          String name = data.getName();
          if (!(name.startsWith("org/apache/hadoop/hdfs/") || name.startsWith("org/apache/hadoop/ipc/"))) continue;
          byte[] bytes = null;
          Path overlay = Paths.get(args[1], name + ".class");
          if (Files.isRegularFile(overlay)) bytes = Files.readAllBytes(overlay);
          else {
            for (ZipFile jar : new ZipFile[]{hdfs, client, common}) {
              ZipEntry entry = jar.getEntry(name + ".class");
              if (entry != null) { bytes = new byte[(int) entry.getSize()];
                try (java.io.InputStream input = jar.getInputStream(entry)) {
                  int offset = 0, n;
                  while (offset < bytes.length && (n = input.read(bytes, offset, bytes.length - offset)) > 0) offset += n;
                }
                break;
              }
            }
          }
          if (bytes == null) continue;
          try {
            CoverageBuilder builder = new CoverageBuilder();
            new Analyzer(loader.getExecutionDataStore(), builder).analyzeClass(bytes, name);
            for (IClassCoverage coverage : builder.getClasses()) {
              for (IMethodCoverage method : coverage.getMethods()) {
                if (method.getInstructionCounter().getCoveredCount() == 0) continue;
                String id = name + "#" + method.getName() + method.getDesc();
                methods.add(id);
                for (int i = 0; i < method.getBranchCounter().getCoveredCount(); i++) branches.add(id + "#" + i);
                if (method.getFirstLine() >= 0) {
                  for (int line = method.getFirstLine(); line <= method.getLastLine(); line++) {
                    if (method.getLine(line).getStatus() != ICounter.NOT_COVERED
                        && method.getLine(line).getStatus() != ICounter.EMPTY) lines.add(name + ":" + line);
                  }
                }
              }
            }
          } catch (IllegalStateException ignored) { /* mismatched dependency class */ }
        }
        Collections.sort(methods);
        Collections.sort(branches);
        Collections.sort(lines);
        Path prefix = Paths.get(args[0]).getParent();
        Files.write(prefix.resolve("covered_methods.txt"), methods);
        Files.write(prefix.resolve("covered_branch_counts.txt"), branches);
        Files.write(prefix.resolve("covered_lines.txt"), lines);
      }
    }
  }
}
