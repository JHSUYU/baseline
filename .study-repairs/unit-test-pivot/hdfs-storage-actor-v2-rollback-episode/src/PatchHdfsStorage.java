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

/** Offline ASM hooks at exact storage guards and observed file/RPC I/O. */
public final class PatchHdfsStorage implements Opcodes {
  private static final String PROBE = "HdfsStorageProbe";
  private static final String BP = "org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage";
  private static final String DATA = "org/apache/hadoop/hdfs/server/datanode/DataStorage";
  private static final String RPC = "org/apache/hadoop/ipc/Client";
  private static final String DN = "org/apache/hadoop/hdfs/server/datanode/DataNode";
  private static final String ACTOR = "org/apache/hadoop/hdfs/server/datanode/BPServiceActor";
  private static final String CLUSTER = "org/apache/hadoop/hdfs/MiniDFSCluster";
  private static final String SD = "Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;";

  private static MethodInsnNode call(String name, String desc) {
    return new MethodInsnNode(INVOKESTATIC, PROBE, name, desc, false);
  }

  private static void addStorageEntry(MethodNode method, int local) {
    InsnList hook = new InsnList();
    hook.add(new VarInsnNode(ALOAD, local));
    hook.add(call("enterStorage", "(" + SD + ")V"));
    method.instructions.insert(hook);
  }

