package zk06;

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

/** Directly records the actual bytecode check and checked-I/O call sites. */
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
              MethodVisitor output = super.visitMethod(access, name, descriptor, signature, exceptions);
              if (output == null) return null;
              final boolean instance = (access & Opcodes.ACC_STATIC) == 0;
              return new MethodVisitor(Opcodes.ASM9, output) {
                private int line = -1;
                @Override public void visitCode() {
                  super.visitCode();
                  if (instance && dotted.equals("org.apache.zookeeper.server.quorum.QuorumPeer")
                      && (name.equals("readLongFromFile") || name.equals("writeLongToFile"))) {
                    super.visitLdcInsn(dotted + "#" + name + ":file");
                    super.visitVarInsn(Opcodes.ALOAD, 0);
                    super.visitVarInsn(Opcodes.ALOAD, 1);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "zk06/Probe", "io",
                        "(Ljava/lang/String;Ljava/lang/Object;Ljava/lang/Object;)V", false);
                  }
                }
                @Override public void visitLineNumber(int number, Label start) {
                  line = number;
                  super.visitLineNumber(number, start);
                  super.visitLdcInsn(dotted);
                  super.visitLdcInsn(name);
                  super.visitLdcInsn(number);
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, "zk06/Probe", "line",
                      "(Ljava/lang/String;Ljava/lang/String;I)V", false);
                }
                @Override public void visitJumpInsn(int opcode, Label label) {
                  if (dotted.equals("org.apache.zookeeper.server.quorum.Leader")
                      && name.equals("waitForEpochAck") && line == 1471 && opcode == Opcodes.IFEQ) {
                    super.visitInsn(Opcodes.DUP);
                    super.visitVarInsn(Opcodes.ALOAD, 0);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "zk06/Probe", "guard",
                        "(ILjava/lang/Object;)V", false);
                  }
                  super.visitJumpInsn(opcode, label);
                }
                @Override public void visitInsn(int opcode) {
                  if (dotted.equals("org.apache.zookeeper.server.quorum.Leader")
                      && name.equals("waitForEpochAck") && line == 1475 && opcode == Opcodes.ATHROW) {
                    super.visitVarInsn(Opcodes.ALOAD, 0);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "zk06/Probe", "targetThrow",
                        "(Ljava/lang/Object;)V", false);
                  }
                  super.visitInsn(opcode);
                }
                @Override public void visitMethodInsn(int opcode, String owner, String called,
                    String calledDesc, boolean isInterface) {
                  boolean io = instance && !dotted.equals("org.apache.zookeeper.server.quorum.QuorumPeer")
                      && ((owner.startsWith("org/apache/jute/")
                           && (called.equals("readRecord") || called.equals("writeRecord")))
                          || (owner.startsWith("java/io/")
                              && (called.startsWith("read") || called.startsWith("write")
                                  || called.equals("flush"))));
                  if (io) {
                    super.visitLdcInsn(dotted + "#" + name + ":" + line + ":"
                        + owner.replace('/', '.') + "#" + called + calledDesc);
                    super.visitVarInsn(Opcodes.ALOAD, 0);
                    super.visitInsn(Opcodes.ACONST_NULL);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "zk06/Probe", "io",
                        "(Ljava/lang/String;Ljava/lang/Object;Ljava/lang/Object;)V", false);
                  }
                  super.visitMethodInsn(opcode, owner, called, calledDesc, isInterface);
                }
              };
            }
          }, 0);
          return writer.toByteArray();
        } catch (Throwable error) {
          System.err.println("ZK06_INSTRUMENT_ERROR " + dotted + " " + error);
          error.printStackTrace();
          return null;
        }
      }
    });
  }
}
