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

/** Case-local ASM hooks for the released HDFS finalize command and its RPC. */
public final class PatchHdfs19 implements Opcodes {
  private static final String OFFER = "org/apache/hadoop/hdfs/server/datanode/BPOfferService";
  private static final String ACTOR = "org/apache/hadoop/hdfs/server/datanode/BPServiceActor";
  private static final String DATA_STORAGE = "org/apache/hadoop/hdfs/server/datanode/DataStorage";
  private static final String BP_STORAGE = "org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage";
  private static final String CMD = "org/apache/hadoop/hdfs/server/protocol/DatanodeCommand";

  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("input class, overlay root");
    ClassNode node = new ClassNode();
    new ClassReader(Files.readAllBytes(Paths.get(args[0]))).accept(node, 0);
    if (!OFFER.equals(node.name) && !ACTOR.equals(node.name)
        && !DATA_STORAGE.equals(node.name) && !BP_STORAGE.equals(node.name)) {
      throw new IllegalArgumentException("wrong class " + node.name);
    }
    int checks = 0, throwsFound = 0, ioHooks = 0;
    for (MethodNode method : node.methods) {
      if ((DATA_STORAGE.equals(node.name) || BP_STORAGE.equals(node.name))
          && method.name.equals("doFinalize")) {
        for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; ) {
          AbstractInsnNode next = insn.getNext();
          if (insn instanceof MethodInsnNode) {
            MethodInsnNode call = (MethodInsnNode) insn;
            if (call.name.equals("rename")
                && call.desc.equals("(Ljava/io/File;Ljava/io/File;)V")) {
              InsnList hook = new InsnList();
              hook.add(new InsnNode(DUP2));
              hook.add(new LdcInsnNode("FAULT:HDFS_FINALIZE:RENAME"));
              hook.add(new LdcInsnNode(node.name.equals(DATA_STORAGE)
                  ? "DataStorage.doFinalize#rename"
                  : "BlockPoolSliceStorage.doFinalize#rename"));
              hook.add(new MethodInsnNode(INVOKESTATIC, "Hdfs19Probe", "ioFile",
                  "(Ljava/io/File;Ljava/io/File;Ljava/lang/String;Ljava/lang/String;)V", false));
              method.instructions.insertBefore(insn, hook);
              ioHooks++;
            }
          }
          insn = next;
        }
        continue;
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
              hook.add(new MethodInsnNode(INVOKESTATIC, "Hdfs19Probe", "io",
                  "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V", false));
              method.instructions.insertBefore(insn, hook);
              ioHooks++;
            }
          }
          insn = next;
        }
        continue;
      }
      if (!OFFER.equals(node.name) || !method.name.equals("processCommandFromActive")
          || !method.desc.equals("(L" + CMD + ";Ljava/net/InetSocketAddress;)Z")) continue;
      int line = -1;
      for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; ) {
        AbstractInsnNode next = insn.getNext();
        if (insn instanceof LineNumberNode) line = ((LineNumberNode) insn).line;
        AbstractInsnNode branchInput = insn.getPrevious();
        while (branchInput != null && branchInput.getOpcode() < 0) {
          branchInput = branchInput.getPrevious();
        }
        if (insn instanceof JumpInsnNode && insn.getOpcode() == IFNE && line == 768
            && branchInput instanceof MethodInsnNode
            && ((MethodInsnNode) branchInput).owner.equals("java/lang/String")
            && ((MethodInsnNode) branchInput).name.equals("equals")) {
          InsnList hook = new InsnList();
          hook.add(new InsnNode(DUP));
          hook.add(new VarInsnNode(ALOAD, 0));
          hook.add(new MethodInsnNode(INVOKEVIRTUAL, OFFER, "getBlockPoolId",
              "()Ljava/lang/String;", false));
          hook.add(new VarInsnNode(ALOAD, 6));
          hook.add(new MethodInsnNode(INVOKESTATIC, "Hdfs19Probe", "targetCheck",
              "(ZLjava/lang/String;Ljava/lang/String;)V", false));
          method.instructions.insertBefore(insn, hook);
          checks++;
        }
        AbstractInsnNode previous = insn.getPrevious();
        while (previous != null && previous.getOpcode() < 0) previous = previous.getPrevious();
        if (insn.getOpcode() == ATHROW && line == 769
            && previous instanceof MethodInsnNode
            && ((MethodInsnNode) previous).owner.equals("java/lang/AssertionError")
            && ((MethodInsnNode) previous).name.equals("<init>")) {
          InsnList hook = new InsnList();
          hook.add(new InsnNode(DUP));
          hook.add(new MethodInsnNode(INVOKESTATIC, "Hdfs19Probe", "targetThrow",
              "(Ljava/lang/Throwable;)V", false));
          method.instructions.insertBefore(insn, hook);
          throwsFound++;
        }
        insn = next;
      }
    }
    if ((OFFER.equals(node.name) && (checks != 1 || throwsFound != 1))
        || (ACTOR.equals(node.name) && ioHooks != 2)
        || ((DATA_STORAGE.equals(node.name) || BP_STORAGE.equals(node.name)) && ioHooks != 1)) {
      throw new IllegalStateException("target check/throw or I/O hook mismatch "
          + checks + "/" + throwsFound + "/" + ioHooks);
    }
    ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
    node.accept(writer);
    Path output = Paths.get(args[1], node.name + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(output);
  }
}
