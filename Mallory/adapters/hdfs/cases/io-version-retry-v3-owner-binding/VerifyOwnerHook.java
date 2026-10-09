import edu.uva.liftlab.mallory.adapters.hdfs.HdfsMiniClusterTransformer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.Map;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.util.CheckClassAdapter;

/** Verifies real Hadoop bytecode has exactly the intended startup hooks. */
public final class VerifyOwnerHook {
  private static void verify(String name, Path path) throws Exception {
    byte[] input = Files.readAllBytes(path);
    byte[] output = new HdfsMiniClusterTransformer().transform(
        VerifyOwnerHook.class.getClassLoader(), name, null, null, input);
    if (output == null) throw new AssertionError("not transformed: " + name);
    new ClassReader(output).accept(new CheckClassAdapter(new ClassWriter(0), true),
        ClassReader.EXPAND_FRAMES);
    ClassNode clazz = new ClassNode();
    new ClassReader(output).accept(clazz, 0);
    Map<String, Integer> counts = new HashMap<String, Integer>();
    for (MethodNode method : clazz.methods) {
      for (AbstractInsnNode instruction : method.instructions.toArray()) {
        if (!(instruction instanceof MethodInsnNode)) continue;
        MethodInsnNode call = (MethodInsnNode) instruction;
        if (!call.owner.equals("edu/uva/liftlab/mallory/adapters/hdfs/HdfsHooks")) continue;
        String key = method.name + ":" + call.name;
        counts.put(key, counts.containsKey(key) ? counts.get(key) + 1 : 1);
      }
    }
    if (name.endsWith("/DataNode")) {
      if (counts.getOrDefault("startDataNode:dataNodeBeforeRefresh", 0) != 1)
        throw new AssertionError("missing or duplicate pre-refresh owner hook: " + counts);
    } else {
      if (counts.getOrDefault("startDataNodes:dataNodeConstructionEnter", 0) < 1
          || counts.getOrDefault("restartDataNode:dataNodeConstructionEnter", 0) < 1)
        throw new AssertionError("missing MiniDFSCluster construction scope: " + counts);
    }
    System.out.println(name + " verified " + counts);
  }

  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("DataNode.class MiniDFSCluster.class");
    verify("org/apache/hadoop/hdfs/server/datanode/DataNode", Paths.get(args[0]));
    verify("org/apache/hadoop/hdfs/MiniDFSCluster", Paths.get(args[1]));
  }
}
