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

/** Patch only observed target guards, an RPC call door, and DN identities. */
public final class PatchRecovery implements Opcodes {
  private static final String WORKER =
      "org/apache/hadoop/hdfs/server/datanode/BlockRecoveryWorker";
  private static final String TASK = WORKER + "$RecoveryTaskContiguous";
  private static final String RECORD = WORKER + "$BlockRecord";
  private static final String CLUSTER = "org/apache/hadoop/hdfs/MiniDFSCluster";
  private static final String IPC = "org/apache/hadoop/ipc/Client$Connection";
  private static final String DATASET =
      "org/apache/hadoop/hdfs/server/datanode/fsdataset/impl/FsDatasetImpl";
  private static final String DATANODE =
      "Lorg/apache/hadoop/hdfs/server/datanode/DataNode;";
  private static final String BLOCK = "Lorg/apache/hadoop/hdfs/protocol/ExtendedBlock;";
  private static final String BPOS =
      "Lorg/apache/hadoop/hdfs/server/datanode/BPOfferService;";

  private static InsnList datanodeFromWorker() {
    InsnList code = new InsnList();
    code.add(new VarInsnNode(ALOAD, 0));
    code.add(new FieldInsnNode(GETFIELD, WORKER, "datanode", DATANODE));
    return code;
  }

  private static void targetCheck(MethodNode method, AbstractInsnNode before,
                                  int caseNumber, int valueLocal) {
    InsnList hook = new InsnList();
    hook.add(new LdcInsnNode(caseNumber));
    hook.add(new VarInsnNode(ALOAD, 1));
    hook.add(new VarInsnNode(ALOAD, valueLocal));
    hook.add(datanodeFromWorker());
    hook.add(new MethodInsnNode(INVOKESTATIC, "RecoveryProbe", "targetCheck",
        "(ILjava/lang/String;Ljava/lang/Object;" + DATANODE + ")V", false));
    method.instructions.insertBefore(before, hook);
  }

