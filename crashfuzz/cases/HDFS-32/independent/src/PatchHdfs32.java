import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Patch clean Hadoop bytecode at the selected call and explicit throw. */
public final class PatchHdfs32 {
  public static void main(String[] args) throws Exception {
    if (args.length != 3) throw new IllegalArgumentException("input class, name, overlay required");
    byte[] original = Files.readAllBytes(Paths.get(args[0]));
    final String className = args[1];
    final int[] counts = new int[6];
    ClassReader reader = new ClassReader(original);
    ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
    reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
      @Override public MethodVisitor visitMethod(int access, String name, String descriptor,
          String signature, String[] exceptions) {
        MethodVisitor mv = super.visitMethod(access, name, descriptor, signature, exceptions);
        if (mv == null) return null;
        final boolean rpc = className.equals("org/apache/hadoop/ipc/Client")
            && name.equals("getRpcResponse");
        final boolean target = className.endsWith("/DataNode")
            && name.equals("deleteBlockPool") && descriptor.equals("(Ljava/lang/String;Z)V");
        final boolean refresh = className.endsWith("/DataNode")
            && name.equals("refreshNamenodes")
            && descriptor.equals("(Lorg/apache/hadoop/conf/Configuration;)V");
        final boolean add = className.endsWith("/BlockPoolManager") && name.equals("addBlockPool");
        final boolean remove = className.endsWith("/BlockPoolManager") && name.equals("remove");
        return new MethodVisitor(Opcodes.ASM9, mv) {
          private int line = -1;
          @Override public void visitCode() {
            super.visitCode();
            if (rpc) {
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs32Probe", "rpcResponse", "()V", false);
              counts[5]++;
            }
            if (refresh) {
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs32Probe", "refresh", "(Ljava/lang/Object;)V", false);
              counts[2]++;
            }
            if (add || remove) {
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs32Probe",
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
            super.visitMethodInsn(opcode, owner, called, desc, isInterface);
            if (target && line == 3819
                && owner.equals("org/apache/hadoop/hdfs/server/datanode/BlockPoolManager")
                && called.equals("get")) {
              super.visitInsn(Opcodes.DUP);
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitVarInsn(Opcodes.ILOAD, 2);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs32Probe", "guard",
                  "(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/String;Z)V", false);
              counts[0]++;
            }
            if (target && line == 3827
                && owner.equals("org/apache/hadoop/hdfs/server/datanode/fsdataset/FsDatasetSpi")
                && called.equals("deleteBlockPool")) {
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitVarInsn(Opcodes.ILOAD, 2);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs32Probe", "datasetDelete",
                  "(Ljava/lang/Object;Ljava/lang/String;Z)V", false);
            }
          }
          @Override public void visitInsn(int opcode) {
            if (target && line == 3822 && opcode == Opcodes.ATHROW) {
              super.visitInsn(Opcodes.DUP);
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitVarInsn(Opcodes.ILOAD, 2);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs32Probe", "targetThrow",
                  "(Ljava/lang/Throwable;Ljava/lang/Object;Ljava/lang/String;Z)V", false);
              counts[1]++;
            }
            super.visitInsn(opcode);
          }
        };
      }
    }, 0);
    if (className.endsWith("/DataNode")) {
      if (counts[0] != 1 || counts[1] != 1 || counts[2] != 1)
        throw new IllegalStateException("Target patch counts: " + java.util.Arrays.toString(counts));
    } else if (className.endsWith("/BlockPoolManager") && (counts[3] != 1 || counts[4] != 1)) {
      throw new IllegalStateException("Pool patch counts: " + java.util.Arrays.toString(counts));
    } else if (className.equals("org/apache/hadoop/ipc/Client") && counts[5] != 1) {
      throw new IllegalStateException("RPC patch counts: " + java.util.Arrays.toString(counts));
    }
    Path output = Paths.get(args[2], className + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(className + " patch counts " + java.util.Arrays.toString(counts));
  }
}
