package audit;

import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.security.ProtectionDomain;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

public final class CoverageAgent {
  public static void premain(String args, Instrumentation instrumentation) {
    final Set<String> selected = new HashSet<String>(Arrays.asList(args.split(",")));
    instrumentation.addTransformer(new ClassFileTransformer() {
      @Override public byte[] transform(ClassLoader loader, String className, Class<?> clazz,
          ProtectionDomain domain, byte[] bytes) {
        if (!selected.contains(className)) return null;
        final String dotted = className.replace('/', '.');
        try {
          ClassReader reader = new ClassReader(bytes);
          ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_FRAMES);
          reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
            @Override public MethodVisitor visitMethod(int access, String name, String descriptor,
                String signature, String[] exceptions) {
              final MethodVisitor output = super.visitMethod(access, name, descriptor, signature, exceptions);
              if (output == null) return null;
              if (dotted.equals("org.apache.zookeeper.server.quorum.QuorumPeer")
                  && !name.equals("readLongFromFile") && !name.equals("writeLongToFile")) {
                return output;
              }
              return new MethodVisitor(Opcodes.ASM9, output) {
                private int line = -1;
                @Override public void visitLineNumber(int line, Label start) {
                  this.line = line;
                  super.visitLineNumber(line, start);
                  super.visitLdcInsn(dotted);
                  super.visitLdcInsn(name);
                  super.visitLdcInsn(line);
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, "audit/Probe", "hit",
                      "(Ljava/lang/String;Ljava/lang/String;I)V", false);
                }
                @Override public void visitJumpInsn(int opcode, Label label) {
                  if (dotted.equals("org.apache.zookeeper.server.ZooKeeperServer")
                      && name.equals("processConnectRequest") && line == 1431
                      && opcode == Opcodes.IFLE) {
                    super.visitInsn(Opcodes.DUP);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "audit/Probe", "guard", "(I)V", false);
                  }
                  super.visitJumpInsn(opcode, label);
                }
                @Override public void visitInsn(int opcode) {
                  if (dotted.equals("org.apache.zookeeper.server.ZooKeeperServer")
                      && name.equals("processConnectRequest") && line == 1441
                      && opcode == Opcodes.ATHROW) {
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "audit/Probe", "targetThrow", "()V", false);
                  }
                  super.visitInsn(opcode);
                }
                @Override public void visitMethodInsn(int opcode, String owner, String called,
                    String calledDesc, boolean isInterface) {
                  if ((owner.equals("java/nio/channels/SocketChannel")
                       && (called.equals("read") || called.equals("write")))
                      || ((name.equals("readLongFromFile") || name.equals("writeLongToFile"))
                          && owner.startsWith("java/io/")
                          && (called.startsWith("read") || called.startsWith("write")
                              || called.equals("close")
                              || (owner.equals("java/io/FileReader") && called.equals("<init>"))))) {
                    String site = dotted + "#" + name + ":" + line + ":"
                        + owner.replace('/', '.') + "#" + called + calledDesc;
                    super.visitLdcInsn(site);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "audit/Probe", "io",
                        "(Ljava/lang/String;)V", false);
                  }
                  super.visitMethodInsn(opcode, owner, called, calledDesc, isInterface);
                }
              };
            }
          }, 0);
          return writer.toByteArray();
        } catch (Throwable error) {
          System.err.println("COVERAGE_INSTRUMENT_ERROR " + dotted + " " + error);
          error.printStackTrace();
          return null;
        }
      }
    });
  }
}
