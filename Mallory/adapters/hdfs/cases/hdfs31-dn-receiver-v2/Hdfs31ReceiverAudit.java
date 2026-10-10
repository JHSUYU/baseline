import edu.uva.liftlab.mallory.adapters.hdfs.HdfsHooks;
import edu.uva.liftlab.mallory.adapters.hdfs.HdfsMiniClusterTransformer;
import edu.uva.liftlab.mallory.instrumentation.Probe;
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
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.TryCatchBlockNode;
import org.objectweb.asm.util.CheckClassAdapter;

/** No MiniCluster startup: verify the real DataNode bytes and receiver scope. */
public final class Hdfs31ReceiverAudit {
  private static final String TARGET =
      "(Lorg/apache/hadoop/hdfs/protocol/ExtendedBlock;)"
      + "Lorg/apache/hadoop/hdfs/server/datanode/BPOfferService;";
  private static final String HOOKS =
      "edu/uva/liftlab/mallory/adapters/hdfs/HdfsHooks";
  private static final String PROBE =
      "edu/uva/liftlab/mallory/instrumentation/Probe$NodeScope";

  private static void require(boolean condition, String detail) {
    if (!condition) throw new AssertionError(detail);
  }

  private static boolean isClose(AbstractInsnNode node) {
    if (!(node instanceof MethodInsnNode)) return false;
    MethodInsnNode call = (MethodInsnNode) node;
    return call.owner.equals(PROBE) && call.name.equals("close")
        && call.desc.equals("()V");
  }

  private static void auditBytes(Path hadoopRoot, Path distribution) throws Exception {
    Path file = hadoopRoot.resolve("hadoop-hdfs-project/hadoop-hdfs/target/classes/"
        + "org/apache/hadoop/hdfs/server/datanode/DataNode.class");
    byte[] original = Files.readAllBytes(file);
    byte[] patched = new HdfsMiniClusterTransformer().transform(null,
        "org/apache/hadoop/hdfs/server/datanode/DataNode", null, null, original);
    require(patched != null, "DataNode was not transformed");
    ClassNode node = new ClassNode();
    new ClassReader(patched).accept(node, 0);
    MethodNode selected = null;
    for (MethodNode method : node.methods) {
      if (method.name.equals("getBPOSForBlock") && method.desc.equals(TARGET)) {
        selected = method;
        break;
      }
    }
    require(selected != null, "exact getBPOSForBlock overload missing");

    int enterHooks = 0;
    int normalReturns = 0;
    int closes = 0;
    int exceptionalRethrows = 0;
    for (AbstractInsnNode instruction : selected.instructions.toArray()) {
      if (instruction instanceof MethodInsnNode) {
        MethodInsnNode call = (MethodInsnNode) instruction;
        if (call.owner.equals(HOOKS) && call.name.equals("dataNodeReceiverEnter")) {
          enterHooks++;
          require(instruction.getPrevious().getOpcode() == Opcodes.ALOAD,
              "hook must consume the concrete this receiver");
        }
        if (isClose(instruction)) closes++;
      }
      if (instruction.getOpcode() == Opcodes.ARETURN) {
        normalReturns++;
        require(isClose(instruction.getPrevious()),
            "normal return must close the DataNode actor scope");
      }
      if (instruction.getOpcode() == Opcodes.ATHROW
          && isClose(instruction.getPrevious().getPrevious())) exceptionalRethrows++;
    }
    require(enterHooks == 1, "expected one receiver scope entry");
    require(normalReturns >= 1 && closes >= normalReturns + 1,
        "normal and exceptional scope exits missing");
    require(exceptionalRethrows >= 1, "exception handler must close and rethrow");
    boolean catchesThrowable = false;
    for (TryCatchBlockNode block : selected.tryCatchBlocks) {
      if ("java/lang/Throwable".equals(block.type)) catchesThrowable = true;
    }
    require(catchesThrowable, "exception-safe scope handler missing");

    List<URL> urls = new ArrayList<>();
    urls.add(hadoopRoot.resolve("hadoop-hdfs-project/hadoop-hdfs/target/classes")
        .toUri().toURL());
    urls.add(hadoopRoot.resolve("hadoop-hdfs-project/hadoop-hdfs/target/test-classes")
        .toUri().toURL());
    try (Stream<Path> jars = Files.walk(distribution.resolve("share/hadoop"))) {
      jars.filter(path -> path.toString().endsWith(".jar")).forEach(path -> {
        try { urls.add(path.toUri().toURL()); }
        catch (Exception failure) { throw new RuntimeException(failure); }
      });
    }
    try (URLClassLoader loader = new URLClassLoader(
        urls.toArray(new URL[0]), ClassLoader.getSystemClassLoader())) {
      StringWriter errors = new StringWriter();
      CheckClassAdapter.verify(new ClassReader(patched), loader, false,
          new PrintWriter(errors));
      require(errors.toString().isEmpty(), "ASM verifier: " + errors);
    }
    System.out.println("PASS exact DataNode getBPOSForBlock transform and exception-safe exits");
  }

  private static void auditScope() {
    Object registeredDataNode = new Object();
    Probe.setNode("hdfs-client", 0);
    Probe.registerNode(registeredDataNode, "hdfs-cluster-1/dn0", 4);
    try (Probe.NodeScope scope = HdfsHooks.dataNodeReceiverEnter(registeredDataNode)) {
      require(Probe.currentNode().equals("hdfs-cluster-1/dn0")
          && Probe.currentEpoch() == 4, "registered receiver not selected");
    }
    require(Probe.currentNode().equals("hdfs-client") && Probe.currentEpoch() == 0,
        "normal exit did not restore caller");
    try {
      try (Probe.NodeScope scope = HdfsHooks.dataNodeReceiverEnter(registeredDataNode)) {
        require(Probe.currentNode().equals("hdfs-cluster-1/dn0"),
            "exception path lost receiver");
        throw new IllegalStateException("scope-exit-marker");
      }
    } catch (IllegalStateException expected) {
      require(expected.getMessage().equals("scope-exit-marker"),
          "exception changed by scope close");
    }
    require(Probe.currentNode().equals("hdfs-client") && Probe.currentEpoch() == 0,
        "exceptional exit did not restore caller");
    System.out.println("PASS registered receiver and caller restoration on normal/throw paths");
  }

  public static void main(String[] args) throws Exception {
    require(args.length == 2, "usage: Hdfs31ReceiverAudit HADOOP_BUILD HADOOP_DIST");
    auditBytes(Paths.get(args[0]), Paths.get(args[1]));
    auditScope();
  }
}
