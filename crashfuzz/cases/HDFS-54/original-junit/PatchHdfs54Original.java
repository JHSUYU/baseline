import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.HashSet;
import java.util.Set;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.FieldInsnNode;
import org.objectweb.asm.tree.InsnList;
import org.objectweb.asm.tree.InsnNode;
import org.objectweb.asm.tree.JumpInsnNode;
import org.objectweb.asm.tree.LdcInsnNode;
import org.objectweb.asm.tree.LineNumberNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.VarInsnNode;

/** Add exact line-629 target and four application-level native checksum I/O hooks. */
public final class PatchHdfs54Original implements Opcodes {
  private static final String TARGET =
      "org/apache/hadoop/hdfs/FileChecksumHelper$StripedFileNonStripedChecksumComputer";

  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("input class, overlay root");
    ClassNode node = new ClassNode();
    new ClassReader(Files.readAllBytes(Paths.get(args[0]))).accept(node, 0);
    if (!TARGET.equals(node.name)) throw new IllegalArgumentException("wrong class");
    int targets = 0, catches = 0, enters = 0, points = 0;
    for (MethodNode method : node.methods) {
      if (method.name.equals("tryDatanode")) {
        InsnList enter = new InsnList();
        enter.add(new VarInsnNode(ALOAD, 0));
        enter.add(new MethodInsnNode(INVOKEVIRTUAL, TARGET, "getSrc",
            "()Ljava/lang/String;", false));
        enter.add(new VarInsnNode(ALOAD, 1));
        enter.add(new VarInsnNode(ALOAD, 3));
        enter.add(new VarInsnNode(ALOAD, 0));
        enter.add(new FieldInsnNode(GETFIELD, TARGET, "bgIdx", "I"));
        enter.add(new MethodInsnNode(INVOKESTATIC, "Hdfs54OriginalProbe", "enterRpc",
            "(Ljava/lang/String;Ljava/lang/Object;Ljava/lang/Object;I)V", false));
        method.instructions.insertBefore(method.instructions.getFirst(), enter);
        enters++;
        Set<Integer> hooked = new HashSet<>();
        for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; ) {
          AbstractInsnNode next = insn.getNext();
          if (insn instanceof LineNumberNode) {
            int line = ((LineNumberNode) insn).line;
            String site = line == 686 ? "CONNECT_L686" : line == 693 ? "SEND_L693"
                : line == 699 ? "RECV_L699" : line == 704 ? "STATUS_L704" : null;
            if (site != null && hooked.add(line)) {
              InsnList hook = new InsnList();
              hook.add(new LdcInsnNode(site));
              hook.add(new MethodInsnNode(INVOKESTATIC, "Hdfs54OriginalProbe", "point",
                  "(Ljava/lang/String;)V", false));
              method.instructions.insert(insn, hook);
              points++;
            }
          }
          insn = next;
        }
      }
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
            hook.add(new MethodInsnNode(INVOKESTATIC, "Hdfs54OriginalProbe", "target",
                "(ZLjava/lang/String;)V", false));
            method.instructions.insertBefore(insn, hook);
            targets++;
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
            hook.add(new MethodInsnNode(INVOKESTATIC, "Hdfs54OriginalProbe", "caught",
                "(Ljava/lang/Throwable;Ljava/lang/String;)V", false));
            method.instructions.insertBefore(insn, hook);
            catches++;
          }
          insn = next;
        }
      }
    }
    if (enters != 1 || points != 4 || targets != 1 || catches != 1) {
      throw new IllegalStateException("released bytecode changed: enter=" + enters
          + " points=" + points + " target=" + targets + " catch=" + catches);
    }
    ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
    node.accept(writer);
    Path output = Paths.get(args[1], node.name + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(output);
  }
}
