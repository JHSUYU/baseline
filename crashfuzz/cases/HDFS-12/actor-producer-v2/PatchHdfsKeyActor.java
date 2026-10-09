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
import org.objectweb.asm.tree.JumpInsnNode;
import org.objectweb.asm.tree.LdcInsnNode;
import org.objectweb.asm.tree.LineNumberNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.VarInsnNode;

/** Offline hooks in the released Hadoop 3.4.3 classes; original JUnit unchanged. */
public final class PatchHdfsKeyActor implements Opcodes {
  private static final String PROBE = "HdfsKeyActorProbe";
  private static final String CLUSTER = "org/apache/hadoop/hdfs/MiniDFSCluster";
  private static final String DN = "org/apache/hadoop/hdfs/server/datanode/DataNode";
  private static final String MANAGER = "org/apache/hadoop/hdfs/security/token/block/BlockTokenSecretManager";
  private static final String POOL_MANAGER =
      "org/apache/hadoop/hdfs/security/token/block/BlockPoolTokenSecretManager";
  private static final String SERVER =
      "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferServer";
  private static final String DATA_NODE_DESC = "L" + DN + ";";
  private static final String MANAGER_DESC = "L" + MANAGER + ";";
  private static final String SERVER_DESC = "L" + SERVER + ";";

  private static MethodInsnNode hook(String name, String desc) {
    return new MethodInsnNode(INVOKESTATIC, PROBE, name, desc, false);
  }

  private static int patchCluster(MethodNode method) {
    if (!method.name.equals("startDataNodes") || Type.getArgumentTypes(method.desc).length != 15)
      return 0;
    method.instructions.insert(hook("startEpisode", "()V"));
    int exits = 0;
    for (AbstractInsnNode at = method.instructions.getFirst(); at != null; at = at.getNext()) {
      if (at.getOpcode() == RETURN) {
        method.instructions.insertBefore(at, hook("endEpisode", "()V"));
        exits++;
      }
    }
    if (exits == 0) throw new IllegalStateException("no MiniDFSCluster start exit");
    return 1;
  }

  private static int patchDataNode(MethodNode method) {
    int count = 0;
    for (AbstractInsnNode at = method.instructions.getFirst(); at != null; ) {
      AbstractInsnNode next = at.getNext();
      if (method.name.equals("<init>") && at instanceof MethodInsnNode) {
        MethodInsnNode call = (MethodInsnNode) at;
        if (call.owner.equals(DN) && call.name.equals("startDataNode")) {
          InsnList code = new InsnList();
          code.add(new VarInsnNode(ALOAD, 0));
          code.add(new VarInsnNode(ALOAD, 1));
          code.add(hook("registerDataNode", "(" + DATA_NODE_DESC
              + "Lorg/apache/hadoop/conf/Configuration;)V"));
          method.instructions.insertBefore(at, code);
          count++;
        }
      }
      if (method.name.equals("registerBlockPoolWithSecretManager")
          && at instanceof MethodInsnNode) {
        MethodInsnNode call = (MethodInsnNode) at;
        if (call.owner.equals(POOL_MANAGER) && call.name.equals("addBlockPool")) {
          // Existing stack: [poolManager, rawBlockPoolId, secretManager].
          // DUP preserves the original call's arguments; local 2 is the pool ID.
          InsnList code = new InsnList();
          code.add(new InsnNode(DUP));
          code.add(new VarInsnNode(ALOAD, 0));
          code.add(new InsnNode(SWAP));
          code.add(new VarInsnNode(ALOAD, 2));
          code.add(hook("bindManager", "(" + DATA_NODE_DESC + MANAGER_DESC
              + "Ljava/lang/String;)V"));
          method.instructions.insertBefore(at, code);
          count++;
        }
      }
      if (at instanceof FieldInsnNode && at.getOpcode() == PUTFIELD) {
        FieldInsnNode field = (FieldInsnNode) at;
        if (field.owner.equals(DN) && field.name.equals("saslServer")
            && field.desc.equals(SERVER_DESC)) {
          InsnList code = new InsnList();
          code.add(new InsnNode(DUP2));
          code.add(hook("bindSaslServer", "(" + DATA_NODE_DESC + SERVER_DESC + ")V"));
          method.instructions.insertBefore(at, code);
          count++;
        }
      }
      at = next;
    }
    return count;
  }

