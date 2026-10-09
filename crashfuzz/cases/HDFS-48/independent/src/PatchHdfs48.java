import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Instrument exact released replaceChild guard and Hadoop IPC response I/O. */
public final class PatchHdfs48 {
  public static void main(String[] args) throws Exception {
    if (args.length != 3) throw new IllegalArgumentException("input, internal name, overlay");
    final String className = args[1];
    final int[] counts = new int[2];
    ClassReader reader = new ClassReader(Files.readAllBytes(Paths.get(args[0])));
    ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
    reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
      @Override public MethodVisitor visitMethod(int access, String name, String desc,
          String signature, String[] exceptions) {
        MethodVisitor mv = super.visitMethod(access, name, desc, signature, exceptions);
        if (mv == null) return null;
        boolean target = className.equals("org/apache/hadoop/hdfs/server/namenode/INodeDirectory")
            && name.equals("replaceChild")
            && desc.equals("(Lorg/apache/hadoop/hdfs/server/namenode/INode;"
                + "Lorg/apache/hadoop/hdfs/server/namenode/INode;"
                + "Lorg/apache/hadoop/hdfs/server/namenode/INodeMap;)V");
        boolean rpc = className.equals("org/apache/hadoop/ipc/Client")
            && name.equals("getRpcResponse");
        return new MethodVisitor(Opcodes.ASM9, mv) {
          int line = -1;
          @Override public void visitCode() {
            super.visitCode();
            if (rpc) {
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs48Probe", "rpcResponse", "()V", false);
              counts[1]++;
            }
          }
          @Override public void visitLineNumber(int number, Label start) {
            line = number;
            super.visitLineNumber(number, start);
          }
          @Override public void visitMethodInsn(int opcode, String owner, String called,
              String descriptor, boolean isInterface) {
            if (target && line == 356 && opcode == Opcodes.INVOKESTATIC
                && owner.equals("org/apache/hadoop/util/Preconditions")
                && called.equals("checkState") && descriptor.equals("(Z)V")) {
              // The original boolean stays on the stack for checkState.
              super.visitInsn(Opcodes.DUP);
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitVarInsn(Opcodes.ALOAD, 2);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs48Probe", "guard",
                  "(ZLorg/apache/hadoop/hdfs/server/namenode/INodeDirectory;"
                      + "Lorg/apache/hadoop/hdfs/server/namenode/INode;"
                      + "Lorg/apache/hadoop/hdfs/server/namenode/INode;)V", false);
              counts[0]++;
            }
            super.visitMethodInsn(opcode, owner, called, descriptor, isInterface);
          }
        };
      }
    }, 0);
    if (className.equals("org/apache/hadoop/hdfs/server/namenode/INodeDirectory") && counts[0] != 1)
      throw new IllegalStateException("Target patch count " + counts[0]);
    if (className.equals("org/apache/hadoop/ipc/Client") && counts[1] != 1)
      throw new IllegalStateException("IPC patch count " + counts[1]);
    Path output = Paths.get(args[2], className + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(className + " patch counts " + java.util.Arrays.toString(counts));
  }
}
