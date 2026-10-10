import edu.uva.liftlab.mallory.adapters.hdfs.HdfsMiniClusterTransformer;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

/** Transform the actual pinned Hadoop class files without starting Hadoop. */
public final class VerifyHdfs14Overlay {
  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("classes test-classes");
    Path classes = Paths.get(args[0]);
    Path tests = Paths.get(args[1]);
    String[] names = {
      "org/apache/hadoop/hdfs/MiniDFSCluster",
      "org/apache/hadoop/hdfs/server/datanode/DataNode",
      "org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager",
      "org/apache/hadoop/hdfs/server/datanode/BPServiceActor"
    };
    try (URLClassLoader loader = new URLClassLoader(
        new URL[] {classes.toUri().toURL(), tests.toUri().toURL()},
        VerifyHdfs14Overlay.class.getClassLoader())) {
      HdfsMiniClusterTransformer transformer = new HdfsMiniClusterTransformer();
      for (String name : names) {
        Path source = (name.endsWith("MiniDFSCluster") ? tests : classes)
            .resolve(name + ".class");
        byte[] original = Files.readAllBytes(source);
        byte[] rewritten = transformer.transform(loader, name, null, null, original);
        if (rewritten == null || rewritten.length <= original.length)
          throw new IllegalStateException("missing expected HDFS-14 hook: " + name);
        System.out.println(name + " " + original.length + " -> " + rewritten.length);
      }
    }
  }
}
