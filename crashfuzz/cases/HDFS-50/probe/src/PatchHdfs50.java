import java.io.IOException;
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
import org.objectweb.asm.tree.LdcInsnNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.VarInsnNode;

/** Offline bytecode hooks for one original HDFS JUnit, without graph construction. */
public final class PatchHdfs50 implements Opcodes {
  private static final String PROBE = "Hdfs50Probe";
  private static final String TARGET = "org/apache/hadoop/hdfs/server/namenode/snapshot/DirectorySnapshottableFeature";
  private static final String RPC = "org/apache/hadoop/ipc/Client";
  private static final String FILE = "org/apache/hadoop/hdfs/server/namenode/EditLogFileOutputStream";

  private static MethodInsnNode call(String name, String descriptor) {
    return new MethodInsnNode(INVOKESTATIC, PROBE, name, descriptor, false);
  }

  private static void patchTarget(MethodNode method) {
    InsnList begin = new InsnList();
    begin.add(new VarInsnNode(ALOAD, 3));
    begin.add(call("targetEnter", "(Ljava/lang/String;)V"));
    method.instructions.insert(begin);
    for (AbstractInsnNode instruction = method.instructions.getFirst(); instruction != null; ) {
      AbstractInsnNode next = instruction.getNext();
      if (instruction.getOpcode() == IFLT) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(new VarInsnNode(ALOAD, 3));
        hook.add(new InsnNode(SWAP));
        hook.add(call("targetBranch", "(Ljava/lang/String;I)V"));
        method.instructions.insertBefore(instruction, hook);
      } else if (instruction.getOpcode() == ATHROW) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(new VarInsnNode(ALOAD, 3));
        hook.add(call("targetThrow", "(Ljava/lang/Throwable;Ljava/lang/String;)V"));
        method.instructions.insertBefore(instruction, hook);
      } else if (instruction.getOpcode() == ARETURN) {
        InsnList hook = new InsnList();
        hook.add(new VarInsnNode(ALOAD, 3));
        hook.add(call("targetReturn", "(Ljava/lang/String;)V"));
        method.instructions.insertBefore(instruction, hook);
      }
      instruction = next;
    }
  }

  private static void patchIo(MethodNode method, String marker, String site) {
    InsnList hook = new InsnList();
    hook.add(new LdcInsnNode(marker));
    hook.add(new LdcInsnNode(site));
    hook.add(call("io", "(Ljava/lang/String;Ljava/lang/String;)V"));
    method.instructions.insert(hook);
  }

  public static void main(String[] args) throws IOException {
    if (args.length != 3) throw new IllegalArgumentException("input .class, internal name, output directory");
    byte[] bytes = Files.readAllBytes(Paths.get(args[0]));
    ClassNode node = new ClassNode();
    new ClassReader(bytes).accept(node, 0);
    String name = args[1];
    if (!name.equals(node.name)) throw new IllegalArgumentException(name + " != " + node.name);
    int count = 0;
    for (MethodNode method : node.methods) {
      if (name.equals(TARGET) && method.name.equals("addSnapshot")
          && method.desc.contains("Lorg/apache/hadoop/hdfs/server/namenode/snapshot/SnapshotManager;")) {
        patchTarget(method); count++;
      }
      if (name.equals(RPC) && method.name.equals("getRpcResponse")) {
        patchIo(method, "FAULT:HDFS_RPC:RESPONSE", "Client.getRpcResponse"); count++;
      }
      if (name.equals(FILE) && method.name.equals("flushAndSync")) {
        patchIo(method, "FAULT:HDFS_FILE:SYNC", "EditLogFileOutputStream.flushAndSync"); count++;
      }
    }
    if (count != 1) throw new IllegalStateException("Expected one hook, got " + count + " for " + name);
    ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
    node.accept(writer);
    Path output = Paths.get(args[2], name + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(output);
  }
}
