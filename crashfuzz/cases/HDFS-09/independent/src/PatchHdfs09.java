import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.FieldInsnNode;
import org.objectweb.asm.tree.FrameNode;
import org.objectweb.asm.tree.InsnList;
import org.objectweb.asm.tree.InsnNode;
import org.objectweb.asm.tree.LabelNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.TryCatchBlockNode;
import org.objectweb.asm.tree.VarInsnNode;

/** Patch only original Hadoop 3.4.3 bytecode, with verified exact sites. */
public final class PatchHdfs09 implements Opcodes {
  private static final String PROBE = "Hdfs09Probe";
  private static final String JOURNAL = "org/apache/hadoop/hdfs/qjournal/server/Journal";
  private static final String FILE = "org/apache/hadoop/hdfs/util/BestEffortLongFile";
  private static final String RPC = "org/apache/hadoop/ipc/Client";

  private static MethodInsnNode call(String name, String desc) {
    return new MethodInsnNode(INVOKESTATIC, PROBE, name, desc, false);
  }

  private static int journal(MethodNode method) {
    int patched = 0;
    for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; insn = insn.getNext()) {
      if (!(insn instanceof MethodInsnNode)) continue;
      MethodInsnNode site = (MethodInsnNode) insn;
      if (!site.owner.equals("org/apache/hadoop/util/Preconditions")
          || !site.name.equals("checkArgument")
          || !site.desc.equals("(ZLjava/lang/Object;)V")) continue;
      InsnList before = new InsnList();
      before.add(new InsnNode(DUP2));
      before.add(new VarInsnNode(ALOAD, 1));
      before.add(call("targetCheck", "(ZLjava/lang/Object;Lorg/apache/hadoop/hdfs/qjournal/protocol/RequestInfo;)V"));
      LabelNode start = new LabelNode();
      before.add(start);
      method.instructions.insertBefore(site, before);

      LabelNode end = new LabelNode();
      InsnList after = new InsnList();
      after.add(end);
      after.add(call("targetReturn", "()V"));
      method.instructions.insert(site, after);

      LabelNode handler = new LabelNode();
      InsnList catchBlock = new InsnList();
      catchBlock.add(handler);
      catchBlock.add(new FrameNode(F_FULL, 2, new Object[]{JOURNAL,
          "org/apache/hadoop/hdfs/qjournal/protocol/RequestInfo"}, 1,
          new Object[]{"java/lang/IllegalArgumentException"}));
      catchBlock.add(new InsnNode(DUP));
      catchBlock.add(call("targetThrow", "(Ljava/lang/Throwable;)V"));
      catchBlock.add(new InsnNode(ATHROW));
      method.instructions.add(catchBlock);
      method.tryCatchBlocks.add(new TryCatchBlockNode(start, end, handler,
          "java/lang/IllegalArgumentException"));
      patched++;
    }
    if (patched != 1) throw new IllegalStateException("Journal exact check hooks=" + patched);
    return patched;
  }

  private static int file(MethodNode method) {
    int patched = 0;
    for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; insn = insn.getNext()) {
      if (!(insn instanceof MethodInsnNode)) continue;
      MethodInsnNode site = (MethodInsnNode) insn;
      if (!site.owner.equals("org/apache/hadoop/io/IOUtils") || !site.name.equals("writeFully")
          || !site.desc.equals("(Ljava/nio/channels/FileChannel;Ljava/nio/ByteBuffer;J)V")) continue;
      InsnList hook = new InsnList();
      hook.add(new VarInsnNode(ALOAD, 0));
      hook.add(new FieldInsnNode(GETFIELD, FILE, "file", "Ljava/io/File;"));
      hook.add(call("committedWrite", "(Ljava/io/File;)V"));
      method.instructions.insertBefore(site, hook);
      patched++;
    }
    if (patched != 1) throw new IllegalStateException("BestEffortLongFile write hooks=" + patched);
    return patched;
  }

  private static int rpc(MethodNode method) {
    method.instructions.insert(call("ipcResponse", "()V"));
    return 1;
  }

  public static void main(String[] args) throws Exception {
    if (args.length != 3) throw new IllegalArgumentException("input.class className outDir");
    ClassNode node = new ClassNode();
    new ClassReader(Files.readAllBytes(Paths.get(args[0]))).accept(node, 0);
    if (!node.name.equals(args[1])) throw new IllegalArgumentException("class name mismatch");
    int count = 0;
    for (MethodNode method : node.methods) {
      if (node.name.equals(JOURNAL) && method.name.equals("checkRequest")
          && method.desc.equals("(Lorg/apache/hadoop/hdfs/qjournal/protocol/RequestInfo;)V")) count += journal(method);
      if (node.name.equals(FILE) && method.name.equals("set") && method.desc.equals("(J)V")) count += file(method);
      if (node.name.equals(RPC) && method.name.equals("getRpcResponse")) count += rpc(method);
    }
    if (count != 1) throw new IllegalStateException(node.name + " hooks=" + count);
    ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
    node.accept(writer);
    Path output = Paths.get(args[2], node.name + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(output);
  }
}
