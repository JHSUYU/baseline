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
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.TypeInsnNode;
import org.objectweb.asm.tree.VarInsnNode;

/** Case-local hooks in the original Hadoop bytecode; no graph classes. */
public final class PatchHdfs07 implements Opcodes {
  private static final String JOURNAL = "org/apache/hadoop/hdfs/qjournal/server/Journal";
  private static final String RPC = "org/apache/hadoop/ipc/Client";
  private static final String PROBE = "Hdfs07Probe";

  private static MethodInsnNode call(String name, String desc) {
    return new MethodInsnNode(INVOKESTATIC, PROBE, name, desc, false);
  }

  private static int journal(MethodNode method) {
    int check = 0, failure = 0, paxos = 0, replace = 0;
    for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null; ) {
      AbstractInsnNode next = insn.getNext();
      if (insn instanceof MethodInsnNode) {
        MethodInsnNode site = (MethodInsnNode) insn;
        if (site.owner.equals(JOURNAL) && site.name.equals("txnRange") && check++ == 0) {
          // The first txnRange call is the guard at Journal.java:924. Locals 2
          // and 9 are the requested and current segment on this branch.
          InsnList hook = new InsnList();
          hook.add(new VarInsnNode(ALOAD, 0));
          hook.add(new FieldInsnNode(GETFIELD, JOURNAL, "storage", "Lorg/apache/hadoop/hdfs/qjournal/server/JNStorage;"));
          hook.add(new MethodInsnNode(INVOKEVIRTUAL, "org/apache/hadoop/hdfs/qjournal/server/JNStorage", "getRoot", "()Ljava/io/File;", false));
          hook.add(new VarInsnNode(ALOAD, 0));
          hook.add(new FieldInsnNode(GETFIELD, JOURNAL, "committedTxnId", "Lorg/apache/hadoop/hdfs/util/BestEffortLongFile;"));
          hook.add(new MethodInsnNode(INVOKEVIRTUAL, "org/apache/hadoop/hdfs/util/BestEffortLongFile", "get", "()J", false));
          hook.add(new VarInsnNode(ALOAD, 1));
          hook.add(new VarInsnNode(ALOAD, 9));
          hook.add(new VarInsnNode(ALOAD, 2));
          hook.add(call("targetCheck", "(Ljava/io/File;JLorg/apache/hadoop/hdfs/qjournal/protocol/RequestInfo;Lorg/apache/hadoop/hdfs/qjournal/protocol/QJournalProtocolProtos$SegmentStateProto;Lorg/apache/hadoop/hdfs/qjournal/protocol/QJournalProtocolProtos$SegmentStateProto;)V"));
          method.instructions.insertBefore(insn, hook);
        }
        if (site.owner.equals(JOURNAL) && site.name.equals("persistPaxosData")) {
          InsnList hook = new InsnList();
          hook.add(new VarInsnNode(ALOAD, 0));
          hook.add(new FieldInsnNode(GETFIELD, JOURNAL, "storage", "Lorg/apache/hadoop/hdfs/qjournal/server/JNStorage;"));
          hook.add(new MethodInsnNode(INVOKEVIRTUAL, "org/apache/hadoop/hdfs/qjournal/server/JNStorage", "getRoot", "()Ljava/io/File;", false));
          hook.add(new VarInsnNode(ALOAD, 1));
          hook.add(new VarInsnNode(ALOAD, 2));
          hook.add(call("paxosWrite", "(Ljava/io/File;Lorg/apache/hadoop/hdfs/qjournal/protocol/RequestInfo;Lorg/apache/hadoop/hdfs/qjournal/protocol/QJournalProtocolProtos$SegmentStateProto;)V"));
          method.instructions.insertBefore(insn, hook);
          paxos++;
        }
        if (site.owner.equals("org/apache/hadoop/fs/FileUtil") && site.name.equals("replaceFile")) {
          InsnList hook = new InsnList();
          hook.add(new InsnNode(DUP2));
          hook.add(call("fileReplace", "(Ljava/io/File;Ljava/io/File;)V"));
          method.instructions.insertBefore(insn, hook);
          replace++;
        }
      }
      if (insn instanceof TypeInsnNode) {
        TypeInsnNode site = (TypeInsnNode) insn;
        if (site.getOpcode() == NEW && site.desc.equals("java/lang/AssertionError")) {
          InsnList hook = new InsnList();
          hook.add(new VarInsnNode(ALOAD, 0));
          hook.add(new FieldInsnNode(GETFIELD, JOURNAL, "storage", "Lorg/apache/hadoop/hdfs/qjournal/server/JNStorage;"));
          hook.add(new MethodInsnNode(INVOKEVIRTUAL, "org/apache/hadoop/hdfs/qjournal/server/JNStorage", "getRoot", "()Ljava/io/File;", false));
          hook.add(new VarInsnNode(ALOAD, 1));
          hook.add(call("targetThrow", "(Ljava/io/File;Lorg/apache/hadoop/hdfs/qjournal/protocol/RequestInfo;)V"));
          method.instructions.insertBefore(insn, hook);
          failure++;
        }
      }
      insn = next;
    }
    if (check != 3 || failure != 1 || paxos != 1 || replace != 1)
      throw new IllegalStateException("Journal hooks check=" + check + " throw=" + failure
          + " paxos=" + paxos + " replace=" + replace);
    return 1;
  }

  public static void main(String[] args) throws Exception {
    if (args.length != 3) throw new IllegalArgumentException("input.class className outDir");
    ClassNode node = new ClassNode();
    new ClassReader(Files.readAllBytes(Paths.get(args[0]))).accept(node, 0);
    if (!node.name.equals(args[1])) throw new IllegalArgumentException("class name mismatch");
    int count = 0;
    for (MethodNode method : node.methods) {
      if (node.name.equals(JOURNAL) && method.name.equals("acceptRecovery")
          && method.desc.equals("(Lorg/apache/hadoop/hdfs/qjournal/protocol/RequestInfo;Lorg/apache/hadoop/hdfs/qjournal/protocol/QJournalProtocolProtos$SegmentStateProto;Ljava/net/URL;)V"))
        count += journal(method);
      if (node.name.equals(RPC) && method.name.equals("getRpcResponse")) {
        method.instructions.insert(call("ipcResponse", "()V"));
        count++;
      }
    }
    if (count != 1) throw new IllegalStateException(node.name + " hooks=" + count);
    ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
    node.accept(writer);
    Path output = Paths.get(args[2], node.name + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(output);
  }
}
