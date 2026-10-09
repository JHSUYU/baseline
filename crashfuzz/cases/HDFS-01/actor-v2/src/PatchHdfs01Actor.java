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
import org.objectweb.asm.tree.LdcInsnNode;
import org.objectweb.asm.tree.LineNumberNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.VarInsnNode;

/** Verify the selected target and bind each data read to its live DN. */
public final class PatchHdfs01Actor implements Opcodes {
  private static final String PROBE = "Hdfs01ActorProbe";
  private static final String TARGET = "org/apache/hadoop/hdfs/DFSInputStream";
  private static final String RPC = "org/apache/hadoop/ipc/Client";
  private static final String CLIENT = "org/apache/hadoop/hdfs/DFSClient";
  private static final String READ = "org/apache/hadoop/hdfs/client/impl/BlockReaderRemote";

  private static MethodInsnNode call(String name, String desc) {
    return new MethodInsnNode(INVOKESTATIC, PROBE, name, desc, false);
  }

  private static int target(MethodNode method) {
    int checks = 0, throwsFound = 0, line = -1;
    for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; ) {
      AbstractInsnNode next = insn.getNext();
      if (insn instanceof LineNumberNode) line = ((LineNumberNode) insn).line;
      if (insn instanceof JumpInsnNode && insn.getOpcode() == IFNULL && line == 517) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(new VarInsnNode(LLOAD, 1));
        hook.add(new VarInsnNode(ALOAD, 0));
        hook.add(new FieldInsnNode(GETFIELD, TARGET, "src", "Ljava/lang/String;"));
        hook.add(call("targetCheck", "(Lorg/apache/hadoop/hdfs/protocol/LocatedBlocks;JLjava/lang/String;)V"));
        method.instructions.insertBefore(insn, hook);
        checks++;
      }
      if (insn.getOpcode() == ATHROW && line == 518) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(call("targetThrow", "(Ljava/lang/Throwable;)V"));
        method.instructions.insertBefore(insn, hook);
        throwsFound++;
      }
      insn = next;
    }
    if (checks != 1 || throwsFound != 1) {
      throw new IllegalStateException("target check/throw mismatch " + checks + "/" + throwsFound);
    }
    return checks + throwsFound;
  }

  private static void io(MethodNode method, String marker, String site) {
    InsnList hook = new InsnList();
    hook.add(new LdcInsnNode(marker));
    hook.add(new LdcInsnNode(site));
    hook.add(call("io", "(Ljava/lang/String;Ljava/lang/String;)V"));
    method.instructions.insert(hook);
  }

  private static void readIo(MethodNode method) {
    InsnList hook = new InsnList();
    hook.add(new VarInsnNode(ALOAD, 0));
    hook.add(new FieldInsnNode(GETFIELD, READ, "datanodeID",
        "Lorg/apache/hadoop/hdfs/protocol/DatanodeID;"));
    hook.add(new VarInsnNode(ALOAD, 0));
    hook.add(new FieldInsnNode(GETFIELD, READ, "blockId", "J"));
    hook.add(new VarInsnNode(ALOAD, 0));
    hook.add(new FieldInsnNode(GETFIELD, READ, "filename", "Ljava/lang/String;"));
    hook.add(call("readIo", "(Lorg/apache/hadoop/hdfs/protocol/DatanodeID;JLjava/lang/String;)V"));
    method.instructions.insert(hook);
  }

  private static int locatedBlocks(MethodNode method) {
    int returns = 0;
    for (AbstractInsnNode instruction = method.instructions.getFirst();
         instruction != null; ) {
      AbstractInsnNode next = instruction.getNext();
      if (instruction.getOpcode() == ARETURN) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(new VarInsnNode(ALOAD, 1));
        hook.add(call("locatedBlocks",
            "(Lorg/apache/hadoop/hdfs/protocol/LocatedBlocks;Ljava/lang/String;)V"));
        method.instructions.insertBefore(instruction, hook);
        returns++;
      }
      instruction = next;
    }
    if (returns == 0) throw new IllegalStateException("getLocatedBlocks has no object return");
    return returns;
  }

  public static void main(String[] args) throws Exception {
    if (args.length != 3) throw new IllegalArgumentException("input .class, name, output directory");
    ClassNode node = new ClassNode();
    new ClassReader(Files.readAllBytes(Paths.get(args[0]))).accept(node, 0);
    if (!node.name.equals(args[1])) throw new IllegalArgumentException("name mismatch: " + node.name);
    int count = 0;
    for (MethodNode method : node.methods) {
      if (node.name.equals(TARGET) && method.name.equals("fetchBlockAt") && method.desc.equals(
          "(JJZ)Lorg/apache/hadoop/hdfs/protocol/LocatedBlock;")) count += target(method);
      if (node.name.equals(RPC) && method.name.equals("getRpcResponse")) {
        io(method, "FAULT:HDFS_RPC:RESPONSE", "Client.getRpcResponse"); count++;
      }
      if (node.name.equals(CLIENT) && method.name.equals("getLocatedBlocks")
          && (method.desc.equals("(Ljava/lang/String;J)Lorg/apache/hadoop/hdfs/protocol/LocatedBlocks;")
              || method.desc.equals("(Ljava/lang/String;JJ)Lorg/apache/hadoop/hdfs/protocol/LocatedBlocks;"))) {
        if (method.desc.equals("(Ljava/lang/String;J)Lorg/apache/hadoop/hdfs/protocol/LocatedBlocks;")) {
          io(method, "FAULT:HDFS_RPC:GET_BLOCK_LOCATIONS", "DFSClient.getLocatedBlocks");
          count++;
        }
        count += locatedBlocks(method);
      }
      if (node.name.equals(READ) && method.name.equals("read") && method.desc.equals("([BII)I")) {
        readIo(method); count++;
      }
    }
    int expected = node.name.equals(TARGET) ? 2 : node.name.equals(CLIENT) ? 3 : 1;
    if (count != expected) throw new IllegalStateException(node.name + " hooks=" + count + " expected=" + expected);
    ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
    node.accept(writer);
    Path out = Paths.get(args[2], node.name + ".class");
    Files.createDirectories(out.getParent());
    Files.write(out, writer.toByteArray());
    System.out.println(out);
  }
}
