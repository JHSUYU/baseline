import edu.uva.liftlab.mallory.adapters.hdfs.HdfsMiniClusterTransformer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

/** Offline classfile probe; this does not load or run Hadoop. */
public final class TransformOne {
  public static void main(String[] args) throws Exception {
    if (args.length != 3) throw new IllegalArgumentException("class name, input, output required");
    byte[] original = Files.readAllBytes(Paths.get(args[1]));
    byte[] transformed = new HdfsMiniClusterTransformer().transform(
        null, args[0], null, null, original);
    if (transformed == null) throw new IllegalStateException("Adapter did not transform " + args[0]);
    Path output = Paths.get(args[2]);
    Files.createDirectories(output.getParent());
    Files.write(output, transformed);
  }
}
