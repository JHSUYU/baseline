import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.InsnList;
import org.objectweb.asm.tree.LdcInsnNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;

/** Observe exact HDFS control-plane I/O used to deliver block-token keys. */
public final class PatchHdfs11KeyRpc implements Opcodes {
  private static final String ACTOR =
      "org/apache/hadoop/hdfs/server/datanode/BPServiceActor";
  private static final String OFFER =
      "org/apache/hadoop/hdfs/server/datanode/BPOfferService";
  private static final String TRANSLATOR =
      "org/apache/hadoop/hdfs/protocolPB/DatanodeProtocolClientSideTranslatorPB";
  private static final String KEY_MANAGER =
      "org/apache/hadoop/hdfs/security/token/block/BlockPoolTokenSecretManager";

  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("input class, overlay root");
    ClassNode node = new ClassNode();
    new ClassReader(Files.readAllBytes(Paths.get(args[0]))).accept(node, 0);
    if (!ACTOR.equals(node.name) && !OFFER.equals(node.name)) {
      throw new IllegalArgumentException("wrong class " + node.name);
    }
    int heartbeat = 0, activeKeys = 0, standbyKeys = 0;
    for (MethodNode method : node.methods) {
      for (AbstractInsnNode instruction = method.instructions.getFirst();
           instruction != null; ) {
        AbstractInsnNode next = instruction.getNext();
        if (instruction instanceof MethodInsnNode) {
          MethodInsnNode call = (MethodInsnNode) instruction;
          String marker = null, site = null;
          if (ACTOR.equals(node.name) && method.name.equals("sendHeartBeat")
              && call.owner.equals(TRANSLATOR) && call.name.equals("sendHeartbeat")) {
            marker = "FAULT:HDFS_HEARTBEAT:RPC";
            site = "BPServiceActor.sendHeartBeat#rpc";
            heartbeat++;
          } else if (OFFER.equals(node.name) && call.owner.equals(KEY_MANAGER)
              && call.name.equals("addKeys")
              && method.name.equals("processCommandFromActive")) {
            marker = "FAULT:HDFS_KEY_UPDATE:RPC";
            site = "BPOfferService.processCommandFromActive#receiveKeys";
            activeKeys++;
          } else if (OFFER.equals(node.name) && call.owner.equals(KEY_MANAGER)
              && call.name.equals("addKeys")
              && method.name.equals("processCommandFromStandby")) {
            marker = "FAULT:HDFS_KEY_UPDATE:RPC";
            site = "BPOfferService.processCommandFromStandby#receiveKeys";
            standbyKeys++;
          }
          if (site != null) {
            InsnList hook = new InsnList();
            hook.add(new LdcInsnNode(marker));
            hook.add(new LdcInsnNode(site));
            hook.add(new MethodInsnNode(INVOKESTATIC, "Hdfs11Probe", "io",
                "(Ljava/lang/String;Ljava/lang/String;)V", false));
            method.instructions.insertBefore(instruction, hook);
          }
        }
        instruction = next;
      }
    }
    if ((ACTOR.equals(node.name) && heartbeat != 1)
        || (OFFER.equals(node.name) && (activeKeys != 1 || standbyKeys != 1))) {
      throw new IllegalStateException("control-plane hook mismatch "
          + heartbeat + "/" + activeKeys + "/" + standbyKeys);
    }
    ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
    node.accept(writer);
    Path output = Paths.get(args[1], node.name + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(output);
  }
}
