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
import org.objectweb.asm.tree.LdcInsnNode;
import org.objectweb.asm.tree.LineNumberNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.VarInsnNode;

/** Bytecode hooks for runtime DN, NN/BP, RPC peer, file, and exact guard. */
public final class PatchHdfs32V3 implements Opcodes {
  private static final String PROBE =
      "org/apache/hadoop/hdfs/server/datanode/Hdfs32V3Probe";
  private static final String CLUSTER = "org/apache/hadoop/hdfs/MiniDFSCluster";
  private static final String DN = "org/apache/hadoop/hdfs/server/datanode/DataNode";
  private static final String ACTOR = "org/apache/hadoop/hdfs/server/datanode/BPServiceActor";
  private static final String BPOS = "org/apache/hadoop/hdfs/server/datanode/BPOfferService";
  private static final String MANAGER = "org/apache/hadoop/hdfs/server/datanode/BlockPoolManager";
  private static final String DATASET = "org/apache/hadoop/hdfs/server/datanode/fsdataset/impl/FsDatasetImpl";
  private static final String CLIENT = "org/apache/hadoop/ipc/Client";
  private static MethodInsnNode call(String name, String desc) {
    return new MethodInsnNode(INVOKESTATIC, PROBE, name, desc, false);
  }
  private static int patchCluster(MethodNode m) {
    if (m.name.equals("startDataNodes") && Type.getArgumentTypes(m.desc).length == 15) {
      m.instructions.insert(call("startEpisode", "()V"));
      int exits = 0;
      for (AbstractInsnNode n = m.instructions.getFirst(); n != null; n = n.getNext())
        if (n.getOpcode() == RETURN) { m.instructions.insertBefore(n, call("endEpisode", "()V")); ++exits; }
      if (exits == 0) throw new IllegalStateException("startup exit absent");
      return 1;
    }
    if (m.name.equals("getDataNodes") && m.desc.equals("()Ljava/util/ArrayList;")) {
      int count = 0;
      for (AbstractInsnNode n = m.instructions.getFirst(); n != null; n = n.getNext())
        if (n.getOpcode() == ARETURN) {
          InsnList h = new InsnList(); h.add(new InsnNode(DUP));
          h.add(call("registerDataNodes", "(Ljava/util/ArrayList;)V"));
          m.instructions.insertBefore(n, h); ++count;
        }
      if (count != 1) throw new IllegalStateException("getDataNodes returns=" + count);
      return 1;
    }
    if (m.name.equals("getNamesystem") && m.desc.equals("(I)Lorg/apache/hadoop/hdfs/server/namenode/FSNamesystem;")) {
      int count = 0;
      for (AbstractInsnNode n = m.instructions.getFirst(); n != null; n = n.getNext())
        if (n.getOpcode() == ARETURN) {
          InsnList h = new InsnList(); h.add(new InsnNode(DUP));
          h.add(new VarInsnNode(ILOAD, 1)); h.add(new InsnNode(SWAP));
          h.add(call("registerNamesystem", "(ILorg/apache/hadoop/hdfs/server/namenode/FSNamesystem;)V"));
          m.instructions.insertBefore(n, h); ++count;
        }
      if (count != 1) throw new IllegalStateException("getNamesystem returns=" + count);
      return 1;
    }
    return 0;
  }
  private static int patchDataNode(MethodNode m) {
    int count = 0;
    if (m.name.equals("<init>")) {
      for (AbstractInsnNode n = m.instructions.getFirst(); n != null; n = n.getNext()) {
        if (!(n instanceof MethodInsnNode)) continue;
        MethodInsnNode x = (MethodInsnNode)n;
        if (!x.owner.equals(DN) || !x.name.equals("startDataNode")) continue;
        InsnList h = new InsnList(); h.add(new VarInsnNode(ALOAD, 0));
        h.add(new VarInsnNode(ALOAD, 1));
        h.add(call("registerDataNode", "(L" + DN + ";Lorg/apache/hadoop/conf/Configuration;)L" + DN + ";"));
        h.add(new InsnNode(POP)); m.instructions.insertBefore(n, h); ++count;
      }
      return count;
    }
    if (m.name.equals("instantiateDataNode") && Type.getArgumentTypes(m.desc).length == 3) {
      for (AbstractInsnNode n = m.instructions.getFirst(); n != null; n = n.getNext())
        if (n.getOpcode() == ARETURN) {
          InsnList h = new InsnList(); h.add(new VarInsnNode(ALOAD, 1));
          h.add(call("registerDataNode", "(L" + DN + ";Lorg/apache/hadoop/conf/Configuration;)L" + DN + ";"));
          m.instructions.insertBefore(n, h); ++count;
        }
      if (count == 0) throw new IllegalStateException("instantiateDataNode returns absent");
      return 1;
    }
    if (m.name.equals("getFSDataset") && m.desc.startsWith("()L")) {
      for (AbstractInsnNode n = m.instructions.getFirst(); n != null; n = n.getNext())
        if (n.getOpcode() == ARETURN) {
          InsnList h = new InsnList(); h.add(new InsnNode(DUP));
          h.add(new VarInsnNode(ALOAD, 0)); h.add(new InsnNode(SWAP));
          h.add(call("mapDataset", "(L" + DN + ";Ljava/lang/Object;)V"));
          m.instructions.insertBefore(n, h); ++count;
        }
      return count == 0 ? 0 : 1;
    }
    if (!m.name.equals("deleteBlockPool") || !m.desc.equals("(Ljava/lang/String;Z)V")) return 0;
    int line = -1, guards = 0, throwCount = 0;
    for (AbstractInsnNode n = m.instructions.getFirst(); n != null; n = n.getNext()) {
      if (n instanceof LineNumberNode) line = ((LineNumberNode)n).line;
      if (n instanceof MethodInsnNode) {
        MethodInsnNode x = (MethodInsnNode)n;
        if (line == 3819 && x.owner.equals(MANAGER) && x.name.equals("get")) {
          InsnList h = new InsnList(); h.add(new InsnNode(DUP));
          h.add(new VarInsnNode(ALOAD, 0)); h.add(new VarInsnNode(ALOAD, 1));
          h.add(new VarInsnNode(ILOAD, 2));
          h.add(call("guard", "(L" + BPOS + ";L" + DN + ";Ljava/lang/String;Z)V"));
          m.instructions.insert(n, h); ++guards;
        }
      }
      if (line == 3822 && n.getOpcode() == ATHROW) {
        InsnList h = new InsnList(); h.add(new InsnNode(DUP));
        h.add(new VarInsnNode(ALOAD, 0)); h.add(new VarInsnNode(ALOAD, 1));
        h.add(new VarInsnNode(ILOAD, 2));
        h.add(call("targetThrow", "(Ljava/lang/Throwable;L" + DN + ";Ljava/lang/String;Z)V"));
        m.instructions.insertBefore(n, h); ++throwCount;
      }
    }
    if (guards != 1 || throwCount != 1) throw new IllegalStateException("guard/throw=" + guards + "/" + throwCount);
    return 1;
  }
  private static int patchActor(MethodNode m) {
    if (!m.name.equals("run") || !m.desc.equals("()V")) return 0;
    InsnList h = new InsnList();
    h.add(new VarInsnNode(ALOAD, 0)); h.add(new FieldInsnNode(GETFIELD, ACTOR, "dn", "L" + DN + ";"));
    h.add(new VarInsnNode(ALOAD, 0)); h.add(new FieldInsnNode(GETFIELD, ACTOR, "bpos", "L" + BPOS + ";"));
    h.add(new VarInsnNode(ALOAD, 0)); h.add(new FieldInsnNode(GETFIELD, ACTOR, "serviceId", "Ljava/lang/String;"));
    h.add(new VarInsnNode(ALOAD, 0)); h.add(new FieldInsnNode(GETFIELD, ACTOR, "nnAddr", "Ljava/net/InetSocketAddress;"));
    h.add(call("enterActor", "(L" + DN + ";L" + BPOS + ";Ljava/lang/String;Ljava/net/InetSocketAddress;)V"));
    m.instructions.insert(h);
    int exits = 0;
    for (AbstractInsnNode n = m.instructions.getFirst(); n != null; n = n.getNext())
      if (n.getOpcode() == RETURN) { m.instructions.insertBefore(n, call("exitActor", "()V")); ++exits; }
    if (exits == 0) throw new IllegalStateException("BP actor exit absent");
    return 1;
  }
  private static int patchManager(MethodNode m) {
    if (!m.name.equals("addBlockPool") && !m.name.equals("remove")) return 0;
    Type[] args = Type.getArgumentTypes(m.desc);
    if (args.length != 1 || !args[0].getDescriptor().equals("L" + BPOS + ";")) return 0;
    InsnList h = new InsnList(); h.add(new VarInsnNode(ALOAD, 0)); h.add(new VarInsnNode(ALOAD, 1));
    h.add(call(m.name.equals("remove") ? "poolRemove" : "poolAdd",
        "(L" + MANAGER + ";L" + BPOS + ";)V"));
    m.instructions.insert(h); return 1;
  }
  private static int patchClient(MethodNode m) {
    if (!m.name.equals("getRpcResponse") || !m.desc.startsWith("(Lorg/apache/hadoop/ipc/Client$Call;Lorg/apache/hadoop/ipc/Client$Connection;")) return 0;
    InsnList h = new InsnList(); h.add(new VarInsnNode(ALOAD, 2));
    h.add(new MethodInsnNode(INVOKEVIRTUAL, CLIENT + "$Connection", "getRemoteAddress",
        "()Ljava/net/InetSocketAddress;", false));
    h.add(call("rpcResponse", "(Ljava/net/InetSocketAddress;)V"));
    m.instructions.insert(h); return 1;
  }
  private static int patchDataset(MethodNode m) {
    int block = -1;
    if (m.name.equals("createRbw") && Type.getArgumentTypes(m.desc).length == 5) block = 3;
    if (m.name.equals("createTemporary") && Type.getArgumentTypes(m.desc).length == 4) block = 3;
    if (m.name.equals("finalizeBlock") && Type.getArgumentTypes(m.desc).length == 2) block = 1;
    if (block < 0) return 0;
    InsnList h = new InsnList(); h.add(new VarInsnNode(ALOAD, 0));
    h.add(new VarInsnNode(ALOAD, block)); h.add(new LdcInsnNode(m.name));
    h.add(call("fileIO", "(Ljava/lang/Object;Lorg/apache/hadoop/hdfs/protocol/ExtendedBlock;Ljava/lang/String;)V"));
    m.instructions.insert(h); return 1;
  }
  public static void main(String[] args) throws Exception {
    if (args.length != 3) throw new IllegalArgumentException("input internalName overlay");
    ClassNode node = new ClassNode();
    new ClassReader(Files.readAllBytes(Paths.get(args[0]))).accept(node, 0);
    if (!node.name.equals(args[1])) throw new IllegalStateException("class mismatch");
    int count = 0;
    for (MethodNode m : node.methods) {
      int added = 0;
      if (node.name.equals(CLUSTER)) added = patchCluster(m);
      else if (node.name.equals(DN)) added = patchDataNode(m);
      else if (node.name.equals(ACTOR)) added = patchActor(m);
      else if (node.name.equals(MANAGER)) added = patchManager(m);
      else if (node.name.equals(CLIENT)) added = patchClient(m);
      else if (node.name.equals(DATASET)) added = patchDataset(m);
      count += added;
      if (added != 0) System.out.println(node.name + " " + m.name + m.desc + " hooks=" + added);
    }
    int expected = node.name.equals(CLUSTER) ? 3 : node.name.equals(DN) ? 4
        : node.name.equals(MANAGER) ? 2 : node.name.equals(DATASET) ? 3 : 1;
    if (count != expected) throw new IllegalStateException(node.name + " hooks=" + count + " expected=" + expected);
    ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
    node.accept(writer);
    Path output = Paths.get(args[2], node.name + ".class");
    Files.createDirectories(output.getParent()); Files.write(output, writer.toByteArray());
    System.out.println(node.name + " hooks=" + count);
  }
}