  private static int patchServer(MethodNode method) {
    if (!method.name.equals("doSaslHandshake")) return 0;
    int count = 0;
    for (AbstractInsnNode at = method.instructions.getFirst(); at != null; ) {
      AbstractInsnNode next = at.getNext();
      if (at instanceof MethodInsnNode) {
        MethodInsnNode call = (MethodInsnNode) at;
        String site = null;
        if (call.owner.equals("java/io/DataInputStream") && call.name.equals("readInt")
            && call.desc.equals("()I")) {
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
          InsnList code = new InsnList();
          code.add(new VarInsnNode(ALOAD, 0));
          code.add(new VarInsnNode(ALOAD, 1));
          code.add(new LdcInsnNode("FAULT:HDFS_SASL:READ"));
          code.add(new LdcInsnNode(site));
          code.add(hook("io", "(" + SERVER_DESC
              + "Lorg/apache/hadoop/hdfs/net/Peer;"
              + "Ljava/lang/String;Ljava/lang/String;)V"));
          method.instructions.insertBefore(at, code);
          count++;
        }
      }
      at = next;
    }
    return count;
  }

  private static int patchManager(MethodNode method) {
    boolean eleven = method.name.equals("retrieveDataEncryptionKey")
        && method.desc.equals("(I[B)[B");
    boolean twelve = method.name.equals("retrievePassword")
        && method.desc.equals("(Lorg/apache/hadoop/hdfs/security/token/block/BlockTokenIdentifier;)[B");
    if (!eleven && !twelve) return 0;
    int line = -1, checks = 0, throwsFound = 0;
    for (AbstractInsnNode at = method.instructions.getFirst(); at != null; ) {
      AbstractInsnNode next = at.getNext();
      if (at instanceof LineNumberNode) line = ((LineNumberNode) at).line;
      if (at instanceof JumpInsnNode && at.getOpcode() == IFNONNULL
          && line == (eleven ? 552 : 511)) {
        InsnList code = new InsnList();
        code.add(new InsnNode(DUP));
        code.add(new VarInsnNode(ALOAD, 0));
        if (eleven) {
          code.add(new VarInsnNode(ILOAD, 1));
        } else {
          code.add(new VarInsnNode(ALOAD, 1));
          code.add(new MethodInsnNode(INVOKEVIRTUAL,
              "org/apache/hadoop/hdfs/security/token/block/BlockTokenIdentifier",
              "getKeyId", "()I", false));
        }
        code.add(hook(eleven ? "check11" : "check12", "(Ljava/lang/Object;"
            + MANAGER_DESC + "I)V"));
        method.instructions.insertBefore(at, code);
        checks++;
      }
      AbstractInsnNode previous = at.getPrevious();
      while (previous != null && previous.getOpcode() < 0) previous = previous.getPrevious();
      if (at.getOpcode() == ATHROW && previous instanceof MethodInsnNode) {
        MethodInsnNode constructor = (MethodInsnNode) previous;
        boolean selectedThrow = eleven
            ? constructor.owner.equals(
                "org/apache/hadoop/hdfs/protocol/datatransfer/InvalidEncryptionKeyException")
                && constructor.name.equals("<init>")
            : line == 514 && constructor.owner.equals(
                "org/apache/hadoop/security/token/SecretManager$InvalidToken")
                && constructor.name.equals("<init>");
        if (selectedThrow) {
          InsnList code = new InsnList();
          code.add(new InsnNode(DUP));
          code.add(new VarInsnNode(ALOAD, 0));
          code.add(hook(eleven ? "throw11" : "throw12", "(Ljava/lang/Throwable;"
              + MANAGER_DESC + ")V"));
          method.instructions.insertBefore(at, code);
          throwsFound++;
        }
      }
      at = next;
    }
    if (checks != 1 || throwsFound != 1)
      throw new IllegalStateException(method.name + " guard/throw=" + checks + "/" + throwsFound);
    return checks + throwsFound;
  }

  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("input class, overlay root");
    ClassNode node = new ClassNode();
    new ClassReader(Files.readAllBytes(Paths.get(args[0]))).accept(node, 0);
    int hooks = 0;
    for (MethodNode method : node.methods) {
      if (node.name.equals(CLUSTER)) hooks += patchCluster(method);
      if (node.name.equals(DN)) hooks += patchDataNode(method);
      if (node.name.equals(SERVER)) hooks += patchServer(method);
      if (node.name.equals(MANAGER)) hooks += patchManager(method);
    }
    int minimum = node.name.equals(DN) ? 3 : node.name.equals(MANAGER) ? 4
        : node.name.equals(SERVER) ? 3 : node.name.equals(CLUSTER) ? 1 : -1;
    if (hooks < minimum) throw new IllegalStateException(node.name + " hooks=" + hooks
        + " expected at least " + minimum);
    ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
    node.accept(writer);
    Path output = Paths.get(args[1], node.name + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(node.name + " hooks=" + hooks);
  }
}
