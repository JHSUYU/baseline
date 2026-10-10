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
import org.objectweb.asm.tree.LineNumberNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.VarInsnNode;

/** Trace the exact released 3.4.3 striped checksum check and generic catch. */
public final class PatchStripedCheck implements Opcodes {
  private static final String TARGET =
      "org/apache/hadoop/hdfs/FileChecksumHelper$StripedFileNonStripedChecksumComputer";

  public static void main(String[] args) throws Exception {
    if (args.length != 2 && args.length != 3) {
      throw new IllegalArgumentException("input class, overlay root [allow missing catch]");
    }
    ClassNode node = new ClassNode();
    new ClassReader(Files.readAllBytes(Paths.get(args[0]))).accept(node, 0);
    if (!TARGET.equals(node.name)) throw new IllegalArgumentException("wrong class " + node.name);
    int checks = 0, genericCatches = 0;
    for (MethodNode method : node.methods) {
      if (method.name.equals("checksumBlocks") && method.desc.equals("()V")) {
        int line = -1;
        for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; ) {
          AbstractInsnNode next = insn.getNext();
          if (insn instanceof LineNumberNode) line = ((LineNumberNode) insn).line;
          if (line == 629 && insn instanceof JumpInsnNode
              && (insn.getOpcode() == IFNE || insn.getOpcode() == IFEQ)) {
            InsnList hook = new InsnList();
            hook.add(new InsnNode(DUP));
            hook.add(new VarInsnNode(ALOAD, 0));
            hook.add(new MethodInsnNode(INVOKEVIRTUAL, TARGET, "getSrc",
                "()Ljava/lang/String;", false));
            hook.add(new MethodInsnNode(INVOKESTATIC, "Hdfs11Probe", "stripedCheck",
                "(ZLjava/lang/String;)V", false));
            method.instructions.insertBefore(insn, hook);
            checks++;
          }
          insn = next;
        }
      }
      if (method.name.equals("checksumBlockGroup")) {
        int line = -1;
        for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; ) {
          AbstractInsnNode next = insn.getNext();
          if (insn instanceof LineNumberNode) line = ((LineNumberNode) insn).line;
          if (line == 669 && insn instanceof VarInsnNode
              && insn.getOpcode() == ASTORE) {
            InsnList hook = new InsnList();
            hook.add(new InsnNode(DUP));
            hook.add(new VarInsnNode(ALOAD, 0));
            hook.add(new MethodInsnNode(INVOKEVIRTUAL, TARGET, "getSrc",
                "()Ljava/lang/String;", false));
            hook.add(new MethodInsnNode(INVOKESTATIC, "Hdfs11Probe", "stripedError",
                "(Ljava/lang/Throwable;Ljava/lang/String;)V", false));
            method.instructions.insertBefore(insn, hook);
            genericCatches++;
          }
          insn = next;
        }
      }
    }
    if (checks != 1 || (args.length == 2 && genericCatches != 1)) {
      throw new IllegalStateException("released check/catch changed: "
          + checks + "/" + genericCatches);
    }
    ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
    node.accept(writer);
    Path output = Paths.get(args[1], node.name + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(output);
  }
}
