package research.solrsubshard;

import java.io.File;
import java.io.InputStream;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import org.jacoco.core.data.ExecutionData;
import org.jacoco.core.internal.data.CRC64;
import org.jacoco.core.tools.ExecFileLoader;

/** Offline probe union with exact class IDs from the original release JARs. */
public final class ProbeUnionAudit {
  private ProbeUnionAudit() {}

  public static void main(String[] args) throws Exception {
    int marker = -1;
    for (int index = 0; index < args.length; index++) {
      if ("--jars".equals(args[index])) { marker = index; break; }
    }
    if (marker < 1 || marker == args.length - 1)
      throw new IllegalArgumentException("exec files --jars original release jars required");
    ExecFileLoader loader = new ExecFileLoader();
    for (int index = 0; index < marker; index++) loader.load(new File(args[index]));
    Map<String, Long> releaseIds = new HashMap<>();
    for (int index = marker + 1; index < args.length; index++) {
      try (ZipFile jar = new ZipFile(new File(args[index]))) {
        Enumeration<? extends ZipEntry> entries = jar.entries();
        while (entries.hasMoreElements()) {
          ZipEntry entry = entries.nextElement();
          if (!entry.getName().endsWith(".class")) continue;
          String name = entry.getName().substring(0, entry.getName().length() - 6);
          if (!name.startsWith("org/apache/solr/")
              && !name.startsWith("org/apache/lucene/")) continue;
          try (InputStream input = jar.getInputStream(entry)) {
            byte[] bytes = new byte[(int) entry.getSize()];
            int read = 0;
            while (read < bytes.length) {
              int count = input.read(bytes, read, bytes.length - read);
              if (count < 0) throw new IllegalStateException("short class read " + name);
              read += count;
            }
            releaseIds.put(name, CRC64.classId(bytes));
          }
        }
      }
    }
    for (ExecutionData data : loader.getExecutionDataStore().getContents()) {
      String name = data.getName();
      if (!name.startsWith("org/apache/solr/")
          && !name.startsWith("org/apache/lucene/")) continue;
      Long releaseId = releaseIds.get(name);
      boolean exactReleaseClass = releaseId != null && releaseId == data.getId();
      boolean[] probes = data.getProbes();
      for (int index = 0; index < probes.length; index++) {
        if (probes[index]) System.out.println("P\t" + Long.toHexString(data.getId())
            + "\t" + name + "\t" + index + "\t" + exactReleaseClass);
      }
    }
  }
}
