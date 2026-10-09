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
import org.objectweb.asm.tree.LdcInsnNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.VarInsnNode;

/** Instrument the exact released-class null-key branch and its throw. */
public final class PatchHdfs11 implements Opcodes {
  private static final String TARGET =
      "org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager";
  private static final String SASL =
      "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferServer";

  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("input class, overlay root");
    ClassNode node = new ClassNode();
    new ClassReader(Files.readAllBytes(Paths.get(args[0]))).accept(node, 0);
    if (!TARGET.equals(node.name) && !SASL.equals(node.name)) {
      throw new IllegalArgumentException("wrong class " + node.name);
    }
    int checks = 0, throwsFound = 0;
    int ioHooks = 0;
    for (MethodNode method : node.methods) {
      if (node.name.equals(SASL) && method.name.equals("doSaslHandshake")) {
        for (AbstractInsnNode instruction = method.instructions.getFirst();
             instruction != null; ) {
          AbstractInsnNode next = instruction.getNext();
          if (instruction instanceof MethodInsnNode) {
            MethodInsnNode call = (MethodInsnNode) instruction;
            String site = null;
            if (call.owner.equals("java/io/DataInputStream")
                && call.name.equals("readInt") && call.desc.equals("()I")) {
              site = "SaslDataTransferServer.doSaslHandshake#readMagic";
            } else if (call.owner.equals(
                "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/DataTransferSaslUtil")
                && call.name.equals("readSaslMessageWithHandshakeSecret")) {
              site = "SaslDataTransferServer.doSaslHandshake#readSecret";
            } else if (call.owner.equals(
                "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/DataTransferSaslUtil")
                && call.name.equals("readSaslMessageAndNegotiationCipherOptions")) {
              site = "SaslDataTransferServer.doSaslHandshake#readOptions";
            }
            if (site != null) {
              InsnList hook = new InsnList();
              hook.add(new LdcInsnNode("FAULT:HDFS_SASL:READ"));
              hook.add(new LdcInsnNode(site));
              hook.add(new MethodInsnNode(INVOKESTATIC, "Hdfs11Probe", "io",
                  "(Ljava/lang/String;Ljava/lang/String;)V", false));
              method.instructions.insertBefore(instruction, hook);
              ioHooks++;
            }
          }
          instruction = next;
        }
        continue;
      }
      if (!node.name.equals(TARGET) || !method.name.equals("retrieveDataEncryptionKey")
          || !method.desc.equals("(I[B)[B")) continue;
      int line = -1;
      for (AbstractInsnNode instruction = method.instructions.getFirst();
           instruction != null; ) {
        AbstractInsnNode next = instruction.getNext();
        if (instruction instanceof LineNumberNode) {
          line = ((LineNumberNode) instruction).line;
        }
        if (instruction instanceof JumpInsnNode
            && instruction.getOpcode() == IFNONNULL && line == 552) {
          InsnList hook = new InsnList();
          hook.add(new InsnNode(DUP));
          hook.add(new VarInsnNode(ILOAD, 1));
          hook.add(new MethodInsnNode(INVOKESTATIC, "Hdfs11Probe", "targetCheck",
              "(Ljava/lang/Object;I)V", false));
          method.instructions.insertBefore(instruction, hook);
          checks++;
        }
        AbstractInsnNode previous = instruction.getPrevious();
        while (previous != null && previous.getOpcode() < 0) {
          previous = previous.getPrevious();
        }
        if (instruction.getOpcode() == ATHROW
            && previous instanceof MethodInsnNode
            && ((MethodInsnNode) previous).owner.equals(
                "org/apache/hadoop/hdfs/protocol/datatransfer/InvalidEncryptionKeyException")
            && ((MethodInsnNode) previous).name.equals("<init>")) {
          InsnList hook = new InsnList();
          hook.add(new InsnNode(DUP));
          hook.add(new MethodInsnNode(INVOKESTATIC, "Hdfs11Probe", "targetThrow",
              "(Ljava/lang/Throwable;)V", false));
          method.instructions.insertBefore(instruction, hook);
          throwsFound++;
        }
        instruction = next;
      }
    }
    if ((node.name.equals(TARGET) && (checks != 1 || throwsFound != 1))
        || (node.name.equals(SASL) && ioHooks != 3)) {
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
