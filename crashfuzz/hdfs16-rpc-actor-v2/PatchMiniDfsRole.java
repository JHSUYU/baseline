import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.InsnList;
import org.objectweb.asm.tree.InsnNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;

/** Observe the unchanged JUnit's MiniDFSCluster DN list order at return. */
public final class PatchMiniDfsRole implements Opcodes {
  private static final String OWNER = "org/apache/hadoop/hdfs/MiniDFSCluster";
  private static final String PROBE = "org/apache/hadoop/hdfs/hdfs16independent/Probe";

  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("input.class output.class");
    ClassNode node = new ClassNode();
    new ClassReader(Files.readAllBytes(Paths.get(args[0]))).accept(node, 0);
    if (!OWNER.equals(node.name)) throw new IllegalArgumentException("wrong class");
    int methods = 0;
    int exits = 0;
    for (MethodNode method : node.methods) {
      if (!method.name.equals("getDataNodes") ||
          !method.desc.equals("()Ljava/util/ArrayList;")) continue;
      methods++;
      for (AbstractInsnNode instruction = method.instructions.getFirst();
           instruction != null; instruction = instruction.getNext()) {
        if (instruction.getOpcode() != ARETURN) continue;
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(new MethodInsnNode(INVOKESTATIC, PROBE, "registerRoles",
            "(Ljava/util/List;)V", false));
        method.instructions.insertBefore(instruction, hook);
        exits++;
      }
    }
    if (methods != 1 || exits != 1) {
      throw new IllegalStateException("getDataNodes methods/exits=" + methods + "/" + exits);
    }
    ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
    node.accept(writer);
    Path output = Paths.get(args[1]);
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println("MiniDFSCluster.getDataNodes role hook PASS");
  }
}
