import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.Type;

/** Patch the original JUnit's exact HDFS31 guard and actor-bound producer RPC. */
public final class PatchHdfs31 {
  public static void main(String[] args) throws Exception {
    if (args.length != 3) throw new IllegalArgumentException("input class, name, overlay required");
    byte[] original = Files.readAllBytes(Paths.get(args[0]));
    final String className = args[1];
    final int[] counts = new int[10];
    ClassReader reader = new ClassReader(original);
    ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
    reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
      @Override public MethodVisitor visitMethod(int access, String name, String descriptor,
          String signature, String[] exceptions) {
        MethodVisitor mv = super.visitMethod(access, name, descriptor, signature, exceptions);
        if (mv == null) return null;
        final boolean rpc = className.equals("org/apache/hadoop/ipc/Client")
            && name.equals("getRpcResponse")
            && descriptor.startsWith("(Lorg/apache/hadoop/ipc/Client$Call;"
                + "Lorg/apache/hadoop/ipc/Client$Connection;");
        final boolean actor = className.endsWith("/BPServiceActor")
            && name.equals("run") && descriptor.equals("()V");
        final boolean cluster = className.endsWith("/MiniDFSCluster")
            && name.equals("startDataNodes") && Type.getArgumentTypes(descriptor).length == 15;
        final boolean dnConstructor = className.endsWith("/DataNode") && name.equals("<init>");
        final boolean instantiate = className.endsWith("/DataNode")
            && name.equals("instantiateDataNode") && Type.getArgumentTypes(descriptor).length == 3;
        final boolean target = className.endsWith("/DataNode")
            && name.equals("getBPOSForBlock")
            && descriptor.equals("(Lorg/apache/hadoop/hdfs/protocol/ExtendedBlock;)Lorg/apache/hadoop/hdfs/server/datanode/BPOfferService;");
        final boolean transfer = className.endsWith("/DataNode")
            && name.equals("transferBlock")
            && descriptor.startsWith("(Lorg/apache/hadoop/hdfs/protocol/ExtendedBlock;");
        final boolean add = className.endsWith("/BlockPoolManager") && name.equals("addBlockPool");
        final boolean remove = className.endsWith("/BlockPoolManager") && name.equals("remove");
        return new MethodVisitor(Opcodes.ASM9, mv) {
          private int line = -1;
          @Override public void visitCode() {
            super.visitCode();
            if (cluster) {
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs31Probe", "startEpisode", "()V", false);
              counts[6]++;
            }
            if (actor) {
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitFieldInsn(Opcodes.GETFIELD,
                  "org/apache/hadoop/hdfs/server/datanode/BPServiceActor", "dn",
                  "Lorg/apache/hadoop/hdfs/server/datanode/DataNode;");
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitFieldInsn(Opcodes.GETFIELD,
                  "org/apache/hadoop/hdfs/server/datanode/BPServiceActor", "nnAddr",
                  "Ljava/net/InetSocketAddress;");
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs31Probe", "enterActor",
                  "(Lorg/apache/hadoop/hdfs/server/datanode/DataNode;Ljava/net/InetSocketAddress;)V", false);
              counts[7]++;
            }
            if (rpc) {
              super.visitVarInsn(Opcodes.ALOAD, 2);
              super.visitMethodInsn(Opcodes.INVOKEVIRTUAL, "org/apache/hadoop/ipc/Client$Connection",
                  "getRemoteAddress", "()Ljava/net/InetSocketAddress;", false);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs31Probe", "rpcResponse",
                  "(Ljava/net/InetSocketAddress;)V", false);
              counts[5]++;
            }
            if (transfer) {
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs31Probe", "transfer",
                  "(Lorg/apache/hadoop/hdfs/server/datanode/DataNode;"
                  + "Lorg/apache/hadoop/hdfs/protocol/ExtendedBlock;)V", false);
              counts[2]++;
            }
            if (add || remove) {
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs31Probe",
                  add ? "poolAdd" : "poolRemove", "(Ljava/lang/Object;Ljava/lang/Object;)V", false);
              counts[add ? 3 : 4]++;
            }
          }
          @Override public void visitLineNumber(int number, Label start) {
            line = number;
            super.visitLineNumber(number, start);
          }
          @Override public void visitMethodInsn(int opcode, String owner, String called,
              String desc, boolean isInterface) {
            if (dnConstructor && owner.equals("org/apache/hadoop/hdfs/server/datanode/DataNode")
                && called.equals("startDataNode")) {
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs31Probe", "registerDataNode",
                  "(Lorg/apache/hadoop/hdfs/server/datanode/DataNode;"
                  + "Lorg/apache/hadoop/conf/Configuration;)Lorg/apache/hadoop/hdfs/server/datanode/DataNode;", false);
              super.visitInsn(Opcodes.POP);
              counts[8]++;
            }
            super.visitMethodInsn(opcode, owner, called, desc, isInterface);
            if (target && line == 1832
                && owner.equals("org/apache/hadoop/hdfs/server/datanode/BlockPoolManager")
                && called.equals("get")) {
              super.visitInsn(Opcodes.DUP);
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs31Probe", "guard",
                  "(Ljava/lang/Object;Lorg/apache/hadoop/hdfs/server/datanode/DataNode;"
                  + "Lorg/apache/hadoop/hdfs/protocol/ExtendedBlock;)V", false);
              counts[0]++;
            }
          }
          @Override public void visitInsn(int opcode) {
            if (cluster && opcode == Opcodes.RETURN) {
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs31Probe", "endEpisode", "()V", false);
            }
            if (actor && opcode == Opcodes.RETURN) {
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs31Probe", "exitActor", "()V", false);
            }
            if (instantiate && opcode == Opcodes.ARETURN) {
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs31Probe", "registerDataNode",
                  "(Lorg/apache/hadoop/hdfs/server/datanode/DataNode;"
                  + "Lorg/apache/hadoop/conf/Configuration;)Lorg/apache/hadoop/hdfs/server/datanode/DataNode;", false);
              counts[9]++;
            }
            if (target && line == 1835 && opcode == Opcodes.ATHROW) {
              super.visitInsn(Opcodes.DUP);
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs31Probe", "targetThrow",
                  "(Ljava/lang/Throwable;Lorg/apache/hadoop/hdfs/server/datanode/DataNode;"
                  + "Lorg/apache/hadoop/hdfs/protocol/ExtendedBlock;)V", false);
              counts[1]++;
            }
            super.visitInsn(opcode);
          }
        };
      }
    }, 0);
    if (className.endsWith("/DataNode")) {
      if (counts[0] != 1 || counts[1] != 1 || counts[2] != 1
          || counts[8] != 1 || counts[9] != 2)
        throw new IllegalStateException("Target patch counts: " + java.util.Arrays.toString(counts));
    } else if (className.endsWith("/BlockPoolManager") && (counts[3] != 1 || counts[4] != 1)) {
      throw new IllegalStateException("Pool patch counts: " + java.util.Arrays.toString(counts));
    } else if (className.equals("org/apache/hadoop/ipc/Client") && counts[5] != 1) {
      throw new IllegalStateException("RPC patch counts: " + java.util.Arrays.toString(counts));
    } else if (className.endsWith("/MiniDFSCluster") && counts[6] != 1) {
      throw new IllegalStateException("Episode patch counts: " + java.util.Arrays.toString(counts));
    } else if (className.endsWith("/BPServiceActor") && counts[7] != 1) {
      throw new IllegalStateException("Actor patch counts: " + java.util.Arrays.toString(counts));
    }
    Path output = Paths.get(args[2], className + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(className + " patch counts " + java.util.Arrays.toString(counts));
  }
}