  private static void targetThrow(MethodNode method, AbstractInsnNode before,
                                  int caseNumber) {
    InsnList hook = new InsnList();
    hook.add(new InsnNode(DUP));
    hook.add(new LdcInsnNode(caseNumber));
    hook.add(new InsnNode(SWAP));
    hook.add(new MethodInsnNode(INVOKESTATIC, "RecoveryProbe", "targetThrow",
        "(ILjava/lang/Throwable;)V", false));
    method.instructions.insertBefore(before, hook);
  }

  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("input class, overlay root");
    ClassNode node = new ClassNode();
    new ClassReader(Files.readAllBytes(Paths.get(args[0]))).accept(node, 0);
    int checks = 0, throwsFound = 0, initDoors = 0, contexts = 0;
    int registrations = 0, physicalIpcDoors = 0, commitLabels = 0;
    int updateLabels = 0, serverContexts = 0, fileHooks = 0;
    for (MethodNode method : node.methods) {
      if (node.name.equals(DATASET) && method.name.equals("initReplicaRecovery")
          && method.desc.equals("(Lorg/apache/hadoop/hdfs/server/protocol/BlockRecoveryCommand$RecoveringBlock;)Lorg/apache/hadoop/hdfs/server/protocol/ReplicaRecoveryInfo;")) {
        InsnList hook = new InsnList();
        hook.add(new VarInsnNode(ALOAD, 1));
        hook.add(new VarInsnNode(ALOAD, 0));
        hook.add(new FieldInsnNode(GETFIELD, DATASET, "datanode", DATANODE));
        hook.add(new MethodInsnNode(INVOKESTATIC, "RecoveryProbe", "beginServerRecovery",
            "(Lorg/apache/hadoop/hdfs/server/protocol/BlockRecoveryCommand$RecoveringBlock;"
                + DATANODE + ")V", false));
        method.instructions.insertBefore(method.instructions.getFirst(), hook);
        serverContexts++;
      }
      if (node.name.equals(DATASET) && method.name.equals("checkReplicaFiles")
          && method.desc.equals("(Lorg/apache/hadoop/hdfs/server/datanode/ReplicaInfo;)V")) {
        int line = -1;
        for (AbstractInsnNode instruction = method.instructions.getFirst();
             instruction != null; ) {
          AbstractInsnNode next = instruction.getNext();
          if (instruction instanceof LineNumberNode)
            line = ((LineNumberNode) instruction).line;
          if (instruction instanceof MethodInsnNode) {
            MethodInsnNode invoke = (MethodInsnNode) instruction;
            if (invoke.owner.equals("org/apache/hadoop/hdfs/server/datanode/ReplicaInfo")
                && (invoke.name.equals("blockDataExists")
                    || invoke.name.equals("getBlockDataLength")
                    || invoke.name.equals("metadataExists")
                    || invoke.name.equals("getMetadataLength"))) {
              InsnList hook = new InsnList();
              hook.add(new VarInsnNode(ALOAD, 0));
              hook.add(new LdcInsnNode(invoke.name + "-L" + line));
              hook.add(new MethodInsnNode(INVOKESTATIC, "RecoveryProbe", "ioFileCheck",
                  "(Lorg/apache/hadoop/hdfs/server/datanode/ReplicaInfo;Ljava/lang/String;)V",
                  false));
              method.instructions.insertBefore(instruction, hook);
              fileHooks++;
            }
          }
          instruction = next;
        }
      }
      if (node.name.equals(RECORD)
          && method.name.equals("updateReplicaUnderRecovery")) {
        for (AbstractInsnNode instruction = method.instructions.getFirst();
             instruction != null; instruction = instruction.getNext()) {
          if (!(instruction instanceof MethodInsnNode)) continue;
          MethodInsnNode invoke = (MethodInsnNode) instruction;
          if (!invoke.owner.equals("org/apache/hadoop/hdfs/server/protocol/InterDatanodeProtocol")
              || !invoke.name.equals("updateReplicaUnderRecovery")) continue;
          InsnList hook = new InsnList();
          hook.add(new MethodInsnNode(INVOKESTATIC, "RecoveryProbe", "markUpdateRpc",
              "()V", false));
          method.instructions.insertBefore(instruction, hook);
          updateLabels++;
        }
      }
      if (node.name.equals(IPC) && method.name.equals("sendRpcRequest")
          && method.desc.equals("(Lorg/apache/hadoop/ipc/Client$Call;)V")) {
        InsnList hook = new InsnList();
        hook.add(new MethodInsnNode(INVOKESTATIC, "RecoveryProbe", "ioHadoopIpc",
            "()V", false));
        method.instructions.insertBefore(method.instructions.getFirst(), hook);
        physicalIpcDoors++;
      }
      if (node.name.equals(CLUSTER) && method.name.equals("waitActive")
          && method.desc.equals("()V")) {
        for (AbstractInsnNode instruction = method.instructions.getFirst();
             instruction != null; instruction = instruction.getNext()) {
          if (instruction.getOpcode() != RETURN) continue;
          InsnList hook = new InsnList();
          hook.add(new VarInsnNode(ALOAD, 0));
          hook.add(new MethodInsnNode(INVOKESTATIC, "RecoveryProbe", "registerCluster",
              "(Lorg/apache/hadoop/hdfs/MiniDFSCluster;)V", false));
          method.instructions.insertBefore(instruction, hook);
          registrations++;
        }
      }
      if (node.name.equals(TASK) && method.name.equals("recover")
          && method.desc.equals("()V")) {
        InsnList hook = new InsnList();
        hook.add(new VarInsnNode(ALOAD, 0));
        hook.add(new FieldInsnNode(GETFIELD, TASK, "block", BLOCK));
        hook.add(new VarInsnNode(ALOAD, 0));
        hook.add(new FieldInsnNode(GETFIELD, TASK, "recoveryId", "J"));
        hook.add(new VarInsnNode(ALOAD, 0));
        hook.add(new FieldInsnNode(GETFIELD, TASK, "this$0", "L" + WORKER + ";"));
        hook.add(new MethodInsnNode(INVOKESTATIC, WORKER, "access$100",
            "(L" + WORKER + ";)" + DATANODE, false));
        hook.add(new MethodInsnNode(INVOKESTATIC, "RecoveryProbe", "beginRecovery",
            "(" + BLOCK + "J" + DATANODE + ")V", false));
        method.instructions.insertBefore(method.instructions.getFirst(), hook);
        contexts++;
      }
      if (node.name.equals(TASK) && method.name.equals("syncBlock")) {
        for (AbstractInsnNode instruction = method.instructions.getFirst();
             instruction != null; instruction = instruction.getNext()) {
          if (!(instruction instanceof MethodInsnNode)) continue;
          MethodInsnNode invoke = (MethodInsnNode) instruction;
          if (!invoke.name.equals("commitBlockSynchronization")
              || !invoke.owner.equals("org/apache/hadoop/hdfs/protocolPB/DatanodeProtocolClientSideTranslatorPB"))
            continue;
          InsnList hook = new InsnList();
          hook.add(new MethodInsnNode(INVOKESTATIC, "RecoveryProbe", "markCommitRpc",
              "()V", false));
          method.instructions.insertBefore(instruction, hook);
          commitLabels++;
        }
      }
      if (!node.name.equals(WORKER)) continue;
      if (method.name.equals("callInitReplicaRecovery")) {
        for (AbstractInsnNode instruction = method.instructions.getFirst();
             instruction != null; instruction = instruction.getNext()) {
          if (!(instruction instanceof MethodInsnNode)) continue;
          MethodInsnNode invoke = (MethodInsnNode) instruction;
          if (!invoke.owner.equals("org/apache/hadoop/hdfs/server/protocol/InterDatanodeProtocol")
              || !invoke.name.equals("initReplicaRecovery")) continue;
          InsnList hook = new InsnList();
          hook.add(new VarInsnNode(ALOAD, 0));
          hook.add(new MethodInsnNode(INVOKESTATIC, "RecoveryProbe",
              "ioInitReplicaRecovery", "(Ljava/lang/Object;)V", false));
          method.instructions.insertBefore(instruction, hook);
          initDoors++;
        }
      }
      boolean getId = method.name.equals("getDatanodeID")
          && method.desc.startsWith("(Ljava/lang/String;)");
      boolean getActive = method.name.equals("getActiveNamenodeForBP")
          && method.desc.startsWith("(Ljava/lang/String;)");
      if (!getId && !getActive) continue;
      int line = -1;
      for (AbstractInsnNode instruction = method.instructions.getFirst();
           instruction != null; ) {
        AbstractInsnNode next = instruction.getNext();
        if (instruction instanceof LineNumberNode)
          line = ((LineNumberNode) instruction).line;
        if (instruction instanceof JumpInsnNode
            && instruction.getOpcode() == IFNONNULL) {
          if (getId && line == 538) {
            targetCheck(method, instruction, 28, 2);
            checks++;
          } else if (getActive && line == 577) {
            targetCheck(method, instruction, 29, 2);
            checks++;
          } else if (getActive && line == 582) {
            targetCheck(method, instruction, 30, 3);
            checks++;
          }
        }
        if (instruction.getOpcode() == ATHROW) {
          if (getId && line == 539) {
            targetThrow(method, instruction, 28);
            throwsFound++;
          } else if (getActive && line == 578) {
            targetThrow(method, instruction, 29);
            throwsFound++;
          } else if (getActive && line == 583) {
            targetThrow(method, instruction, 30);
            throwsFound++;
          }
        }
        instruction = next;
      }
    }
    if ((node.name.equals(WORKER) && (checks != 3 || throwsFound != 3 || initDoors != 1))
        || (node.name.equals(TASK) && (contexts != 1 || commitLabels != 2))
        || (node.name.equals(RECORD) && updateLabels != 1)
        || (node.name.equals(CLUSTER) && registrations < 1)
        || (node.name.equals(IPC) && physicalIpcDoors != 1)
        || (node.name.equals(DATASET) && (serverContexts != 1 || fileHooks != 5))) {
      throw new IllegalStateException("HDFS recovery hook mismatch: " + node.name
          + " checks=" + checks + " throws=" + throwsFound
          + " initDoors=" + initDoors + " contexts=" + contexts
          + " registrations=" + registrations
          + " physicalIpcDoors=" + physicalIpcDoors
          + " commitLabels=" + commitLabels
          + " updateLabels=" + updateLabels
          + " serverContexts=" + serverContexts
          + " fileHooks=" + fileHooks);
    }
    ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
    node.accept(writer);
    Path output = Paths.get(args[1], node.name + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(output);
  }
}
