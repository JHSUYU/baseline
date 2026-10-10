package edu.uva.liftlab.mallory.adapters.hdfs;

import java.io.IOException;
import java.io.InputStream;
import java.lang.instrument.ClassFileTransformer;
import java.security.ProtectionDomain;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.Type;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.AnnotationNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.InsnList;
import org.objectweb.asm.tree.InsnNode;
import org.objectweb.asm.tree.JumpInsnNode;
import org.objectweb.asm.tree.LabelNode;
import org.objectweb.asm.tree.LdcInsnNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.TryCatchBlockNode;
import org.objectweb.asm.tree.VarInsnNode;

/** Narrow Hadoop hooks; the generic site transformer still handles target/door probes. */
public final class HdfsMiniClusterTransformer implements ClassFileTransformer {
  private static final String HOOKS = Type.getInternalName(HdfsHooks.class);
  private static final String PROBE = "edu/uva/liftlab/mallory/instrumentation/Probe";

  public HdfsMiniClusterTransformer() { }

  @Override public byte[] transform(ClassLoader loader, String name, Class<?> redefined,
                                    ProtectionDomain domain, byte[] bytes) {
    if (!eligible(name)) return null;
    ClassNode clazz = new ClassNode();
    new ClassReader(bytes).accept(clazz, ClassReader.EXPAND_FRAMES);
    boolean changed = false;
    for (MethodNode method : clazz.methods) {
      if (method.instructions.size() == 0) continue;
      if (name.equals("org/apache/hadoop/hdfs/MiniDFSCluster$Builder")
          && method.name.equals("build")
          && method.desc.equals("()Lorg/apache/hadoop/hdfs/MiniDFSCluster;")) {
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          if (instruction.getOpcode() == Opcodes.ARETURN) {
            InsnList hook = new InsnList();
            hook.add(new InsnNode(Opcodes.DUP));
            hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "clusterBuilt",
                "(Ljava/lang/Object;)V", false));
            method.instructions.insertBefore(instruction, hook);
            changed = true;
          }
        }
      } else if (name.equals("org/apache/hadoop/hdfs/MiniDFSCluster")
          && method.name.equals("configureNameService")) {
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          if (!(instruction instanceof MethodInsnNode)) continue;
          MethodInsnNode call = (MethodInsnNode) instruction;
          if (call.getOpcode() != Opcodes.INVOKESTATIC
              || !call.owner.equals("org/apache/hadoop/hdfs/DFSTestUtil")
              || !call.name.equals("formatNameNode")
              || !call.desc.equals("(Lorg/apache/hadoop/conf/Configuration;)V")) continue;
          aroundFormatCall(method, instruction);
          changed = true;
        }
      } else if (name.equals("org/apache/hadoop/hdfs/MiniDFSCluster")
          && method.name.equals("startDataNodes")) {
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          if (!(instruction instanceof MethodInsnNode)) continue;
          MethodInsnNode call = (MethodInsnNode) instruction;
          if (!call.owner.equals("org/apache/hadoop/hdfs/server/datanode/DataNode")
              || !call.name.equals("runDatanodeDaemon") || !call.desc.equals("()V")) continue;
          InsnList hook = new InsnList();
          hook.add(new InsnNode(Opcodes.DUP));
          hook.add(new VarInsnNode(Opcodes.ALOAD, 0));
          hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "dataNodeStarting",
              "(Ljava/lang/Object;Ljava/lang/Object;)V", false));
          method.instructions.insertBefore(instruction, hook);
          changed = true;
        }
      } else if (name.equals("org/apache/hadoop/hdfs/MiniDFSCluster")
          && (method.name.equals("createNameNode")
              || method.name.equals("restartNameNode"))) {
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          if (instruction.getOpcode() != Opcodes.RETURN) continue;
          InsnList hook = new InsnList();
          hook.add(new VarInsnNode(Opcodes.ALOAD, 0));
          hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "nameNodesAvailable",
              "(Ljava/lang/Object;)V", false));
          method.instructions.insertBefore(instruction, hook);
          changed = true;
        }
        if (method.name.equals("createNameNode")) {
          wrap(method, HOOKS, "nameNodeCreationEnter",
              "(Ljava/lang/Object;)L" + HOOKS + "$NameNodeCreationScope;",
              HOOKS + "$NameNodeCreationScope", true);
        }
      } else if (name.equals("org/apache/hadoop/hdfs/server/namenode/FSNamesystem")
          && method.name.equals("<init>")) {
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          if (instruction.getOpcode() != Opcodes.RETURN) continue;
          InsnList hook = new InsnList();
          hook.add(new VarInsnNode(Opcodes.ALOAD, 0));
          hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "namesystemConstructed",
              "(Ljava/lang/Object;)V", false));
          method.instructions.insertBefore(instruction, hook);
          changed = true;
        }
      } else if (name.equals("org/apache/hadoop/hdfs/server/namenode/NameNodeRpcServer")
          && method.name.equals("getDataEncryptionKey")
          && method.desc.equals("()Lorg/apache/hadoop/hdfs/security/token/block/DataEncryptionKey;")) {
        // This RPC method declares IOException. A method-specific entry door
        // stays attached to key issuance even when other RpcCall executions
        // reorder and change the generic call-site door ordinal.
        InsnList hook = new InsnList();
        hook.add(new LdcInsnNode("hdfs:nn-get-data-encryption-key"));
        hook.add(new LdcInsnNode("java.io.IOException"));
        hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, PROBE, "beforeDoor",
            "(Ljava/lang/String;Ljava/lang/String;)V", false));
        method.instructions.insertBefore(method.instructions.getFirst(), hook);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/server/balancer/KeyManager")
          && method.name.equals("<init>")) {
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          if (instruction.getOpcode() != Opcodes.RETURN) continue;
          InsnList hook = new InsnList();
          hook.add(new VarInsnNode(Opcodes.ALOAD, 0));
          hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS,
              "balancerKeyManagerConstructed", "(Ljava/lang/Object;)V", false));
          method.instructions.insertBefore(instruction, hook);
          changed = true;
        }
      } else if (name.equals("org/apache/hadoop/hdfs/server/balancer/KeyManager")
          && method.name.equals("startBlockKeyUpdater") && method.desc.equals("()V")) {
        InsnList hook = new InsnList();
        hook.add(new VarInsnNode(Opcodes.ALOAD, 0));
        hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS,
            "balancerKeyUpdaterSubmitted", "(Ljava/lang/Object;)V", false));
        method.instructions.insertBefore(method.instructions.getFirst(), hook);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/server/balancer/KeyManager$BlockKeyUpdater")
          && method.name.equals("run") && method.desc.equals("()V")) {
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          if (!(instruction instanceof MethodInsnNode)) continue;
          MethodInsnNode call = (MethodInsnNode) instruction;
          if (call.getOpcode() != Opcodes.INVOKEINTERFACE
              || !call.owner.equals("org/apache/hadoop/hdfs/server/protocol/NamenodeProtocol")
              || !call.name.equals("getBlockKeys")
              || !call.desc.equals("()Lorg/apache/hadoop/hdfs/security/token/block/ExportedBlockKeys;"))
            continue;
          InsnList hook = new InsnList();
          hook.add(new LdcInsnNode("hdfs:balancer-refresh-block-keys"));
          hook.add(new LdcInsnNode("java.io.IOException"));
          hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, PROBE, "beforeDoor",
              "(Ljava/lang/String;Ljava/lang/String;)V", false));
          method.instructions.insertBefore(instruction, hook);
          changed = true;
        }
        wrap(method, HOOKS, "balancerKeyUpdaterEnter",
            "(Ljava/lang/Object;)L" + HOOKS + "$BalancerTaskScope;",
            HOOKS + "$BalancerTaskScope", true);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/server/balancer/Dispatcher")
          && method.name.equals("executePendingMove")
          && method.desc.equals("(Lorg/apache/hadoop/hdfs/server/balancer/Dispatcher$PendingMove;)V")) {
        // There is an early return when no move executor can be allocated.
        // Submit only at the actual executor handoff, so this token cannot
        // represent a move that the caller decided to skip.
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          if (!(instruction instanceof MethodInsnNode)) continue;
          MethodInsnNode call = (MethodInsnNode) instruction;
          if (call.getOpcode() != Opcodes.INVOKEINTERFACE
              || !call.owner.equals("java/util/concurrent/ExecutorService")
              || !call.name.equals("execute")
              || !call.desc.equals("(Ljava/lang/Runnable;)V")) continue;
          InsnList hook = new InsnList();
          hook.add(new VarInsnNode(Opcodes.ALOAD, 1));
          hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS,
              "balancerMoveSubmitted", "(Ljava/lang/Object;)V", false));
          method.instructions.insertBefore(instruction, hook);
          changed = true;
        }
      } else if (name.equals("org/apache/hadoop/hdfs/server/balancer/Dispatcher$PendingMove")
          && method.name.equals("dispatch") && method.desc.equals("()V")) {
        wrap(method, HOOKS, "balancerMoveEnter",
            "(Ljava/lang/Object;)L" + HOOKS + "$BalancerTaskScope;",
            HOOKS + "$BalancerTaskScope", true);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/DFSInputStream")
          && method.name.equals("blockSeekTo")
          && method.desc.equals("(J)Lorg/apache/hadoop/hdfs/protocol/DatanodeInfo;")) {
        wrap(method, HOOKS, "clientBlockSeekEnter",
            "(Ljava/lang/Object;)L" + HOOKS + "$ClientOperationScope;",
            HOOKS + "$ClientOperationScope", true);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/qjournal/MiniJournalCluster$Builder")
          && method.name.equals("build")
          && method.desc.equals("()Lorg/apache/hadoop/hdfs/qjournal/MiniJournalCluster;")) {
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          if (instruction.getOpcode() == Opcodes.ARETURN) {
            InsnList hook = new InsnList();
            hook.add(new InsnNode(Opcodes.DUP));
            hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "journalClusterBuilt",
                "(Ljava/lang/Object;)V", false));
            method.instructions.insertBefore(instruction, hook);
            changed = true;
          }
        }
      } else if (name.equals("org/apache/hadoop/hdfs/qjournal/MiniJournalCluster")
          && method.name.equals("restartJournalNode") && method.desc.equals("(I)V")) {
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          if (instruction.getOpcode() == Opcodes.RETURN) {
            InsnList hook = new InsnList();
            hook.add(new VarInsnNode(Opcodes.ALOAD, 0));
            hook.add(new VarInsnNode(Opcodes.ILOAD, 1));
            hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "journalNodeRestarted",
                "(Ljava/lang/Object;I)V", false));
            method.instructions.insertBefore(instruction, hook);
            changed = true;
          }
        }
      } else if (name.equals("org/apache/hadoop/hdfs/qjournal/server/JournalNode")
          && method.name.equals("getOrCreateJournal")
          && method.desc.endsWith(")Lorg/apache/hadoop/hdfs/qjournal/server/Journal;")) {
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          if (instruction.getOpcode() == Opcodes.ARETURN) {
            InsnList hook = new InsnList();
            hook.add(new InsnNode(Opcodes.DUP));
            hook.add(new VarInsnNode(Opcodes.ALOAD, 0));
            hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "journalObtained",
                "(Ljava/lang/Object;Ljava/lang/Object;)V", false));
            method.instructions.insertBefore(instruction, hook);
            changed = true;
          }
        }
      } else if (name.equals("org/apache/hadoop/hdfs/qjournal/server/Journal")
          && (method.access & Opcodes.ACC_STATIC) == 0 && !method.name.startsWith("<")) {
        wrap(method, HOOKS, "journalEnter", "(Ljava/lang/Object;)L" + PROBE + "$NodeScope;",
            PROBE + "$NodeScope", true);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/server/blockmanagement/BlockManager")
          && method.name.equals("enqueueBlockOp")
          && method.desc.equals("(Ljava/lang/Runnable;)V")) {
        InsnList hook = new InsnList();
        hook.add(new VarInsnNode(Opcodes.ALOAD, 0));
        hook.add(new VarInsnNode(Opcodes.ALOAD, 1));
        hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "blockOpSubmitted",
            "(Ljava/lang/Object;Ljava/lang/Object;)V", false));
        method.instructions.insertBefore(method.instructions.getFirst(), hook);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/server/blockmanagement/BlockManager$BlockReportProcessingThread")
          && method.name.equals("processQueue")) {
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          if (!(instruction instanceof MethodInsnNode)) continue;
          MethodInsnNode call = (MethodInsnNode) instruction;
          if (call.getOpcode() != Opcodes.INVOKEINTERFACE
              || !call.owner.equals("java/lang/Runnable")
              || !call.name.equals("run") || !call.desc.equals("()V")) continue;
          AbstractInsnNode previous = instruction.getPrevious();
          if (!(previous instanceof VarInsnNode) || previous.getOpcode() != Opcodes.ALOAD)
            continue;
          aroundBlockOpCall(method, instruction, ((VarInsnNode) previous).var);
          changed = true;
        }
      } else if (name.equals("org/apache/hadoop/hdfs/server/blockmanagement/BlockManager")
          && method.name.equals("processIncrementalBlockReport")
          && (method.access & Opcodes.ACC_PUBLIC) != 0) {
        wrap(method, HOOKS, "blockManagerEnter",
            "(Ljava/lang/Object;)L" + PROBE + "$NodeScope;",
            PROBE + "$NodeScope", true);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/server/namenode/snapshot/FSImageFormatPBSnapshot$Saver")
          && method.name.equals("serializeSnapshotSection")) {
        wrap(method, HOOKS, "snapshotSaverEnter",
            "(Ljava/lang/Object;)L" + PROBE + "$NodeScope;",
            PROBE + "$NodeScope", true);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/server/namenode/FSImage$FSImageSaver")
          && method.name.equals("<init>")) {
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          if (instruction.getOpcode() != Opcodes.RETURN) continue;
          InsnList hook = new InsnList();
          hook.add(new VarInsnNode(Opcodes.ALOAD, 0));
          hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "imageSaverConstructed",
              "(Ljava/lang/Object;)V", false));
          method.instructions.insertBefore(instruction, hook);
          changed = true;
        }
      } else if (name.equals("org/apache/hadoop/hdfs/server/namenode/FSImage$FSImageSaver")
          && method.name.equals("run") && method.desc.equals("()V")) {
        wrap(method, HOOKS, "imageSaverEnter",
            "(Ljava/lang/Object;)L" + HOOKS + "$ImageSaverScope;",
            HOOKS + "$ImageSaverScope", true);
        changed = true;
      } else if (name.equals("org/apache/hadoop/ipc/Server$RpcCall")
          && method.name.equals("run") && method.desc.equals("()Ljava/lang/Void;")) {
        wrap(method, HOOKS, "rpcEnter", "(Ljava/lang/Object;)L" + HOOKS + "$RpcScope;",
            HOOKS + "$RpcScope", true);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/server/datanode/BPServiceActor")
          && method.name.equals("run") && method.desc.equals("()V")) {
        wrap(method, HOOKS, "actorEnter", "(Ljava/lang/Object;)L" + HOOKS + "$ActorScope;",
            HOOKS + "$ActorScope", true);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/server/datanode/BPServiceActor")
          && method.name.equals("connectToNNAndHandshake")) {
        // The namespace reply is consumed before verifyAndSetNamespaceInfo
        // calls DataNode.initBlockPool. Keep that exact reply context across
        // the synchronous initialization path into the storage guards.
        wrap(method, HOOKS, "responseConsumerEnter",
            "(Ljava/lang/Object;)L" + HOOKS + "$ResponseConsumerScope;",
            HOOKS + "$ResponseConsumerScope", true);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/server/datanode/BPServiceActor")
          && method.name.equals("offerService") && method.desc.equals("()V")) {
        // offerService consumes the exact heartbeat reply and immediately
        // enters the updateActorStatesFromHeartbeat target. The reply's actor
        // and correlation must survive sendHeartBeat's return. Close that
        // continuation immediately after the state check, before unrelated
        // report work in the next loop iteration can inherit it.
        int stateChecks = 0;
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          if (!(instruction instanceof MethodInsnNode)) continue;
          MethodInsnNode call = (MethodInsnNode) instruction;
          if (!call.owner.equals("org/apache/hadoop/hdfs/server/datanode/BPOfferService")
              || !call.name.equals("updateActorStatesFromHeartbeat")
              || !call.desc.endsWith(")V")) continue;
          InsnList after = new InsnList();
          after.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS,
              "heartbeatStateUpdated", "()V", false));
          method.instructions.insert(instruction, after);
          stateChecks++;
        }
        if (stateChecks > 0) {
          wrap(method, HOOKS, "heartbeatEnter",
              "(Ljava/lang/Object;)L" + HOOKS + "$HeartbeatScope;",
              HOOKS + "$HeartbeatScope", true);
          changed = true;
        }
      } else if (name.equals("org/apache/hadoop/hdfs/server/datanode/BPServiceActor")
          && method.name.equals("checkNNVersion")) {
        wrap(method, HOOKS, "serviceActorEnter",
            "(Ljava/lang/Object;)L" + PROBE + "$NodeScope;", PROBE + "$NodeScope", true);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/server/datanode/BPOfferService")
          && (method.name.equals("processCommandFromActive")
              || method.name.equals("updateActorStatesFromHeartbeat"))) {
        wrap(method, HOOKS, "offerEnter",
            "(Ljava/lang/Object;)L" + PROBE + "$NodeScope;", PROBE + "$NodeScope", true);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/server/datanode/DataStorage")
          && method.name.equals("getBlockPoolSliceStorage")) {
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          if (instruction.getOpcode() != Opcodes.ARETURN) continue;
          InsnList hook = new InsnList();
          hook.add(new InsnNode(Opcodes.DUP));
          hook.add(new VarInsnNode(Opcodes.ALOAD, 0));
          hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "blockPoolStorageObtained",
              "(Ljava/lang/Object;Ljava/lang/Object;)V", false));
          method.instructions.insertBefore(instruction, hook);
          changed = true;
        }
      } else if (name.equals("org/apache/hadoop/hdfs/server/datanode/DataStorage")
          && method.name.equals("loadBlockPoolSliceStorage")) {
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          if (!(instruction instanceof MethodInsnNode)) continue;
          MethodInsnNode call = (MethodInsnNode) instruction;
          if (call.getOpcode() != Opcodes.INVOKEINTERFACE
              || !call.owner.equals("java/util/concurrent/ExecutorService")
              || !call.name.equals("submit")
              || !call.desc.equals("(Ljava/util/concurrent/Callable;)Ljava/util/concurrent/Future;"))
            continue;
          // Stack before submit is [executor, callable]. Duplicate only the
          // concrete task, so the original invocation remains unchanged.
          InsnList hook = new InsnList();
          hook.add(new InsnNode(Opcodes.DUP));
          hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "storageUpgradeSubmitted",
              "(Ljava/lang/Object;)V", false));
          method.instructions.insertBefore(instruction, hook);
          changed = true;
        }
      } else if (name.equals("org/apache/hadoop/hdfs/server/datanode/DataStorage")
          && method.name.equals("doTransition")) {
        wrap(method, HOOKS, "dataStorageEnter",
            "(Ljava/lang/Object;)L" + PROBE + "$NodeScope;", PROBE + "$NodeScope", true);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage")
          && (method.name.equals("doTransition")
              || method.name.equals("loadStorageDirectory")
              || (method.name.equals("doUpgrade")
                  && method.desc.startsWith("(Ljava/lang/String;")))) {
        // The guard can run after doTransition returns, or inside the queued
        // eight-argument upgrade task on another thread. The registered slice
        // receiver, rather than its caller thread, identifies the DataNode.
        wrap(method, HOOKS, "blockPoolStorageEnter",
            "(Ljava/lang/Object;)L" + PROBE + "$NodeScope;", PROBE + "$NodeScope", true);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage$1")
          && method.name.equals("call")
          && method.desc.equals("()Lorg/apache/hadoop/hdfs/server/common/Storage$StorageDirectory;")) {
        wrap(method, HOOKS, "storageUpgradeEnter",
            "(Ljava/lang/Object;)L" + HOOKS + "$StorageUpgradeScope;",
            HOOKS + "$StorageUpgradeScope", true);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/server/datanode/BlockRecoveryWorker")
          && method.name.equals("recoverBlocks")) {
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          if (!(instruction instanceof MethodInsnNode)) continue;
          MethodInsnNode call = (MethodInsnNode) instruction;
          if (call.getOpcode() != Opcodes.INVOKESPECIAL
              || !call.owner.equals("org/apache/hadoop/util/Daemon")
              || !call.name.equals("<init>")
              || !call.desc.equals("(Ljava/lang/ThreadGroup;Ljava/lang/Runnable;)V"))
            continue;
          // The just-created BlockRecoveryWorker$1 is the constructor's
          // Runnable argument. Preserve the original operand stack.
          InsnList hook = new InsnList();
          hook.add(new InsnNode(Opcodes.DUP));
          hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "blockRecoverySubmitted",
              "(Ljava/lang/Object;)V", false));
          method.instructions.insertBefore(instruction, hook);
          changed = true;
        }
      } else if (name.equals("org/apache/hadoop/hdfs/server/datanode/BlockRecoveryWorker$1")
          && method.name.equals("run") && method.desc.equals("()V")) {
        wrap(method, HOOKS, "blockRecoveryTaskEnter",
            "(Ljava/lang/Object;)L" + HOOKS + "$BlockRecoveryTaskScope;",
            HOOKS + "$BlockRecoveryTaskScope", true);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/server/datanode/BlockRecoveryWorker")
          && (method.name.equals("getActiveNamenodeForBP")
              || method.name.equals("getDatanodeID"))) {
        wrap(method, HOOKS, "blockRecoveryEnter",
            "(Ljava/lang/Object;)L" + PROBE + "$NodeScope;", PROBE + "$NodeScope", true);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/server/datanode/DataStorage$VolumeBuilder")
          && method.name.equals("build")) {
        wrap(method, HOOKS, "volumeBuilderEnter",
            "(Ljava/lang/Object;)L" + PROBE + "$NodeScope;", PROBE + "$NodeScope", true);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/server/datanode/DataXceiver")
          && (method.name.equals("readBlock")
              || (method.name.equals("run") && method.desc.equals("()V")))) {
        // The encrypted SASL handshake runs in DataXceiver.run before an
        // operation is decoded and readBlock is entered. Bind the whole
        // connection worker to its concrete DataNode so secret-key checks in
        // that handshake have a named actor as well.
        wrap(method, HOOKS, "datanodeEnter", "(Ljava/lang/Object;)L" + PROBE + "$NodeScope;",
            PROBE + "$NodeScope", true);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferClient")
          && (method.name.equals("newSocketSend") || method.name.equals("socketSend")
              || method.name.equals("peerSend"))) {
        // The private handshake has no socket source port. Carry the exact
        // endpoints from its public Socket/Peer entry, including nested
        // socketSend overloads, and restore them on every exit.
        wrapArgument(method, HOOKS, "saslClientEnter",
            "(Ljava/lang/Object;)L" + HOOKS + "$SaslClientScope;",
            HOOKS + "$SaslClientScope", 1);
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferClient")
          && method.name.equals("doSaslHandshake")) {
        int joins = 0;
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          if (!(instruction instanceof MethodInsnNode)) continue;
          MethodInsnNode call = (MethodInsnNode) instruction;
          if (!call.name.equals("readSaslMessage")) continue;
          // This read follows every successful first-message send branch.
          // A send recorded here therefore represents flushed message bytes,
          // not merely an attempt to begin negotiation.
          InsnList hook = new InsnList();
          hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS,
              "saslInitialMessageSent", "()V", false));
          method.instructions.insertBefore(instruction, hook);
          joins++;
        }
        if (joins != 1)
          throw new IllegalStateException("Expected one HDFS SASL client initial-message join");
        changed = true;
      } else if (name.equals("org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferServer")
          && method.name.equals("doSaslHandshake")) {
        int reads = 0;
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          if (!(instruction instanceof MethodInsnNode)) continue;
          MethodInsnNode call = (MethodInsnNode) instruction;
          if (!call.name.equals("readSaslMessageWithHandshakeSecret")) continue;
          // The receive scope begins only after the DataNode successfully
          // parses the first protobuf. It encloses the later secret-key check.
          scopeAfterCall(method, instruction, HOOKS, "saslInitialMessageReceived",
              "(Ljava/lang/Object;)L" + PROBE + "$ContextScope;",
              PROBE + "$ContextScope", 1);
          reads++;
        }
        if (reads != 1)
          throw new IllegalStateException("Expected one HDFS SASL server initial-message read");
        changed = true;
      } else if (name.equals("org/apache/hadoop/ipc/Client$Connection")
          && method.name.equals("sendRpcRequest")
          && method.desc.startsWith("(Lorg/apache/hadoop/ipc/Client$Call;)")) {
        InsnList hook = new InsnList();
        hook.add(new VarInsnNode(Opcodes.ALOAD, 0));
        hook.add(new VarInsnNode(Opcodes.ALOAD, 1));
        hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "rpcSend",
            "(Ljava/lang/Object;Ljava/lang/Object;)V", false));
        method.instructions.insertBefore(method.instructions.getFirst(), hook);
        changed = true;
      } else if (name.equals("org/apache/hadoop/ipc/Server$Connection")
          && method.name.equals("sendResponse")
          && method.desc.equals("(Lorg/apache/hadoop/ipc/Server$RpcCall;)V")) {
        InsnList hook = new InsnList();
        hook.add(new VarInsnNode(Opcodes.ALOAD, 1));
        hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "rpcResponseSent",
            "(Ljava/lang/Object;)V", false));
        method.instructions.insertBefore(method.instructions.getFirst(), hook);
        changed = true;
      } else if (name.equals("org/apache/hadoop/ipc/Client")
          && method.name.equals("getRpcResponse")
          && method.desc.equals("(Lorg/apache/hadoop/ipc/Client$Call;"
              + "Lorg/apache/hadoop/ipc/Client$Connection;JLjava/util/concurrent/TimeUnit;)"
              + "Lorg/apache/hadoop/io/Writable;")) {
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          int opcode = instruction.getOpcode();
          if (opcode == Opcodes.ARETURN || opcode == Opcodes.ATHROW) {
            InsnList hook = new InsnList();
            // The return value or thrown exception remains on the stack.
            hook.add(new InsnNode(Opcodes.DUP));
            hook.add(new VarInsnNode(Opcodes.ALOAD, 2));
            hook.add(new VarInsnNode(Opcodes.ALOAD, 1));
            hook.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS,
                opcode == Opcodes.ARETURN ? "rpcResponseConsumed" : "rpcErrorConsumed",
                "(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;)V", false));
            method.instructions.insertBefore(instruction, hook);
            changed = true;
          }
        }
      } else if (name.startsWith("org/apache/hadoop/hdfs/")
          && name.contains("/Test") && hasJUnitTest(method)) {
        wrap(method, HOOKS, "clientEnter",
            "()L" + PROBE + "$NodeScope;", PROBE + "$NodeScope", false);
        changed = true;
      }
    }
    if (!changed) return null;
    try {
      ClassWriter writer = new ResolvingWriter(ClassWriter.COMPUTE_FRAMES | ClassWriter.COMPUTE_MAXS,
          loader, clazz);
      clazz.accept(writer);
      return writer.toByteArray();
    } catch (RuntimeException failure) {
      throw new IllegalStateException("HDFS Mallory adapter could not transform " + name, failure);
    }
  }

  private static boolean eligible(String name) {
    return name != null && (name.equals("org/apache/hadoop/hdfs/MiniDFSCluster$Builder")
        || name.equals("org/apache/hadoop/hdfs/MiniDFSCluster")
        || name.equals("org/apache/hadoop/hdfs/server/namenode/FSNamesystem")
        || name.equals("org/apache/hadoop/hdfs/server/namenode/NameNodeRpcServer")
        || name.equals("org/apache/hadoop/hdfs/qjournal/MiniJournalCluster$Builder")
        || name.equals("org/apache/hadoop/hdfs/qjournal/MiniJournalCluster")
        || name.equals("org/apache/hadoop/hdfs/qjournal/server/JournalNode")
        || name.equals("org/apache/hadoop/hdfs/qjournal/server/Journal")
        || name.equals("org/apache/hadoop/hdfs/server/blockmanagement/BlockManager")
        || name.equals("org/apache/hadoop/hdfs/server/blockmanagement/BlockManager$BlockReportProcessingThread")
        || name.equals("org/apache/hadoop/hdfs/server/namenode/snapshot/FSImageFormatPBSnapshot$Saver")
        || name.equals("org/apache/hadoop/hdfs/server/namenode/FSImage$FSImageSaver")
        || name.equals("org/apache/hadoop/ipc/Server$RpcCall")
        || name.equals("org/apache/hadoop/ipc/Server$Connection")
        || name.equals("org/apache/hadoop/ipc/Client")
        || name.equals("org/apache/hadoop/ipc/Client$Connection")
        || name.equals("org/apache/hadoop/hdfs/server/datanode/BPServiceActor")
        || name.equals("org/apache/hadoop/hdfs/server/datanode/BPOfferService")
        || name.equals("org/apache/hadoop/hdfs/server/datanode/DataStorage")
        || name.equals("org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage")
        || name.equals("org/apache/hadoop/hdfs/server/datanode/BlockPoolSliceStorage$1")
        || name.equals("org/apache/hadoop/hdfs/server/datanode/BlockRecoveryWorker")
        || name.equals("org/apache/hadoop/hdfs/server/datanode/BlockRecoveryWorker$1")
        || name.equals("org/apache/hadoop/hdfs/server/datanode/DataStorage$VolumeBuilder")
        || name.equals("org/apache/hadoop/hdfs/server/datanode/DataXceiver")
        || name.equals("org/apache/hadoop/hdfs/server/balancer/KeyManager")
        || name.equals("org/apache/hadoop/hdfs/server/balancer/KeyManager$BlockKeyUpdater")
        || name.equals("org/apache/hadoop/hdfs/server/balancer/Dispatcher")
        || name.equals("org/apache/hadoop/hdfs/server/balancer/Dispatcher$PendingMove")
        || name.equals("org/apache/hadoop/hdfs/DFSInputStream")
        || name.equals("org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferClient")
        || name.equals("org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferServer")
        || name.startsWith("org/apache/hadoop/hdfs/") && name.contains("/Test"));
  }

  private static boolean hasJUnitTest(MethodNode method) {
    if ((method.access & Opcodes.ACC_STATIC) != 0) return false;
    if (method.visibleAnnotations == null) return false;
    for (AnnotationNode annotation : method.visibleAnnotations)
      if ("Lorg/junit/Test;".equals(annotation.desc)) return true;
    return false;
  }

  private static void wrap(MethodNode method, String owner, String enter, String desc,
                           String scopeType, boolean receiver) {
    int scopeLocal = method.maxLocals++;
    int thrownLocal = method.maxLocals++;
    LabelNode start = new LabelNode();
    InsnList entry = new InsnList();
    if (receiver) entry.add(new VarInsnNode(Opcodes.ALOAD, 0));
    entry.add(new MethodInsnNode(Opcodes.INVOKESTATIC, owner, enter, desc, false));
    entry.add(new VarInsnNode(Opcodes.ASTORE, scopeLocal));
    entry.add(start);
    method.instructions.insertBefore(method.instructions.getFirst(), entry);
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      int opcode = instruction.getOpcode();
      if (opcode >= Opcodes.IRETURN && opcode <= Opcodes.RETURN)
        method.instructions.insertBefore(instruction, close(scopeLocal, scopeType));
    }
    LabelNode end = new LabelNode();
    LabelNode handler = new LabelNode();
    method.instructions.add(end);
    method.instructions.add(handler);
    method.instructions.add(new VarInsnNode(Opcodes.ASTORE, thrownLocal));
    method.instructions.add(close(scopeLocal, scopeType));
    method.instructions.add(new VarInsnNode(Opcodes.ALOAD, thrownLocal));
    method.instructions.add(new InsnNode(Opcodes.ATHROW));
    method.tryCatchBlocks.add(new TryCatchBlockNode(start, end, handler, "java/lang/Throwable"));
  }

  private static void wrapArgument(MethodNode method, String owner, String enter, String desc,
                                   String scopeType, int argumentLocal) {
    int scopeLocal = method.maxLocals++;
    int thrownLocal = method.maxLocals++;
    LabelNode start = new LabelNode();
    InsnList entry = new InsnList();
    entry.add(new VarInsnNode(Opcodes.ALOAD, argumentLocal));
    entry.add(new MethodInsnNode(Opcodes.INVOKESTATIC, owner, enter, desc, false));
    entry.add(new VarInsnNode(Opcodes.ASTORE, scopeLocal));
    entry.add(start);
    method.instructions.insertBefore(method.instructions.getFirst(), entry);
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      int opcode = instruction.getOpcode();
      if (opcode >= Opcodes.IRETURN && opcode <= Opcodes.RETURN)
        method.instructions.insertBefore(instruction, close(scopeLocal, scopeType));
    }
    LabelNode end = new LabelNode();
    LabelNode handler = new LabelNode();
    method.instructions.add(end);
    method.instructions.add(handler);
    method.instructions.add(new VarInsnNode(Opcodes.ASTORE, thrownLocal));
    method.instructions.add(close(scopeLocal, scopeType));
    method.instructions.add(new VarInsnNode(Opcodes.ALOAD, thrownLocal));
    method.instructions.add(new InsnNode(Opcodes.ATHROW));
    method.tryCatchBlocks.add(new TryCatchBlockNode(start, end, handler, "java/lang/Throwable"));
  }

  private static void scopeAfterCall(MethodNode method, AbstractInsnNode call, String owner,
                                     String enter, String desc, String scopeType,
                                     int argumentLocal) {
    int scopeLocal = method.maxLocals++;
    int thrownLocal = method.maxLocals++;
    // The original method catches exceptions from the read that precedes our
    // scope entry. Its handler can later rethrow inside our handler's range;
    // keep a verifier-visible null until the read and receive hook succeed.
    InsnList initial = new InsnList();
    initial.add(new InsnNode(Opcodes.ACONST_NULL));
    initial.add(new VarInsnNode(Opcodes.ASTORE, scopeLocal));
    method.instructions.insertBefore(method.instructions.getFirst(), initial);
    LabelNode start = new LabelNode();
    InsnList entry = new InsnList();
    // The call's return value remains on the operand stack throughout.
    entry.add(new VarInsnNode(Opcodes.ALOAD, argumentLocal));
    entry.add(new MethodInsnNode(Opcodes.INVOKESTATIC, owner, enter, desc, false));
    entry.add(new VarInsnNode(Opcodes.ASTORE, scopeLocal));
    entry.add(start);
    method.instructions.insert(call, entry);
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      int opcode = instruction.getOpcode();
      if (opcode >= Opcodes.IRETURN && opcode <= Opcodes.RETURN)
        method.instructions.insertBefore(instruction, closeIfNotNull(scopeLocal, scopeType));
    }
    LabelNode end = new LabelNode();
    LabelNode handler = new LabelNode();
    method.instructions.add(end);
    method.instructions.add(handler);
    method.instructions.add(new VarInsnNode(Opcodes.ASTORE, thrownLocal));
    method.instructions.add(closeIfNotNull(scopeLocal, scopeType));
    method.instructions.add(new VarInsnNode(Opcodes.ALOAD, thrownLocal));
    method.instructions.add(new InsnNode(Opcodes.ATHROW));
    method.tryCatchBlocks.add(new TryCatchBlockNode(start, end, handler, "java/lang/Throwable"));
  }

  private static InsnList closeIfNotNull(int local, String type) {
    InsnList instructions = new InsnList();
    LabelNode absent = new LabelNode();
    instructions.add(new VarInsnNode(Opcodes.ALOAD, local));
    instructions.add(new JumpInsnNode(Opcodes.IFNULL, absent));
    instructions.add(close(local, type));
    instructions.add(absent);
    return instructions;
  }

  private static InsnList close(int local, String type) {
    InsnList instructions = new InsnList();
    instructions.add(new VarInsnNode(Opcodes.ALOAD, local));
    instructions.add(new MethodInsnNode(Opcodes.INVOKEVIRTUAL, type, "close", "()V", false));
    return instructions;
  }

  /** Preserve the future NameNode actor while MiniDFSCluster formats its image. */
  private static void aroundFormatCall(MethodNode method, AbstractInsnNode call) {
    int scopeLocal = method.maxLocals++;
    int thrownLocal = method.maxLocals++;
    LabelNode start = new LabelNode();
    LabelNode end = new LabelNode();
    LabelNode handler = new LabelNode();
    LabelNode after = new LabelNode();
    String scopeType = HOOKS + "$NameNodeCreationScope";
    InsnList entry = new InsnList();
    entry.add(new VarInsnNode(Opcodes.ALOAD, 0));
    entry.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "nameNodeCreationEnter",
        "(Ljava/lang/Object;)L" + scopeType + ";", false));
    entry.add(new VarInsnNode(Opcodes.ASTORE, scopeLocal));
    entry.add(start);
    method.instructions.insertBefore(call, entry);
    InsnList suffix = new InsnList();
    suffix.add(end);
    suffix.add(close(scopeLocal, scopeType));
    suffix.add(new JumpInsnNode(Opcodes.GOTO, after));
    suffix.add(handler);
    suffix.add(new VarInsnNode(Opcodes.ASTORE, thrownLocal));
    suffix.add(close(scopeLocal, scopeType));
    suffix.add(new VarInsnNode(Opcodes.ALOAD, thrownLocal));
    suffix.add(new InsnNode(Opcodes.ATHROW));
    suffix.add(after);
    method.instructions.insert(call, suffix);
    method.tryCatchBlocks.add(new TryCatchBlockNode(start, end, handler, "java/lang/Throwable"));
  }

  private static void aroundBlockOpCall(MethodNode method, AbstractInsnNode call,
                                        int actionLocal) {
    int scopeLocal = method.maxLocals++;
    int thrownLocal = method.maxLocals++;
    LabelNode start = new LabelNode();
    LabelNode end = new LabelNode();
    LabelNode handler = new LabelNode();
    LabelNode after = new LabelNode();
    String scopeType = HOOKS + "$BlockOpScope";
    InsnList entry = new InsnList();
    entry.add(new VarInsnNode(Opcodes.ALOAD, 0));
    entry.add(new VarInsnNode(Opcodes.ALOAD, actionLocal));
    entry.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "blockOpEnter",
        "(Ljava/lang/Object;Ljava/lang/Object;)L" + scopeType + ";", false));
    entry.add(new VarInsnNode(Opcodes.ASTORE, scopeLocal));
    entry.add(start);
    method.instructions.insertBefore(call, entry);
    InsnList suffix = new InsnList();
    suffix.add(end);
    suffix.add(close(scopeLocal, scopeType));
    suffix.add(new JumpInsnNode(Opcodes.GOTO, after));
    suffix.add(handler);
    suffix.add(new VarInsnNode(Opcodes.ASTORE, thrownLocal));
    suffix.add(close(scopeLocal, scopeType));
    suffix.add(new VarInsnNode(Opcodes.ALOAD, thrownLocal));
    suffix.add(new InsnNode(Opcodes.ATHROW));
    suffix.add(after);
    method.instructions.insert(call, suffix);
    method.tryCatchBlocks.add(new TryCatchBlockNode(start, end, handler, "java/lang/Throwable"));
  }

  private static final class ResolvingWriter extends ClassWriter {
    private final ClassLoader loader;
    private final ClassNode transforming;
    private final Map<String, Hierarchy> cache = new HashMap<String, Hierarchy>();
    ResolvingWriter(int flags, ClassLoader loader, ClassNode transforming) {
      super(flags);
      this.loader = loader;
      this.transforming = transforming;
    }
    @Override protected String getCommonSuperClass(String left, String right) {
      try {
        if (left.equals(right)) return left;
        if (isAssignable(left, right, new HashSet<String>())) return left;
        if (isAssignable(right, left, new HashSet<String>())) return right;
        if (left.startsWith("[") || right.startsWith("[")) {
          if (!(left.startsWith("[") && right.startsWith("["))) return "java/lang/Object";
          String a = arrayElement(left), b = arrayElement(right);
          if (primitive(a) || primitive(b)) return "java/lang/Object";
          String shared = getCommonSuperClass(a, b);
          return "[" + (shared.startsWith("[") ? shared : "L" + shared + ";");
        }
        Hierarchy cursor = hierarchy(left);
        String parent = cursor == null ? null : cursor.parent;
        while (parent != null) {
          if (isAssignable(parent, right, new HashSet<String>())) return parent;
          Hierarchy info = hierarchy(parent);
          parent = info == null ? null : info.parent;
        }
        return "java/lang/Object";
      } catch (IOException | RuntimeException failure) {
        return "java/lang/Object";
      }
    }

    private boolean isAssignable(String target, String source, Set<String> visited)
        throws IOException {
      if (target.equals(source) || "java/lang/Object".equals(target)) return true;
      if (source.startsWith("[")) {
        if ("java/lang/Cloneable".equals(target) || "java/io/Serializable".equals(target))
          return true;
        if (!target.startsWith("[")) return false;
        String a = arrayElement(target), b = arrayElement(source);
        return primitive(a) || primitive(b) ? a.equals(b) : isAssignable(a, b, visited);
      }
      if (target.startsWith("[") || !visited.add(source)) return false;
      Hierarchy info = hierarchy(source);
      if (info == null) return false;
      if (info.parent != null && isAssignable(target, info.parent, visited)) return true;
      for (String implemented : info.interfaces)
        if (isAssignable(target, implemented, visited)) return true;
      return false;
    }

    private Hierarchy hierarchy(String name) throws IOException {
      if (name.equals(transforming.name))
        return new Hierarchy(transforming.superName, transforming.interfaces);
      if (cache.containsKey(name)) return cache.get(name);
      InputStream stream = loader == null ? null : loader.getResourceAsStream(name + ".class");
      if (stream == null) stream = ClassLoader.getSystemResourceAsStream(name + ".class");
      Hierarchy answer = null;
      if (stream != null) {
        try (InputStream source = stream) {
          ClassReader reader = new ClassReader(source);
          answer = new Hierarchy(reader.getSuperName(), Arrays.asList(reader.getInterfaces()));
        }
      }
      cache.put(name, answer);
      return answer;
    }

    private static String arrayElement(String array) {
      String value = array.substring(1);
      return value.startsWith("L") ? value.substring(1, value.length() - 1) : value;
    }

    private static boolean primitive(String value) {
      return value.length() == 1 && "ZCBSIFJD".contains(value);
    }

    private static final class Hierarchy {
      final String parent;
      final List<String> interfaces;
      Hierarchy(String parent, List<String> interfaces) {
        this.parent = parent;
        this.interfaces = interfaces;
      }
    }
  }
}
