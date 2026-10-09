import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Offline ASM hooks on released Hadoop bytecode, with exact patch-count checks. */
public final class PatchHdfs33 {
  public static void main(String[] args) throws Exception {
    if (args.length != 3) throw new IllegalArgumentException("input, internal name, overlay");
    final String className = args[1];
    final int[] counts = new int[3];
    ClassReader reader = new ClassReader(Files.readAllBytes(Paths.get(args[0])));
    ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
    reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
      @Override public MethodVisitor visitMethod(int access, String name, String desc,
          String signature, String[] exceptions) {
        MethodVisitor mv = super.visitMethod(access, name, desc, signature, exceptions);
        if (mv == null) return null;
        boolean target = className.endsWith("/DataStorage$VolumeBuilder")
            && name.equals("build") && desc.equals("()V");
        boolean rpc = className.equals("org/apache/hadoop/ipc/Client")
            && name.equals("getRpcResponse");
        return new MethodVisitor(Opcodes.ASM9, mv) {
          int line = -1;
          @Override public void visitCode() {
            super.visitCode();
            if (rpc) {
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs33Probe", "rpcResponse", "()V", false);
              counts[2]++;
            }
          }
          @Override public void visitLineNumber(int number, Label start) {
            line = number;
            super.visitLineNumber(number, start);
          }
          @Override public void visitVarInsn(int opcode, int var) {
            super.visitVarInsn(opcode, var);
            if (target && line == 258 && opcode == Opcodes.ASTORE && var == 5) {
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 4);
              super.visitVarInsn(Opcodes.ALOAD, 5);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs33Probe", "target",
                  "(Ljava/lang/Object;Ljava/lang/String;Ljava/lang/Object;)V", false);
              counts[0]++;
            }
          }
          @Override public void visitInsn(int opcode) {
            if (target && line == 259 && opcode == Opcodes.ATHROW) {
              super.visitInsn(Opcodes.DUP);
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 4);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs33Probe", "targetThrow",
                  "(Ljava/lang/Throwable;Ljava/lang/Object;Ljava/lang/String;)V", false);
              counts[1]++;
            }
            super.visitInsn(opcode);
          }
        };
      }
    }, 0);
    if (className.endsWith("/DataStorage$VolumeBuilder") && (counts[0] != 1 || counts[1] != 1))
      throw new IllegalStateException("Target patch counts " + java.util.Arrays.toString(counts));
    if (className.equals("org/apache/hadoop/ipc/Client") && counts[2] != 1)
      throw new IllegalStateException("IPC patch counts " + java.util.Arrays.toString(counts));
    Path output = Paths.get(args[2], className + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(className + " patch counts " + java.util.Arrays.toString(counts));
  }
}
