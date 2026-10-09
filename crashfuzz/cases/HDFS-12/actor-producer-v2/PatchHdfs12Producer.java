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

/** HDFS-12-only hooks: real heartbeat response and local key command import. */
public final class PatchHdfs12Producer implements Opcodes {
  private static final String PROBE = "HdfsKeyActorProbe";
  private static final String ACTOR =
      "org/apache/hadoop/hdfs/server/datanode/BPServiceActor";
  private static final String OFFER =
      "org/apache/hadoop/hdfs/server/datanode/BPOfferService";
  private static final String DN =
      "org/apache/hadoop/hdfs/server/datanode/DataNode";
  private static final String POOL_MANAGER =
      "org/apache/hadoop/hdfs/security/token/block/BlockPoolTokenSecretManager";
  private static final String RESPONSE =
      "org/apache/hadoop/hdfs/server/protocol/HeartbeatResponse";
  private static final String COMMAND =
      "org/apache/hadoop/hdfs/server/protocol/DatanodeCommand";
  private static final String RESPONSE_DESC = "L" + RESPONSE + ";";
  private static final String DN_DESC = "L" + DN + ";";
  private static final String COMMAND_DESC = "L" + COMMAND + ";";

  private static MethodInsnNode hook(String name, String descriptor) {
    return new MethodInsnNode(INVOKESTATIC, PROBE, name, descriptor, false);
  }

  private static InsnList actorFields(String owner) {
    InsnList code = new InsnList();
    code.add(new VarInsnNode(ALOAD, 0));
    code.add(new FieldInsnNode(GETFIELD, owner, "dn", DN_DESC));
    code.add(new VarInsnNode(ALOAD, 0));
    if (ACTOR.equals(owner)) {
      code.add(new FieldInsnNode(GETFIELD, ACTOR, "bpos", "L" + OFFER + ";"));
      code.add(new MethodInsnNode(INVOKEVIRTUAL, OFFER, "getBlockPoolId",
          "()Ljava/lang/String;", false));
      code.add(new VarInsnNode(ALOAD, 0));
      code.add(new FieldInsnNode(GETFIELD, ACTOR, "nnAddr", "Ljava/net/InetSocketAddress;"));
    } else {
      code.add(new MethodInsnNode(INVOKEVIRTUAL, OFFER, "getBlockPoolId",
          "()Ljava/lang/String;", false));
      code.add(new VarInsnNode(ALOAD, 2)); // processCommandFromActive/Standby NN
    }
    return code;
  }

  private static int patchActor(MethodNode method) {
    if (!method.name.equals("offerService")) return 0;
    int count = 0;
    for (AbstractInsnNode at = method.instructions.getFirst(); at != null; at = at.getNext()) {
      if (!(at instanceof MethodInsnNode)) continue;
      MethodInsnNode call = (MethodInsnNode) at;
      if (!ACTOR.equals(call.owner) || !"sendHeartBeat".equals(call.name)
          || !call.desc.endsWith(")" + RESPONSE_DESC)) continue;
      // On stack immediately after RPC: [HeartbeatResponse]. Keep the original
      // response for ASTORE, and let the probe optionally model response loss.
      InsnList code = new InsnList();
      code.add(new InsnNode(DUP));
      code.add(actorFields(ACTOR));
      code.add(hook("keyResponse", "(" + RESPONSE_DESC + DN_DESC
          + "Ljava/lang/String;Ljava/lang/Object;)V"));
      method.instructions.insert(at, code);
      count++;
    }
    return count;
  }

  private static int patchOffer(MethodNode method) {
    if (!method.name.equals("processCommandFromActive")
        && !method.name.equals("processCommandFromStandby")) return 0;
    int count = 0;
    for (AbstractInsnNode at = method.instructions.getFirst(); at != null; ) {
      AbstractInsnNode next = at.getNext();
      if (at instanceof MethodInsnNode) {
        MethodInsnNode call = (MethodInsnNode) at;
        if (POOL_MANAGER.equals(call.owner) && "addKeys".equals(call.name)) {
          // Original stack [poolManager, rawPool, exportedKeys] remains intact.
          InsnList before = actorFields(OFFER);
          before.add(new VarInsnNode(ALOAD, 1));
          before.add(hook("keyImportBefore", "(" + DN_DESC
              + "Ljava/lang/String;Ljava/lang/Object;" + COMMAND_DESC + ")V"));
          method.instructions.insertBefore(at, before);
          InsnList after = actorFields(OFFER);
          after.add(new VarInsnNode(ALOAD, 1));
          after.add(hook("keyImportAfter", "(" + DN_DESC
              + "Ljava/lang/String;Ljava/lang/Object;" + COMMAND_DESC + ")V"));
          method.instructions.insert(at, after);
          count++;
        }
      }
      at = next;
    }
    return count;
  }

  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("input class, overlay root");
    ClassNode node = new ClassNode();
    new ClassReader(Files.readAllBytes(Paths.get(args[0]))).accept(node, 0);
    if (!ACTOR.equals(node.name) && !OFFER.equals(node.name)) {
      throw new IllegalArgumentException("wrong producer class " + node.name);
    }
    int hooks = 0;
    for (MethodNode method : node.methods) {
      hooks += ACTOR.equals(node.name) ? patchActor(method) : patchOffer(method);
    }
    int expected = ACTOR.equals(node.name) ? 1 : 2;
    if (hooks != expected) throw new IllegalStateException(
        node.name + " producer hooks=" + hooks + " expected=" + expected);
    ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
    node.accept(writer);
    Path output = Paths.get(args[1], node.name + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(node.name + " producer hooks=" + hooks);
  }
}
