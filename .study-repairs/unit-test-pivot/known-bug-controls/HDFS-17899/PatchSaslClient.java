import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Hook exactly the six-argument outbound data-transfer SASL setup. */
public final class PatchSaslClient {
  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("input class, overlay root");
    int[] hooks = new int[1];
    ClassReader reader = new ClassReader(Files.readAllBytes(Paths.get(args[0])));
    ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
    reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
      @Override public MethodVisitor visitMethod(int access, String name,
          String desc, String signature, String[] exceptions) {
        MethodVisitor mv = super.visitMethod(access, name, desc, signature, exceptions);
        if (mv == null || !name.equals("socketSend") ||
            desc.contains("Ljavax/crypto/SecretKey;")) return mv;
        return new MethodVisitor(Opcodes.ASM9, mv) {
          @Override public void visitCode() {
            super.visitCode();
            super.visitVarInsn(Opcodes.ALOAD, 4);
            super.visitVarInsn(Opcodes.ALOAD, 6);
            super.visitMethodInsn(Opcodes.INVOKESTATIC,
                "org/apache/hadoop/hdfs/server/balancer/Hdfs17899Probe",
                "beforeSocketSend", "(Lorg/apache/hadoop/hdfs/protocol/datatransfer/sasl/DataEncryptionKeyFactory;Lorg/apache/hadoop/hdfs/protocol/DatanodeID;)V", false);
            hooks[0]++;
          }
        };
      }
    }, 0);
    if (hooks[0] != 1) throw new IllegalStateException("hook count=" + hooks[0]);
    Path output = Paths.get(args[1],
        "org/apache/hadoop/hdfs/protocol/datatransfer/sasl/SaslDataTransferClient.class");
    Files.createDirectories(output.getParent());
    Files.write(output, writer.toByteArray());
    System.out.println("CONTROL sasl_hook_count=" + hooks[0]);
  }
}
