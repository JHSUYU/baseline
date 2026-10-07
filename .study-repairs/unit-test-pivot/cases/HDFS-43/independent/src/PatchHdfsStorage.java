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
import org.objectweb.asm.tree.JumpInsnNode;
import org.objectweb.asm.tree.LdcInsnNode;
import org.objectweb.asm.tree.LineNumberNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.VarInsnNode;

/** Case-local offline ASM hooks in original Hadoop 3.4.3 classes. */
public final class PatchHdfsStorage implements Opcodes {
  private static final String PROBE = "HdfsStorageProbe";
  private static final String TRUNCATE = "org/apache/hadoop/hdfs/server/namenode/FSDirTruncateOp";
  private static final String EDIT_LOG = "org/apache/hadoop/hdfs/server/namenode/FSEditLog";
  private static final String RPC = "org/apache/hadoop/ipc/Client";

  private static MethodInsnNode call(String name, String desc) {
    return new MethodInsnNode(INVOKESTATIC, PROBE, name, desc, false);
  }

  private static int patchTruncate(MethodNode method) {
    int checks = 0, throwsFound = 0, line = -1;
    for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; ) {
      AbstractInsnNode next = insn.getNext();
      if (insn instanceof LineNumberNode) line = ((LineNumberNode) insn).line;
      if (insn instanceof JumpInsnNode && insn.getOpcode() == IFNE && line == 113) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(new VarInsnNode(LLOAD, 2));
        hook.add(new VarInsnNode(LLOAD, 19));
        hook.add(new VarInsnNode(ALOAD, 11));
        hook.add(call("truncateCheck", "(IJJLjava/lang/String;)V"));
        method.instructions.insertBefore(insn, hook);
        checks++;
      }
      if (insn.getOpcode() == ATHROW && line == 117) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(new LdcInsnNode("HDFS-43"));
        hook.add(new InsnNode(SWAP));
        hook.add(call("targetThrow", "(Ljava/lang/String;Ljava/lang/Throwable;)V"));
        method.instructions.insertBefore(insn, hook);
        throwsFound++;
      }
      insn = next;
    }
    if (checks != 1 || throwsFound != 1)
      throw new IllegalStateException("FSDirTruncateOp.truncate hooks=" + checks + "/" + throwsFound);
    return checks + throwsFound;
  }

  public static void main(String[] args) throws Exception {
    if (args.length != 3) throw new IllegalArgumentException("input.class className outDir");
    ClassNode node = new ClassNode();
    new ClassReader(Files.readAllBytes(Paths.get(args[0]))).accept(node, 0);
    if (!node.name.equals(args[1])) throw new IllegalArgumentException("class name mismatch");
    int count = 0;
    for (MethodNode method : node.methods) {
      if (node.name.equals(TRUNCATE) && method.name.equals("truncate")
          && method.desc.equals("(Lorg/apache/hadoop/hdfs/server/namenode/FSNamesystem;"
              + "Ljava/lang/String;JLjava/lang/String;Ljava/lang/String;J"
              + "Lorg/apache/hadoop/hdfs/server/namenode/INode$BlocksMapUpdateInfo;"
              + "Lorg/apache/hadoop/hdfs/server/namenode/FSPermissionChecker;)"
              + "Lorg/apache/hadoop/hdfs/server/namenode/FSDirTruncateOp$TruncateResult;"))
        count += patchTruncate(method);
      if (node.name.equals(EDIT_LOG) && method.name.equals("logSync")
          && method.desc.equals("()V")) {
        method.instructions.insert(call("editLogSync", "()V"));
        count++;
      }
      if (node.name.equals(RPC) && method.name.equals("getRpcResponse")) {
        method.instructions.insert(call("ipcResponse", "()V"));
        count++;
      }
    }
    int expected = node.name.equals(TRUNCATE) ? 2 : 1;
    if (count != expected) throw new IllegalStateException(node.name + " hooks=" + count);
    ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
    node.accept(writer);
    Path output = Paths.get(args[2], node.name + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(output);
  }
}
