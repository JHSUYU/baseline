import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Add one hook to the original seven-argument SASL socketSend method. */
public final class PatchOutboundSasl {
  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("input class, overlay root");
    final int[] hooks = new int[1];
    ClassReader reader = new ClassReader(Files.readAllBytes(Paths.get(args[0])));
    ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
    reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
      @Override public MethodVisitor visitMethod(int access, String name, String desc,
          String signature, String[] exceptions) {
        MethodVisitor mv = super.visitMethod(access, name, desc, signature, exceptions);
        if (mv == null || !name.equals("socketSend") || !desc.contains("Ljavax/crypto/SecretKey;"))
          return mv;
        return new MethodVisitor(Opcodes.ASM9, mv) {
          @Override public void visitCode() {
            super.visitCode();
            // DatanodeID is local 6 in this instance method.
            super.visitVarInsn(Opcodes.ALOAD, 6);
            super.visitMethodInsn(Opcodes.INVOKESTATIC, "Hdfs17967Probe", "before",
                "(Lorg/apache/hadoop/hdfs/protocol/DatanodeID;)V", false);
            hooks[0]++;
          }
        };
      }
    }, 0);
    if (hooks[0] != 1) throw new IllegalStateException("socketSend hook count " + hooks[0]);
    Path output = Paths.get(args[1],
        "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferClient.class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println("outbound SASL hook count=" + hooks[0]);
  }
}
