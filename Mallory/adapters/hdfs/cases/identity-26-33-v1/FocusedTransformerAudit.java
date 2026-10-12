import edu.uva.liftlab.mallory.adapters.hdfs.HdfsMiniClusterTransformer;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Stream;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.util.CheckClassAdapter;

/** Bytecode-only audit. No Hadoop class is initialized or MiniCluster started. */
public final class FocusedTransformerAudit {
  private static final String HOOKS =
      "edu/uva/liftlab/mallory/adapters/hdfs/HdfsHooks";

  private static void require(boolean value, String message) {
    if (!value) throw new AssertionError(message);
  }

  private static MethodNode method(ClassNode clazz, String name) {
    MethodNode result = null;
    for (MethodNode candidate : clazz.methods) {
      if (!candidate.name.equals(name)) continue;
      if (result == null || candidate.instructions.size() > result.instructions.size())
        result = candidate;
    }
    require(result != null, clazz.name + " lacks " + name);
    return result;
  }

  private static void requireHookBefore(MethodNode method, String callOwner,
                                        String callName, String hookName) {
    boolean found = false;
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (!(instruction instanceof MethodInsnNode)) continue;
      MethodInsnNode call = (MethodInsnNode) instruction;
      if (!call.owner.equals(callOwner) || !call.name.equals(callName)) continue;
      boolean hooked = false;
      for (AbstractInsnNode prior = instruction.getPrevious(); prior != null;
           prior = prior.getPrevious()) {
        if (!(prior instanceof MethodInsnNode)) continue;
        MethodInsnNode previous = (MethodInsnNode) prior;
        if (previous.owner.equals(HOOKS) && previous.name.equals(hookName)) {
          hooked = true;
          break;
        }
        if (previous.owner.equals(callOwner) && previous.name.equals(callName)) break;
      }
      require(hooked, method.name + " lacks " + hookName + " before " + callName
          + " descriptor " + call.desc);
      found = true;
    }
    require(found, method.name + " lacks " + callName);
  }

  private static void requireHook(MethodNode method, String hookName) {
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (!(instruction instanceof MethodInsnNode)) continue;
      MethodInsnNode call = (MethodInsnNode) instruction;
      if (call.owner.equals(HOOKS) && call.name.equals(hookName)) return;
    }
    throw new AssertionError(method.name + " lacks " + hookName);
  }

  private static void audit(ClassLoader loader, Path file, String internal,
                            String method, String hook, String beforeOwner,
                            String beforeCall) throws Exception {
    byte[] original = Files.readAllBytes(file);
    byte[] patched = new HdfsMiniClusterTransformer().transform(
        loader, internal, null, null, original);
    require(patched != null, "no transform for " + internal);
    ClassNode node = new ClassNode();
    new ClassReader(patched).accept(node, 0);
    MethodNode selected = method(node, method);
    if (beforeCall == null) requireHook(selected, hook);
    else requireHookBefore(selected, beforeOwner, beforeCall, hook);
    StringWriter verification = new StringWriter();
    CheckClassAdapter.verify(new ClassReader(patched), loader, false,
        new PrintWriter(verification));
    require(verification.toString().isEmpty(),
        "ASM verification failed for " + internal + ": " + verification);
    System.out.println("PASS " + internal + " " + hook + " ASM-verified");
  }

  public static void main(String[] args) throws Exception {
    require(args.length == 2, "usage: FocusedTransformerAudit HDFS_BUILD_ROOT HADOOP_DIST_ROOT");
    Path build = Paths.get(args[0]);
    Path classes = build.resolve("hadoop-hdfs-project/hadoop-hdfs/target/classes");
    Path tests = build.resolve("hadoop-hdfs-project/hadoop-hdfs/target/test-classes");
    List<URL> urls = new ArrayList<>();
    urls.add(tests.toUri().toURL());
    urls.add(classes.toUri().toURL());
    try (Stream<Path> paths = Files.walk(Paths.get(args[1], "share/hadoop"))) {
      paths.filter(p -> p.toString().endsWith(".jar"))
          .forEach(p -> {
            try { urls.add(p.toUri().toURL()); }
            catch (Exception e) { throw new RuntimeException(e); }
          });
    }
    try (URLClassLoader loader = new URLClassLoader(
        urls.toArray(new URL[0]), ClassLoader.getSystemClassLoader())) {
      audit(loader, tests.resolve("org/apache/hadoop/hdfs/MiniDFSCluster.class"),
          "org/apache/hadoop/hdfs/MiniDFSCluster", "startDataNodes",
          "dataNodeConstructionConfigured",
          "org/apache/hadoop/hdfs/server/datanode/DataNode", "instantiateDataNode");
      audit(loader, classes.resolve("org/apache/hadoop/hdfs/server/datanode/DataNode.class"),
          "org/apache/hadoop/hdfs/server/datanode/DataNode", "startDataNode",
          "dataNodeConstructionReady",
          "org/apache/hadoop/hdfs/server/datanode/BlockPoolManager", "refreshNamenodes");
      audit(loader, tests.resolve("org/apache/hadoop/hdfs/MiniDFSCluster$Builder.class"),
          "org/apache/hadoop/hdfs/MiniDFSCluster$Builder", "build",
          "clusterBuilt", null, null);
      audit(loader, classes.resolve("org/apache/hadoop/hdfs/server/datanode/DataStorage.class"),
          "org/apache/hadoop/hdfs/server/datanode/DataStorage", "getBlockPoolSliceStorage",
          "blockPoolStorageObtained", null, null);
      audit(loader, classes.resolve("org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage.class"),
          "org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage", "doTransition",
          "blockPoolStorageEnter", null, null);
      audit(loader, classes.resolve("org/apache/hadoop/hdfs/server/datanode/DataStorage$VolumeBuilder.class"),
          "org/apache/hadoop/hdfs/server/datanode/DataStorage$VolumeBuilder", "build",
          "volumeBuilderEnter", null, null);
      audit(loader, classes.resolve("org/apache/hadoop/hdfs/server/datanode/BPServiceActor.class"),
          "org/apache/hadoop/hdfs/server/datanode/BPServiceActor", "run",
          "actorEnter", null, null);
    }
  }
}
