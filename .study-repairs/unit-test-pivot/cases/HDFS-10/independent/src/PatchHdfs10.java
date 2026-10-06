import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.FieldInsnNode;
import org.objectweb.asm.tree.InsnList;
import org.objectweb.asm.tree.InsnNode;
import org.objectweb.asm.tree.JumpInsnNode;
import org.objectweb.asm.tree.LineNumberNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.VarInsnNode;

/** Case-local hooks for the original writer-epoch guard and observed I/O. */
public final class PatchHdfs10 implements Opcodes {
  private static final String PROBE = "Hdfs10Probe";
  private static final String JOURNAL = "org/apache/hadoop/hdfs/qjournal/server/Journal";
  private static final String FILE = "org/apache/hadoop/hdfs/util/PersistentLongFile";
  private static final String RPC = "org/apache/hadoop/ipc/Client";

  private static MethodInsnNode call(String name, String desc) {
    return new MethodInsnNode(INVOKESTATIC, PROBE, name, desc, false);
  }

  private static int journal(MethodNode method) {
    int checks = 0, throwsFound = 0, returns = 0, line = -1;
    for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; ) {
      AbstractInsnNode next = insn.getNext();
      if (insn instanceof LineNumberNode) line = ((LineNumberNode) insn).line;
      if (insn instanceof JumpInsnNode && insn.getOpcode() == IFEQ && line == 517) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(new VarInsnNode(ALOAD, 1));
        hook.add(call("targetCheck", "(ILorg/apache/hadoop/hdfs/qjournal/protocol/RequestInfo;)V"));
        method.instructions.insertBefore(insn, hook);
        checks++;
      }
      if (insn.getOpcode() == ATHROW && line == 520) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(call("targetThrow", "(Ljava/lang/Throwable;)V"));
        method.instructions.insertBefore(insn, hook);
        throwsFound++;
      }
      if (insn.getOpcode() == RETURN && line == 522) {
        method.instructions.insertBefore(insn, call("targetReturn", "()V"));
        returns++;
      }
      insn = next;
    }
    if (checks != 1 || throwsFound != 1 || returns != 1)
      throw new IllegalStateException("writer epoch check/throw/return="
          + checks + "/" + throwsFound + "/" + returns);
    return checks + throwsFound + returns;
  }

  private static int file(MethodNode method) {
    int patched = 0;
    for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; insn = insn.getNext()) {
      if (!(insn instanceof MethodInsnNode)) continue;
      MethodInsnNode site = (MethodInsnNode) insn;
      if (!site.owner.equals(FILE) || !site.name.equals("writeFile")
          || !site.desc.equals("(Ljava/io/File;J)V")) continue;
      InsnList hook = new InsnList();
      hook.add(new VarInsnNode(ALOAD, 0));
      hook.add(new FieldInsnNode(GETFIELD, FILE, "file", "Ljava/io/File;"));
      hook.add(call("writerEpochWrite", "(Ljava/io/File;)V"));
      method.instructions.insertBefore(site, hook);
      patched++;
    }
    if (patched != 1) throw new IllegalStateException("PersistentLongFile write hooks=" + patched);
    return patched;
  }

  public static void main(String[] args) throws Exception {
    if (args.length != 3) throw new IllegalArgumentException("input.class className outDir");
    ClassNode node = new ClassNode();
    new ClassReader(Files.readAllBytes(Paths.get(args[0]))).accept(node, 0);
    if (!node.name.equals(args[1])) throw new IllegalArgumentException("class name mismatch");
    int count = 0;
    for (MethodNode method : node.methods) {
      if (node.name.equals(JOURNAL) && method.name.equals("checkWriteRequest")
          && method.desc.equals("(Lorg/apache/hadoop/hdfs/qjournal/protocol/RequestInfo;)V")) count += journal(method);
      if (node.name.equals(FILE) && method.name.equals("set") && method.desc.equals("(J)V")) count += file(method);
      if (node.name.equals(RPC) && method.name.equals("getRpcResponse")) {
        method.instructions.insert(call("ipcResponse", "()V"));
        count++;
      }
    }
    int expected = node.name.equals(JOURNAL) ? 3 : 1;
    if (count != expected) throw new IllegalStateException(node.name + " hooks=" + count);
    ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
    node.accept(writer);
    Path output = Paths.get(args[2], node.name + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(output);
  }
}
