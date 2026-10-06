import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Offline hooks at released snapshot serialization, count check, and IPC read. */
public final class PatchHdfs52 {
  public static void main(String[] args) throws Exception {
    if (args.length != 3) throw new IllegalArgumentException("input, internal name, overlay");
    final String className = args[1];
    final int[] counts = new int[4];
    ClassReader reader = new ClassReader(Files.readAllBytes(Paths.get(args[0])));
    ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
    reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
      @Override public MethodVisitor visitMethod(int access, String name, String desc,
          String signature, String[] exceptions) {
        MethodVisitor mv = super.visitMethod(access, name, desc, signature, exceptions);
        if (mv == null) return null;
        boolean target = className.endsWith("/FSImageFormatPBSnapshot$Saver")
            && name.equals("serializeSnapshotSection")
            && desc.equals("(Ljava/io/OutputStream;)V");
        boolean rpc = className.equals("org/apache/hadoop/ipc/Client")
            && name.equals("getRpcResponse");
        return new MethodVisitor(Opcodes.ASM9, mv) {
          int line = -1;
          @Override public void visitCode() {
            super.visitCode();
            if (rpc) {
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs52Probe", "rpcResponse", "()V", false);
              counts[3]++;
            }
          }
          @Override public void visitLineNumber(int number, Label start) {
            line = number;
            super.visitLineNumber(number, start);
          }
          @Override public void visitMethodInsn(int opcode, String owner, String called,
              String descriptor, boolean isInterface) {
            if (target && called.equals("writeDelimitedTo")
                && descriptor.equals("(Ljava/io/OutputStream;)V")
                && line == 445
                && owner.equals("org/apache/hadoop/hdfs/server/namenode/FsImageProto$SnapshotSection")) {
              super.visitLdcInsn("header");
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs52Probe", "fileWrite",
                  "(Ljava/lang/String;)V", false);
              counts[1]++;
            }
            if (target && called.equals("writeDelimitedTo")
                && descriptor.equals("(Ljava/io/OutputStream;)V")
                && line == 460
                && owner.equals("org/apache/hadoop/hdfs/server/namenode/FsImageProto$SnapshotSection$Snapshot")) {
              super.visitLdcInsn("record");
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs52Probe", "fileWrite",
                  "(Ljava/lang/String;)V", false);
              counts[2]++;
            }
            super.visitMethodInsn(opcode, owner, called, descriptor, isInterface);
            if (target && line == 467
                && owner.equals("org/apache/hadoop/hdfs/server/namenode/snapshot/SnapshotManager")
                && called.equals("getNumSnapshots") && descriptor.equals("()I")) {
              // Preserve the original serialized and manager counts for if_icmpne.
              super.visitInsn(Opcodes.DUP2);
              super.visitVarInsn(Opcodes.ALOAD, 2);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs52Probe", "counts",
                  "(IILjava/lang/Object;)V", false);
              counts[0]++;
            }
          }
        };
      }
    }, 0);
    if (className.endsWith("/FSImageFormatPBSnapshot$Saver")
        && (counts[0] != 1 || counts[1] != 1 || counts[2] != 1))
      throw new IllegalStateException("Snapshot patch counts " + java.util.Arrays.toString(counts));
    if (className.equals("org/apache/hadoop/ipc/Client") && counts[3] != 1)
      throw new IllegalStateException("IPC patch count " + counts[3]);
    Path output = Paths.get(args[2], className + ".class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println(className + " patch counts " + java.util.Arrays.toString(counts));
  }
}