  private static int patchCluster(MethodNode method) {
    if (!method.name.equals("startDataNodes") || Type.getArgumentTypes(method.desc).length != 15)
      return 0;
    method.instructions.insert(call("startEpisode", "()V"));
    int exits = 0;
    for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; insn = insn.getNext()) {
      if (insn.getOpcode() == RETURN) {
        method.instructions.insertBefore(insn, call("endEpisode", "()V"));
        exits++;
      }
    }
    if (exits == 0) throw new IllegalStateException("MiniDFSCluster missing exit");
    return 1;
  }

  private static int patchDataNode(MethodNode method) {
    if (method.name.equals("<init>")) {
      int starts = 0;
      for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; insn = insn.getNext()) {
        if (!(insn instanceof MethodInsnNode)) continue;
        MethodInsnNode site = (MethodInsnNode) insn;
        if (!site.owner.equals(DN) || !site.name.equals("startDataNode")) continue;
        // Constructor-local configuration is still on the MiniDFSCluster startup thread.
        // Register before startDataNode creates and starts the BPServiceActor thread.
        InsnList hook = new InsnList();
        hook.add(new VarInsnNode(ALOAD, 0));
        hook.add(new VarInsnNode(ALOAD, 1));
        hook.add(call("registerDataNode", "(Lorg/apache/hadoop/hdfs/server/datanode/DataNode;"
            + "Lorg/apache/hadoop/conf/Configuration;)Lorg/apache/hadoop/hdfs/server/datanode/DataNode;"));
        hook.add(new InsnNode(POP));
        method.instructions.insertBefore(insn, hook);
        starts++;
      }
      return starts;
    }
    if (!method.name.equals("instantiateDataNode") || Type.getArgumentTypes(method.desc).length != 3)
      return 0;
    int returns = 0;
    for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; insn = insn.getNext()) {
      if (insn.getOpcode() == ARETURN) {
        InsnList hook = new InsnList();
        hook.add(new VarInsnNode(ALOAD, 1));
        hook.add(call("registerDataNode", "(Lorg/apache/hadoop/hdfs/server/datanode/DataNode;"
            + "Lorg/apache/hadoop/conf/Configuration;)Lorg/apache/hadoop/hdfs/server/datanode/DataNode;"));
        method.instructions.insertBefore(insn, hook);
        returns++;
      }
    }
    if (returns == 0) throw new IllegalStateException("DataNode registration return missing");
    return 1;
  }

  private static int patchActor(MethodNode method) {
    if (!method.name.equals("run") || !method.desc.equals("()V")) return 0;
    InsnList entry = new InsnList();
    entry.add(new VarInsnNode(ALOAD, 0));
    entry.add(new FieldInsnNode(GETFIELD, ACTOR, "dn", "Lorg/apache/hadoop/hdfs/server/datanode/DataNode;"));
    entry.add(new VarInsnNode(ALOAD, 0));
    entry.add(new FieldInsnNode(GETFIELD, ACTOR, "nnAddr", "Ljava/net/InetSocketAddress;"));
    entry.add(call("enterActor", "(Lorg/apache/hadoop/hdfs/server/datanode/DataNode;"
        + "Ljava/net/InetSocketAddress;)V"));
    method.instructions.insert(entry);
    int exits = 0;
    for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; insn = insn.getNext()) {
      if (insn.getOpcode() == RETURN) {
        method.instructions.insertBefore(insn, call("exitActor", "()V"));
        exits++;
      }
    }
    if (exits == 0) throw new IllegalStateException("BPServiceActor missing exit");
    return 1;
  }

  private static int patchRpc(MethodNode method) {
    if (!method.name.equals("getRpcResponse")
        || !method.desc.startsWith("(Lorg/apache/hadoop/ipc/Client$Call;"
            + "Lorg/apache/hadoop/ipc/Client$Connection;")) return 0;
    InsnList entry = new InsnList();
    entry.add(new VarInsnNode(ALOAD, 2));
    entry.add(new MethodInsnNode(INVOKEVIRTUAL, "org/apache/hadoop/ipc/Client$Connection",
        "getRemoteAddress", "()Ljava/net/InetSocketAddress;", false));
    entry.add(call("ipcResponse", "(Ljava/net/InetSocketAddress;)V"));
    method.instructions.insert(entry);
    return 1;
  }

  private static int patchDoTransition(MethodNode method) {
    int namespaceCheck = 0, blockpoolCheck = 0, namespaceThrow = 0,
        blockpoolThrow = 0, reads = 0, layoutCheck = 0, ctimeCheck = 0,
        transitionThrow = 0, line = -1;
    for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; ) {
      AbstractInsnNode next = insn.getNext();
      if (insn instanceof LineNumberNode) line = ((LineNumberNode) insn).line;
      if (insn instanceof JumpInsnNode && insn.getOpcode() == IF_ICMPEQ && line == 392) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP2));
        hook.add(call("namespaceCheck", "(II)V"));
        method.instructions.insertBefore(insn, hook);
        namespaceCheck++;
      }
      if (insn instanceof JumpInsnNode && insn.getOpcode() == IFNE && line == 398) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(call("blockpoolCheck", "(I)V"));
        method.instructions.insertBefore(insn, hook);
        blockpoolCheck++;
      }
      if (insn instanceof JumpInsnNode && insn.getOpcode() == IF_ICMPGT && line == 414) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP2));
        hook.add(call("transitionLayoutCheck", "(II)V"));
        method.instructions.insertBefore(insn, hook);
        layoutCheck++;
      }
      if (insn instanceof JumpInsnNode && insn.getOpcode() == IFGE && line == 415) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(call("transitionCTimeCheck", "(I)V"));
        method.instructions.insertBefore(insn, hook);
        ctimeCheck++;
      }
      if (insn.getOpcode() == ATHROW && (line == 396 || line == 401)) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(new LdcInsnNode(line == 396 ? "HDFS-22" : "HDFS-23"));
        hook.add(new InsnNode(SWAP));
        hook.add(call("targetThrow", "(Ljava/lang/String;Ljava/lang/Throwable;)V"));
        method.instructions.insertBefore(insn, hook);
        if (line == 396) namespaceThrow++; else blockpoolThrow++;
      }
      if (insn.getOpcode() == ATHROW && line == 424) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(new LdcInsnNode("HDFS-24"));
        hook.add(new InsnNode(SWAP));
        hook.add(call("targetThrow", "(Ljava/lang/String;Ljava/lang/Throwable;)V"));
        method.instructions.insertBefore(insn, hook);
        transitionThrow++;
      }
      if (insn instanceof MethodInsnNode) {
        MethodInsnNode site = (MethodInsnNode) insn;
        if (site.name.equals("readProperties")
            && site.desc.equals("(Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;)V")
            && line == 388) {
          InsnList hook = new InsnList();
          hook.add(new VarInsnNode(ALOAD, 1));
          hook.add(call("versionRead", "(Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;)V"));
          method.instructions.insertBefore(insn, hook);
          reads++;
        }
      }
      insn = next;
    }
    if (namespaceCheck != 1 || blockpoolCheck != 1 || namespaceThrow != 1
        || blockpoolThrow != 1 || reads != 1 || layoutCheck != 1
        || ctimeCheck != 1 || transitionThrow != 1)
      throw new IllegalStateException("doTransition hooks=" + namespaceCheck + "/"
          + blockpoolCheck + "/" + namespaceThrow + "/" + blockpoolThrow + "/" + reads
          + "/" + layoutCheck + "/" + ctimeCheck + "/" + transitionThrow);
    return namespaceCheck + blockpoolCheck + namespaceThrow + blockpoolThrow + reads
        + layoutCheck + ctimeCheck + transitionThrow;
  }

  private static int patchDoRollback(MethodNode method) {
    int layoutCheck = 0, ctimeCheck = 0, throwsFound = 0, reads = 0, line = -1;
    for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; ) {
      AbstractInsnNode next = insn.getNext();
      if (insn instanceof LineNumberNode) line = ((LineNumberNode) insn).line;
      if (insn instanceof JumpInsnNode && insn.getOpcode() == IF_ICMPLT && line == 619) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP2));
        hook.add(call("rollbackLayoutCheck", "(II)V"));
        method.instructions.insertBefore(insn, hook);
        layoutCheck++;
      }
      if (insn instanceof JumpInsnNode && insn.getOpcode() == IFLE && line == 620) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(call("rollbackCTimeCheck", "(I)V"));
        method.instructions.insertBefore(insn, hook);
        ctimeCheck++;
      }
      if (insn.getOpcode() == ATHROW && line == 626) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(new LdcInsnNode("HDFS-26"));
        hook.add(new InsnNode(SWAP));
        hook.add(call("targetThrow", "(Ljava/lang/String;Ljava/lang/Throwable;)V"));
        method.instructions.insertBefore(insn, hook);
        throwsFound++;
      }
      if (insn instanceof MethodInsnNode) {
        MethodInsnNode site = (MethodInsnNode) insn;
        if (site.name.equals("readPreviousVersionProperties") && line == 612) {
          InsnList hook = new InsnList();
          hook.add(new VarInsnNode(ALOAD, 1));
          hook.add(call("previousVersionRead",
              "(Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;)V"));
          method.instructions.insertBefore(insn, hook);
          reads++;
        }
      }
      insn = next;
    }
    if (layoutCheck != 1 || ctimeCheck != 1 || throwsFound != 1 || reads != 1)
      throw new IllegalStateException("doRollback hooks=" + layoutCheck + "/"
          + ctimeCheck + "/" + throwsFound + "/" + reads);
    return layoutCheck + ctimeCheck + throwsFound + reads;
  }

  private static int patchDoUpgradeNamespace(MethodNode method) {
    int checks = 0, throwsFound = 0, line = -1;
    for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; ) {
      AbstractInsnNode next = insn.getNext();
      if (insn instanceof LineNumberNode) line = ((LineNumberNode) insn).line;
      if (insn instanceof JumpInsnNode && insn.getOpcode() == IF_ICMPEQ && line == 510) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP2));
        hook.add(call("upgradeNamespaceCheck", "(II)V"));
        method.instructions.insertBefore(insn, hook);
        checks++;
      }
      if (insn.getOpcode() == ATHROW && line == 510) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(new LdcInsnNode("HDFS-27"));
        hook.add(new InsnNode(SWAP));
        hook.add(call("targetThrow", "(Ljava/lang/String;Ljava/lang/Throwable;)V"));
        method.instructions.insertBefore(insn, hook);
        throwsFound++;
      }
      insn = next;
    }
    if (checks != 1 || throwsFound != 1)
      throw new IllegalStateException("doUpgradeNamespace hooks=" + checks + "/" + throwsFound);
    return checks + throwsFound;
  }

  private static int patchLoadStorageDirectory(MethodNode method) {
    int checks = 0, throwsFound = 0, line = -1;
    for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; ) {
      AbstractInsnNode next = insn.getNext();
      if (insn instanceof LineNumberNode) line = ((LineNumberNode) insn).line;
      if (insn instanceof JumpInsnNode && insn.getOpcode() == IFEQ && line == 184) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(call("ctimeCheck", "(I)V"));
        method.instructions.insertBefore(insn, hook);
        checks++;
      }
      if (insn.getOpcode() == ATHROW && line == 186) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(new LdcInsnNode("HDFS-25"));
        hook.add(new InsnNode(SWAP));
        hook.add(call("targetThrow", "(Ljava/lang/String;Ljava/lang/Throwable;)V"));
        method.instructions.insertBefore(insn, hook);
        throwsFound++;
      }
      insn = next;
    }
    if (checks != 1 || throwsFound != 1)
      throw new IllegalStateException("loadStorageDirectory hooks=" + checks + "/" + throwsFound);
    return checks + throwsFound;
  }

  private static int patchDataStorage(MethodNode method) {
    int namespaceCheck = 0, clusterCheck = 0, namespaceThrow = 0,
        clusterThrow = 0, reads = 0, line = -1;
    for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; ) {
      AbstractInsnNode next = insn.getNext();
      if (insn instanceof LineNumberNode) line = ((LineNumberNode) insn).line;
      if (insn instanceof JumpInsnNode && insn.getOpcode() == IF_ICMPEQ && line == 740) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP2));
        hook.add(call("storageNamespaceCheck", "(II)V"));
        method.instructions.insertBefore(insn, hook);
        namespaceCheck++;
      }
      if (insn instanceof JumpInsnNode && insn.getOpcode() == IFNE && line == 749) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(call("clusterCheck", "(I)V"));
        method.instructions.insertBefore(insn, hook);
        clusterCheck++;
      }
      if (insn.getOpcode() == ATHROW && (line == 744 || line == 752)) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(new LdcInsnNode(line == 744 ? "HDFS-34" : "HDFS-35"));
        hook.add(new InsnNode(SWAP));
        hook.add(call("targetThrow", "(Ljava/lang/String;Ljava/lang/Throwable;)V"));
        method.instructions.insertBefore(insn, hook);
        if (line == 744) namespaceThrow++; else clusterThrow++;
      }
      if (insn instanceof MethodInsnNode) {
        MethodInsnNode site = (MethodInsnNode) insn;
        if (site.name.equals("readProperties")
            && site.desc.equals("(Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;)V")
            && line == 729) {
          InsnList hook = new InsnList();
          hook.add(new VarInsnNode(ALOAD, 1));
          hook.add(call("dataVersionRead", "(Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;)V"));
          method.instructions.insertBefore(insn, hook);
          reads++;
        }
      }
      insn = next;
    }
    if (namespaceCheck != 1 || clusterCheck != 1 || namespaceThrow != 1
        || clusterThrow != 1 || reads != 1)
      throw new IllegalStateException("DataStorage.doTransition hooks=" + namespaceCheck + "/"
          + clusterCheck + "/" + namespaceThrow + "/" + clusterThrow + "/" + reads);
    return namespaceCheck + clusterCheck + namespaceThrow + clusterThrow + reads;
  }

  private static int patchDataRollback(MethodNode method) {
    int layoutCheck = 0, ctimeCheck = 0, throwsFound = 0, reads = 0, line = -1;
    for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; ) {
      AbstractInsnNode next = insn.getNext();
      if (insn instanceof LineNumberNode) line = ((LineNumberNode) insn).line;
      if (insn instanceof JumpInsnNode && insn.getOpcode() == IF_ICMPLT && line == 940) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP2));
        hook.add(call("dataRollbackLayoutCheck", "(II)V"));
        method.instructions.insertBefore(insn, hook);
        layoutCheck++;
      }
      if (insn instanceof JumpInsnNode && insn.getOpcode() == IFLE && line == 941) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(call("dataRollbackCTimeCheck", "(I)V"));
        method.instructions.insertBefore(insn, hook);
        ctimeCheck++;
      }
      if (insn.getOpcode() == ATHROW && line == 947) {
        InsnList hook = new InsnList();
        hook.add(new InsnNode(DUP));
        hook.add(new LdcInsnNode("HDFS-37"));
        hook.add(new InsnNode(SWAP));
        hook.add(call("targetThrow", "(Ljava/lang/String;Ljava/lang/Throwable;)V"));
        method.instructions.insertBefore(insn, hook);
        throwsFound++;
      }
      if (insn instanceof MethodInsnNode) {
        MethodInsnNode site = (MethodInsnNode) insn;
        if (site.name.equals("readPreviousVersionProperties") && line == 935) {
          InsnList hook = new InsnList();
          hook.add(new VarInsnNode(ALOAD, 1));
          hook.add(call("dataPreviousVersionRead",
              "(Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;)V"));
          method.instructions.insertBefore(insn, hook);
          reads++;
        }
      }
      insn = next;
    }
    if (layoutCheck != 1 || ctimeCheck != 1 || throwsFound != 1 || reads != 1)
      throw new IllegalStateException("DataStorage.doRollback hooks=" + layoutCheck + "/"
          + ctimeCheck + "/" + throwsFound + "/" + reads);
    return layoutCheck + ctimeCheck + throwsFound + reads;
  }

  public static void main(String[] args) throws Exception {
    if (args.length != 3) throw new IllegalArgumentException("input.class className outDir");
    ClassNode node = new ClassNode();
    new ClassReader(Files.readAllBytes(Paths.get(args[0]))).accept(node, 0);
    if (!node.name.equals(args[1])) throw new IllegalArgumentException("class name mismatch");
    int count = 0;
    for (MethodNode method : node.methods) {
      if (node.name.equals(BP) && method.name.equals("doTransition")
          && method.desc.equals("(Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;"
              + "Lorg/apache/hadoop/hdfs/server/protocol/NamespaceInfo;"
              + "Lorg/apache/hadoop/hdfs/server/common/HdfsServerConstants$StartupOption;"
              + "Ljava/util/List;Lorg/apache/hadoop/conf/Configuration;)Z"))
      {
        count += patchDoTransition(method);
        addStorageEntry(method, 1);
        count++;
      }
      if (node.name.equals(BP) && method.name.equals("doRollback")
          && method.desc.equals("(Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;"
              + "Lorg/apache/hadoop/hdfs/server/protocol/NamespaceInfo;)V"))
      {
        count += patchDoRollback(method);
        addStorageEntry(method, 1);
        count++;
      }
      if (node.name.equals(BP) && method.name.equals("doUpgrade")
          && method.desc.equals("(Ljava/lang/String;"
              + "Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;"
              + "Lorg/apache/hadoop/hdfs/server/protocol/NamespaceInfo;"
              + "Ljava/io/File;Ljava/io/File;Ljava/io/File;I"
              + "Lorg/apache/hadoop/conf/Configuration;)V"))
      {
        count += patchDoUpgradeNamespace(method);
        addStorageEntry(method, 2);
        count++;
      }
      if (node.name.equals(BP) && method.name.equals("loadStorageDirectory")
          && method.desc.equals("(Lorg/apache/hadoop/hdfs/server/protocol/NamespaceInfo;"
              + "Lorg/apache/hadoop/hdfs/server/datanode/StorageLocation;"
              + "Lorg/apache/hadoop/hdfs/server/common/HdfsServerConstants$StartupOption;"
              + "Ljava/util/List;Lorg/apache/hadoop/conf/Configuration;)"
              + "Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;"))
        count += patchLoadStorageDirectory(method);
      if (node.name.equals(DATA) && method.name.equals("doTransition")
          && method.desc.equals("(Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;"
              + "Lorg/apache/hadoop/hdfs/server/protocol/NamespaceInfo;"
              + "Lorg/apache/hadoop/hdfs/server/common/HdfsServerConstants$StartupOption;"
              + "Ljava/util/List;Lorg/apache/hadoop/conf/Configuration;)Z"))
      {
        count += patchDataStorage(method);
        addStorageEntry(method, 1);
        count++;
      }
      if (node.name.equals(DATA) && method.name.equals("doRollback")
          && method.desc.equals("(Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;"
              + "Lorg/apache/hadoop/hdfs/server/protocol/NamespaceInfo;)V"))
      {
        count += patchDataRollback(method);
        addStorageEntry(method, 1);
        count++;
      }
      if (node.name.equals(RPC)) count += patchRpc(method);
      if (node.name.equals(DN)) count += patchDataNode(method);
      if (node.name.equals(ACTOR)) count += patchActor(method);
      if (node.name.equals(CLUSTER)) count += patchCluster(method);
    }
    int expected = node.name.equals(BP) ? 19 : node.name.equals(DATA) ? 11
        : node.name.equals(DN) ? 2 : 1;
    if (count != expected) throw new IllegalStateException(node.name + " hooks=" + count);
    ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
    node.accept(writer);
    Path output = Paths.get(args[2], node.name + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(output);
  }
}
