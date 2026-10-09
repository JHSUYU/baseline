import edu.uva.liftlab.mallory.adapters.hdfs.HdfsMiniClusterTransformer;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

/** Transform pinned real HDFS classfiles without loading or starting Hadoop. */
public final class VerifyOverlay {
  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("classes-root output-root");
    Path classes = Paths.get(args[0]);
    Path output = Paths.get(args[1]);
    String[] names = {
      "org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager",
      "org/apache/hadoop/hdfs/server/datanode/BPServiceActor",
      "org/apache/hadoop/hdfs/server/datanode/BPOfferService",
      "org/apache/hadoop/hdfs/server/datanode/BPServiceActor$CommandProcessingThread"
    };
    try (URLClassLoader loader = new URLClassLoader(new URL[] {classes.toUri().toURL()},
                                                  VerifyOverlay.class.getClassLoader())) {
      HdfsMiniClusterTransformer transformer = new HdfsMiniClusterTransformer();
      for (String name : names) {
        Path original = classes.resolve(name + ".class");
        byte[] bytes = Files.readAllBytes(original);
        byte[] rewritten = transformer.transform(loader, name, null, null, bytes);
        if (rewritten == null || rewritten.length == 0)
          throw new IllegalStateException("not transformed: " + name);
        Path target = output.resolve(name + ".class");
        Files.createDirectories(target.getParent());
        Files.write(target, rewritten);
        System.out.println(name + " " + bytes.length + " -> " + rewritten.length);
      }
    }
  }
}
