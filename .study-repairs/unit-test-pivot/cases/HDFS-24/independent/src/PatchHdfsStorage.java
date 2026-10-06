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

  private static MethodInsnNode call(String name, String desc) {
    return new MethodInsnNode(INVOKESTATIC, PROBE, name, desc, false);
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
        count += patchDoTransition(method);
      if (node.name.equals(BP) && method.name.equals("doRollback")
          && method.desc.equals("(Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;"
              + "Lorg/apache/hadoop/hdfs/server/protocol/NamespaceInfo;)V"))
        count += patchDoRollback(method);
      if (node.name.equals(BP) && method.name.equals("doUpgrade")
          && method.desc.equals("(Ljava/lang/String;"
              + "Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;"
              + "Lorg/apache/hadoop/hdfs/server/protocol/NamespaceInfo;"
              + "Ljava/io/File;Ljava/io/File;Ljava/io/File;I"
              + "Lorg/apache/hadoop/conf/Configuration;)V"))
        count += patchDoUpgradeNamespace(method);
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
        count += patchDataStorage(method);
      if (node.name.equals(RPC) && method.name.equals("getRpcResponse")) {
        method.instructions.insert(call("ipcResponse", "()V"));
        count++;
      }
    }
    int expected = node.name.equals(BP) ? 16 : node.name.equals(DATA) ? 5 : 1;
    if (count != expected) throw new IllegalStateException(node.name + " hooks=" + count);
    ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
    node.accept(writer);
    Path output = Paths.get(args[2], node.name + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(output);
  }
}
