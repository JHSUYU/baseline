package independent;

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

/** Exact target-site and direct-I/O probes, built from original class files. */
public final class CoverageAgent {
  public static void premain(String args, Instrumentation instrumentation) {
    final Set<String> selected = new HashSet<String>(Arrays.asList(args.split(",")));
    final String targetMethod = System.getProperty("research.target.method");
    final int guardLine = Integer.getInteger("research.target.guard.line", -1);
    final int throwLine = Integer.getInteger("research.target.throw.line", -1);
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
                  && !name.equals("readLongFromFile") && !name.equals("writeLongToFile") && !name.equals("loadDataBase")) return output;
              final boolean target = dotted.equals("org.apache.zookeeper.server.quorum.QuorumPeer")
                  && name.equals(targetMethod);
              return new MethodVisitor(Opcodes.ASM9, output) {
                private int line = -1;
                @Override public void visitCode() {
                  super.visitCode();
                  if (target) {
                    super.visitVarInsn(Opcodes.ALOAD, 0);
                    super.visitFieldInsn(Opcodes.GETFIELD, "org/apache/zookeeper/server/quorum/QuorumPeer", "myid", "J");
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "independent/Probe", "entry", "(J)V", false);
                  }
                }
                @Override public void visitLineNumber(int number, Label start) {
                  line = number;
                  super.visitLineNumber(number, start);
                  super.visitLdcInsn(dotted);
                  super.visitLdcInsn(name);
                  super.visitLdcInsn(number);
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, "independent/Probe", "hit",
                      "(Ljava/lang/String;Ljava/lang/String;I)V", false);
                  if (target && number == guardLine) {
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "independent/Probe", "guard", "()V", false);
                  }
                }
                @Override public void visitInsn(int opcode) {
                  if (target && line == throwLine && opcode == Opcodes.ATHROW) {
                    super.visitInsn(Opcodes.DUP);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "independent/Probe", "targetThrow",
                        "(Ljava/lang/Throwable;)V", false);
                  }
                  super.visitInsn(opcode);
                }
                @Override public void visitMethodInsn(int opcode, String owner, String called,
                    String calledDesc, boolean isInterface) {
                  boolean socket = owner.equals("java/nio/channels/SocketChannel")
                      && (called.equals("read") || called.equals("write"));
                  boolean epoch = dotted.equals("org.apache.zookeeper.server.quorum.QuorumPeer")
                      && name.equals("readLongFromFile")
                      && ((owner.equals("java/io/FileReader") && called.equals("<init>"))
                          || (owner.equals("java/io/BufferedReader") && called.equals("readLine")));
                  boolean epochWrite = dotted.equals("org.apache.zookeeper.server.quorum.QuorumPeer")
                      && name.equals("writeLongToFile")
                      && owner.equals("org/apache/zookeeper/common/AtomicFileWritingIdiom")
                      && called.equals("<init>");
                  boolean atomic = dotted.equals("org.apache.zookeeper.common.AtomicFileWritingIdiom")
                      && (owner.equals("org/apache/zookeeper/common/AtomicFileOutputStream")
                          && (called.equals("<init>") || called.equals("close")));
                  boolean atomicDisk = dotted.equals("org.apache.zookeeper.common.AtomicFileOutputStream")
                      && name.equals("close")
                      && ((owner.equals("java/io/FileDescriptor") && called.equals("sync"))
                          || (owner.equals("java/io/File") && called.equals("renameTo")));
                  if (socket || epoch || epochWrite || atomic || atomicDisk) {
                    String site = dotted + "#" + name + ":" + line + ":"
                        + owner.replace('/', '.') + "#" + called + calledDesc;
                    super.visitLdcInsn(site);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "independent/Probe", "io",
                        "(Ljava/lang/String;)V", false);
                  }
                  super.visitMethodInsn(opcode, owner, called, calledDesc, isInterface);
                }
              };
            }
          }, 0);
          return writer.toByteArray();
        } catch (Throwable error) {
          System.err.println("INDEPENDENT_INSTRUMENT_ERROR " + dotted + " " + error);
          error.printStackTrace();
          return null;
        }
      }
    });
  }
}
