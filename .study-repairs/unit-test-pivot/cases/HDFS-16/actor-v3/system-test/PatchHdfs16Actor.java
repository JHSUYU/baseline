import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.Type;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.FieldInsnNode;
import org.objectweb.asm.tree.InsnList;
import org.objectweb.asm.tree.InsnNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.VarInsnNode;

/** Case-local actor roots copied from the tested Hadoop storage V2 bridge. */
public final class PatchHdfs16Actor implements Opcodes {
  private static final String REGISTRY =
      "org/apache/hadoop/hdfs/hdfs16independent/Hdfs16ActorRegistry";
  private static final String CLUSTER = "org/apache/hadoop/hdfs/MiniDFSCluster";
  private static final String DN = "org/apache/hadoop/hdfs/server/datanode/DataNode";
  private static final String ACTOR = "org/apache/hadoop/hdfs/server/datanode/BPServiceActor";

  private static MethodInsnNode call(String name, String descriptor) {
    return new MethodInsnNode(INVOKESTATIC, REGISTRY, name, descriptor, false);
  }

  private static int patchCluster(MethodNode method) {
    if (!method.name.equals("startDataNodes") ||
        Type.getArgumentTypes(method.desc).length != 15) {
      return 0;
    }
    method.instructions.insert(call("startEpisode", "()V"));
    int exits = 0;
    for (AbstractInsnNode insn = method.instructions.getFirst();
         insn != null; insn = insn.getNext()) {
      if (insn.getOpcode() == RETURN) {
        method.instructions.insertBefore(insn, call("endEpisode", "()V"));
        exits++;
      }
    }
    if (exits == 0) {
      throw new IllegalStateException("MiniDFSCluster startup exit missing");
    }
    return 1;
  }

  private static int patchDataNode(MethodNode method) {
    if (method.name.equals("<init>")) {
      int starts = 0;
      for (AbstractInsnNode insn = method.instructions.getFirst();
           insn != null; insn = insn.getNext()) {
        if (!(insn instanceof MethodInsnNode)) {
          continue;
        }
        MethodInsnNode site = (MethodInsnNode) insn;
        if (!site.owner.equals(DN) || !site.name.equals("startDataNode")) {
          continue;
        }
        InsnList hook = new InsnList();
        hook.add(new VarInsnNode(ALOAD, 0));
        hook.add(new VarInsnNode(ALOAD, 1));
        hook.add(call("registerDataNode",
            "(Lorg/apache/hadoop/hdfs/server/datanode/DataNode;"
            + "Lorg/apache/hadoop/conf/Configuration;)"
            + "Lorg/apache/hadoop/hdfs/server/datanode/DataNode;"));
        hook.add(new InsnNode(POP));
        method.instructions.insertBefore(insn, hook);
        starts++;
      }
      return starts;
    }
    if (!method.name.equals("instantiateDataNode") ||
        Type.getArgumentTypes(method.desc).length != 3) {
      return 0;
    }
    int returns = 0;
    for (AbstractInsnNode insn = method.instructions.getFirst();
         insn != null; insn = insn.getNext()) {
      if (insn.getOpcode() == ARETURN) {
        InsnList hook = new InsnList();
        hook.add(new VarInsnNode(ALOAD, 1));
        hook.add(call("registerDataNode",
            "(Lorg/apache/hadoop/hdfs/server/datanode/DataNode;"
            + "Lorg/apache/hadoop/conf/Configuration;)"
            + "Lorg/apache/hadoop/hdfs/server/datanode/DataNode;"));
        method.instructions.insertBefore(insn, hook);
        returns++;
      }
    }
    if (returns == 0) {
      throw new IllegalStateException("DataNode registration return missing");
    }
    return 1;
  }

  private static int patchActor(MethodNode method) {
    if (!method.name.equals("run") || !method.desc.equals("()V")) {
      return 0;
    }
    InsnList entry = new InsnList();
    entry.add(new VarInsnNode(ALOAD, 0));
    entry.add(new FieldInsnNode(GETFIELD, ACTOR, "dn",
        "Lorg/apache/hadoop/hdfs/server/datanode/DataNode;"));
    entry.add(new VarInsnNode(ALOAD, 0));
    entry.add(new FieldInsnNode(GETFIELD, ACTOR, "nnAddr",
        "Ljava/net/InetSocketAddress;"));
    entry.add(call("enterActor",
        "(Lorg/apache/hadoop/hdfs/server/datanode/DataNode;"
        + "Ljava/net/InetSocketAddress;)V"));
    method.instructions.insert(entry);
    int exits = 0;
    for (AbstractInsnNode insn = method.instructions.getFirst();
         insn != null; insn = insn.getNext()) {
      if (insn.getOpcode() == RETURN) {
        method.instructions.insertBefore(insn, call("exitActor", "()V"));
        exits++;
      }
    }
    if (exits == 0) {
      throw new IllegalStateException("BPServiceActor exit missing");
    }
    return 1;
  }

  public static void main(String[] args) throws Exception {
    if (args.length != 3) {
      throw new IllegalArgumentException("input.class internalClassName outputDir");
    }
    ClassNode node = new ClassNode();
    new ClassReader(Files.readAllBytes(Paths.get(args[0]))).accept(node, 0);
    if (!node.name.equals(args[1])) {
      throw new IllegalArgumentException("class name mismatch: " + node.name);
    }
    int count = 0;
    for (MethodNode method : node.methods) {
      if (node.name.equals(CLUSTER)) {
        count += patchCluster(method);
      } else if (node.name.equals(DN)) {
        count += patchDataNode(method);
      } else if (node.name.equals(ACTOR)) {
        count += patchActor(method);
      }
    }
    int expected = node.name.equals(DN) ? 2 : 1;
    if (count != expected) {
      throw new IllegalStateException(node.name + " hooks=" + count);
    }
    ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
    node.accept(writer);
    Path output = Paths.get(args[2], node.name + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(node.name + " hooks=" + count + " " + output);
  }
}
