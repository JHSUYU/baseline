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
import org.objectweb.asm.tree.LdcInsnNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.VarInsnNode;

/** ASM hooks for the exact StatefulBlockInfo guard and DataNode report RPC. */
public final class PatchHdfs17 implements Opcodes {
  private static final String TARGET =
      "org/apache/hadoop/hdfs/server/blockmanagement/BlockManager$StatefulBlockInfo";
  private static final String BLOCK_INFO =
      "org/apache/hadoop/hdfs/server/blockmanagement/BlockInfo";
  private static final String BLOCK = "org/apache/hadoop/hdfs/protocol/Block";
  private static final String ACTOR = "org/apache/hadoop/hdfs/server/datanode/BPServiceActor";
  private static final String OFFER = "org/apache/hadoop/hdfs/server/datanode/BPOfferService";
  private static final String REGISTRATION =
      "org/apache/hadoop/hdfs/server/protocol/DatanodeRegistration";

  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("input class, overlay root");
    ClassNode node = new ClassNode();
    new ClassReader(Files.readAllBytes(Paths.get(args[0]))).accept(node, 0);
    if (!TARGET.equals(node.name) && !ACTOR.equals(node.name)) {
      throw new IllegalArgumentException("wrong class " + node.name);
    }
    int checks = 0;
    int ioHooks = 0;
    for (MethodNode method : node.methods) {
      if (TARGET.equals(node.name) && method.name.equals("<init>")) {
        for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; ) {
          AbstractInsnNode next = insn.getNext();
          if (insn instanceof MethodInsnNode) {
            MethodInsnNode call = (MethodInsnNode) insn;
            if (call.owner.equals("org/apache/hadoop/util/Preconditions")
                && call.name.equals("checkArgument") && call.desc.equals("(Z)V")) {
              InsnList hook = new InsnList();
              hook.add(new InsnNode(DUP));
              hook.add(new VarInsnNode(ALOAD, 1));
              hook.add(new MethodInsnNode(INVOKEVIRTUAL, BLOCK_INFO, "getBlockId", "()J", false));
              hook.add(new VarInsnNode(ALOAD, 2));
              hook.add(new MethodInsnNode(INVOKEVIRTUAL, BLOCK, "getBlockId", "()J", false));
              hook.add(new VarInsnNode(ALOAD, 3));
              hook.add(new MethodInsnNode(INVOKESTATIC, "java/lang/String", "valueOf",
                  "(Ljava/lang/Object;)Ljava/lang/String;", false));
              hook.add(new MethodInsnNode(INVOKESTATIC, "Hdfs17Probe", "targetCheck",
                  "(ZJJLjava/lang/String;)V", false));
              method.instructions.insertBefore(insn, hook);
              checks++;
            }
          }
          insn = next;
        }
      }
      if (ACTOR.equals(node.name) && method.name.equals("blockReport")
          && method.desc.equals("(J)Ljava/util/List;")) {
        for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; ) {
          AbstractInsnNode next = insn.getNext();
          if (insn instanceof MethodInsnNode) {
            MethodInsnNode call = (MethodInsnNode) insn;
            if (call.name.equals("blockReport")
                && call.owner.equals(
                    "org/apache/hadoop/hdfs/protocolPB/DatanodeProtocolClientSideTranslatorPB")) {
              String site = ioHooks == 0 ? "BPServiceActor.blockReport#full"
                  : "BPServiceActor.blockReport#split";
              InsnList hook = new InsnList();
              hook.add(new LdcInsnNode("FAULT:HDFS_BLOCK_REPORT:RPC"));
              hook.add(new LdcInsnNode(site));
              hook.add(new VarInsnNode(ALOAD, 0));
              hook.add(new FieldInsnNode(GETFIELD, ACTOR, "bpos", "L" + OFFER + ";"));
              hook.add(new MethodInsnNode(INVOKEVIRTUAL, OFFER, "getBlockPoolId",
                  "()Ljava/lang/String;", false));
              hook.add(new VarInsnNode(ALOAD, 0));
              hook.add(new MethodInsnNode(INVOKEVIRTUAL, ACTOR, "getBpRegistration",
                  "()L" + REGISTRATION + ";", false));
              hook.add(new MethodInsnNode(INVOKEVIRTUAL, REGISTRATION, "getDatanodeUuid",
                  "()Ljava/lang/String;", false));
              hook.add(new MethodInsnNode(INVOKESTATIC, "Hdfs17Probe", "io",
                  "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V",
                  false));
              method.instructions.insertBefore(insn, hook);
              ioHooks++;
            }
          }
          insn = next;
        }
      }
    }
    if ((TARGET.equals(node.name) && checks != 1)
        || (ACTOR.equals(node.name) && ioHooks != 2)) {
      throw new IllegalStateException("target or RPC hook mismatch " + checks + "/" + ioHooks);
    }
    ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
    node.accept(writer);
    Path output = Paths.get(args[1], node.name + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(output);
  }
}
