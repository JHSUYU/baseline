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
import org.objectweb.asm.tree.LdcInsnNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.VarInsnNode;

/** Adds peer/target identity to the existing case-local Hadoop 3.4.3 hooks. */
public final class PatchQjmRpcActorV2 implements Opcodes {
  private static final String CLIENT = "org/apache/hadoop/ipc/Client";
  private static final String CONNECTION = CLIENT + "$Connection";
  private static final String SERVER = "org/apache/hadoop/hdfs/qjournal/server/JournalNodeRpcServer";
  private static final String JOURNAL_NODE = "org/apache/hadoop/hdfs/qjournal/server/JournalNode";
  private static final String JOURNAL = "org/apache/hadoop/hdfs/qjournal/server/Journal";
  private static final String STORAGE = "org/apache/hadoop/hdfs/qjournal/server/JNStorage";

  private static MethodInsnNode call(String owner, String name, String desc) {
    return new MethodInsnNode(INVOKESTATIC, owner, name, desc, false);
  }

  private static int client(MethodNode method, String probe) {
    if (!method.desc.equals("(L" + CLIENT + "$Call;L" + CONNECTION
        + ";JLjava/util/concurrent/TimeUnit;)Lorg/apache/hadoop/io/Writable;"))
      throw new IllegalStateException("getRpcResponse descriptor drift: " + method.desc);
    int count = 0;
    for (AbstractInsnNode instruction = method.instructions.getFirst(); instruction != null;
         instruction = instruction.getNext()) {
      if (!(instruction instanceof MethodInsnNode)) continue;
      MethodInsnNode old = (MethodInsnNode) instruction;
      if (!old.owner.equals(probe) || !old.name.equals("ipcResponse") || !old.desc.equals("()V"))
        continue;
      // Local 2 is the actual RPC connection; use its resolved server address.
      InsnList replacement = new InsnList();
      replacement.add(new VarInsnNode(ALOAD, 2));
      replacement.add(new MethodInsnNode(INVOKEVIRTUAL, CONNECTION, "getRemoteAddress",
          "()Ljava/net/InetSocketAddress;", false));
      replacement.add(new MethodInsnNode(INVOKEVIRTUAL, "java/net/InetSocketAddress", "getPort", "()I", false));
      replacement.add(call(probe, "ipcResponse", "(I)V"));
      method.instructions.insertBefore(old, replacement);
      method.instructions.remove(old);
      count++;
    }
    if (count != 1) throw new IllegalStateException("Client RPC hook count=" + count);
    return count;
  }

  private static int server(MethodNode method, String probe) {
    int count = 0;
    for (AbstractInsnNode instruction = method.instructions.getFirst(); instruction != null;
         instruction = instruction.getNext()) {
      if (instruction.getOpcode() != RETURN) continue;
      InsnList hook = new InsnList();
      hook.add(new VarInsnNode(ALOAD, 0));
      hook.add(new FieldInsnNode(GETFIELD, SERVER, "server", "Lorg/apache/hadoop/ipc/RPC$Server;"));
      hook.add(new MethodInsnNode(INVOKEVIRTUAL, "org/apache/hadoop/ipc/RPC$Server", "getListenerAddress",
          "()Ljava/net/InetSocketAddress;", false));
      hook.add(new MethodInsnNode(INVOKEVIRTUAL, "java/net/InetSocketAddress", "getPort", "()I", false));
      hook.add(new VarInsnNode(ALOAD, 0));
      hook.add(new FieldInsnNode(GETFIELD, SERVER, "jn", "L" + JOURNAL_NODE + ";"));
      hook.add(new MethodInsnNode(INVOKEVIRTUAL, JOURNAL_NODE, "getConf",
          "()Lorg/apache/hadoop/conf/Configuration;", false));
      hook.add(new LdcInsnNode("dfs.journalnode.edits.dir"));
      hook.add(new MethodInsnNode(INVOKEVIRTUAL, "org/apache/hadoop/conf/Configuration", "get",
          "(Ljava/lang/String;)Ljava/lang/String;", false));
      hook.add(call(probe, "registerPort", "(ILjava/lang/String;)V"));
      method.instructions.insertBefore(instruction, hook);
      count++;
    }
    if (count != 1) throw new IllegalStateException("JN start RETURN count=" + count);
    return count;
  }

  private static int target(MethodNode method) {
    InsnList hook = new InsnList();
    hook.add(new VarInsnNode(ALOAD, 0));
    hook.add(new FieldInsnNode(GETFIELD, JOURNAL, "storage", "L" + STORAGE + ";"));
    hook.add(new MethodInsnNode(INVOKEVIRTUAL, STORAGE, "getRoot", "()Ljava/io/File;", false));
    hook.add(call("QjmRpcActor", "bindTarget", "(Ljava/io/File;)V"));
    method.instructions.insert(hook);
    return 1;
  }

  public static void main(String[] args) throws Exception {
    if (args.length != 4) throw new IllegalArgumentException("input.class className caseProbe outputDir");
    Path input = Paths.get(args[0]);
    ClassNode node = new ClassNode();
    new ClassReader(Files.readAllBytes(input)).accept(node, 0);
    if (!node.name.equals(args[1])) throw new IllegalArgumentException("class name mismatch");
    String probe = args[2];
    if (!probe.matches("Hdfs(07|09|10)Probe")) throw new IllegalArgumentException("case probe");
    int count = 0;
    for (MethodNode method : node.methods) {
      if (node.name.equals(CLIENT) && method.name.equals("getRpcResponse")) count += client(method, probe);
      if (node.name.equals(SERVER) && method.name.equals("start") && method.desc.equals("()V")) count += server(method, probe);
      if (node.name.equals(JOURNAL) && !probe.equals("Hdfs07Probe")
          && method.desc.equals("(Lorg/apache/hadoop/hdfs/qjournal/protocol/RequestInfo;)V")
          && method.name.equals(probe.equals("Hdfs09Probe") ? "checkRequest" : "checkWriteRequest"))
        count += target(method);
    }
    if (count != 1) throw new IllegalStateException(node.name + " exact hooks=" + count);
    ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
    node.accept(writer);
    Path output = Paths.get(args[3], node.name + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(output);
  }
}
