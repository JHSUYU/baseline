package research.zkactor.zk1112;

import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.security.ProtectionDomain;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Case-local ASM hooks in the unchanged JUnit and ZooKeeper 3.8.7 classes. */
public final class CaseAgent {
  static final String TEST = "org/apache/zookeeper/server/quorum/CurrentEpochWriteFailureTest";
  static final String PEER = "org/apache/zookeeper/server/quorum/QuorumPeer";
  static final String ATOMIC = "org/apache/zookeeper/common/AtomicFileOutputStream";
  static final String BRIDGE = "research/zkactor/zk1112/Bridge";
  static final String PROBE = "research/zkactor/Probe";

  private CaseAgent() {}

  public static void premain(String options, Instrumentation instrumentation) {
    instrumentation.addTransformer(new ClassFileTransformer() {
      @Override public byte[] transform(ClassLoader loader, String name, Class<?> clazz,
          ProtectionDomain domain, byte[] original) {
        if (!TEST.equals(name) && !PEER.equals(name) && !ATOMIC.equals(name)) return null;
        try { return transformBytes(name, original); }
        catch (Throwable failure) {
          System.err.println("ZK1112_ACTOR_V2_TRANSFORM_ERROR " + name);
          failure.printStackTrace(System.err);
          throw new IllegalStateException(failure);
        }
      }
    });
  }

  static byte[] transformBytes(String className, byte[] original) {
    ClassReader reader = new ClassReader(original);
    ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_FRAMES);
    reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
      @Override public MethodVisitor visitMethod(int access, String method, String desc,
          String signature, String[] exceptions) {
        MethodVisitor next = super.visitMethod(access, method, desc, signature, exceptions);
        if (next == null) return null;
        boolean test = TEST.equals(className) && method.equals(
            "testReadCurrentEpochFromAcceptedEpochTmpFile") && desc.equals("()V");
        boolean load = PEER.equals(className) && method.equals("loadDataBase")
            && desc.equals("()V");
        boolean read = PEER.equals(className) && method.equals("readLongFromFile")
            && desc.equals("(Ljava/lang/String;)J");
        boolean write = PEER.equals(className) && method.equals("writeLongToFile")
            && desc.equals("(Ljava/lang/String;J)V");
        boolean atomicCtor = ATOMIC.equals(className) && method.equals("<init>")
            && desc.equals("(Ljava/io/File;)V");
        boolean atomicClose = ATOMIC.equals(className) && method.equals("close")
            && desc.equals("()V");
        if (!(test || load || read || write || atomicCtor || atomicClose)) return next;
        return new MethodVisitor(Opcodes.ASM9, next) {
          int line = -1;
          @Override public void visitCode() {
            super.visitCode();
            if (load) {
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "enterLoadDataBase",
                  "(Ljava/lang/Object;)V", false);
            }
          }
          @Override public void visitLineNumber(int number, Label start) {
            line = number;
            super.visitLineNumber(number, start);
            if (!test) {
              super.visitLdcInsn(className.replace('/', '.'));
              super.visitLdcInsn(method);
              super.visitLdcInsn(number);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "coverage",
                  "(Ljava/lang/String;Ljava/lang/String;I)V", false);
            }
            if (test && number == 68) {
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "selectFirstServer",
                  "(Ljava/lang/Object;)V", false);
            }
            if (test && (number == 83 || number == 84)) {
              super.visitVarInsn(Opcodes.ALOAD, number == 83 ? 5 : 6);
              super.visitLdcInsn("CurrentEpochWriteFailureTest#test:"
                  + number + ":FileUtils.write");
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "testFileIo",
                  "(Ljava/io/File;Ljava/lang/String;)V", false);
            }
            if (load && number == 1193) {
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitFieldInsn(Opcodes.GETFIELD, PEER, "acceptedEpoch", "J");
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitFieldInsn(Opcodes.GETFIELD, PEER, "currentEpoch", "J");
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "guard12",
                  "(Ljava/lang/Object;JJ)V", false);
            }
          }
          @Override public void visitInsn(int opcode) {
            if (load && opcode == Opcodes.ATHROW && (line == 1175 || line == 1197)) {
              super.visitInsn(Opcodes.DUP);
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE,
                  line == 1175 ? "throw11" : "throw12",
                  "(Ljava/lang/Throwable;Ljava/lang/Object;)V", false);
            }
            super.visitInsn(opcode);
          }
          @Override public void visitFieldInsn(int opcode, String owner, String field,
              String fieldDesc) {
            super.visitFieldInsn(opcode, owner, field, fieldDesc);
            if (atomicCtor && opcode == Opcodes.PUTFIELD && ATOMIC.equals(owner)
                && field.equals("tmpFile") && fieldDesc.equals("Ljava/io/File;")) {
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitLdcInsn("AtomicFileOutputStream#<init>:" + line + ":tmpFile");
              super.visitLdcInsn("open_tmp");
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "atomicFileIo",
                  "(Ljava/lang/Object;Ljava/lang/String;Ljava/lang/String;)V", false);
            }
          }
          @Override public void visitMethodInsn(int opcode, String owner, String called,
              String calledDesc, boolean itf) {
            if (load && line == 1169 && owner.equals("java/io/File")
                && called.equals("exists") && calledDesc.equals("()Z")) {
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 5);
              super.visitLdcInsn("QuorumPeer#loadDataBase:1169:File.exists");
              super.visitLdcInsn("exists");
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "peerFileIo",
                  "(Ljava/lang/Object;Ljava/io/File;Ljava/lang/String;Ljava/lang/String;)V", false);
            }
            if (read && owner.equals("java/io/FileReader") && called.equals("<init>")
                && calledDesc.equals("(Ljava/io/File;)V")) {
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 2);
              super.visitLdcInsn("QuorumPeer#readLongFromFile:2186:FileReader");
              super.visitLdcInsn("read");
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "peerFileIo",
                  "(Ljava/lang/Object;Ljava/io/File;Ljava/lang/String;Ljava/lang/String;)V", false);
            }
            if (write && owner.equals("org/apache/zookeeper/common/AtomicFileWritingIdiom")
                && called.equals("<init>")) {
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 4);
              super.visitLdcInsn("QuorumPeer#writeLongToFile:2215:AtomicFileWritingIdiom");
              super.visitLdcInsn("write");
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "peerFileIo",
                  "(Ljava/lang/Object;Ljava/io/File;Ljava/lang/String;Ljava/lang/String;)V", false);
            }
            if (atomicClose && owner.equals("java/io/File") && called.equals("renameTo")
                && calledDesc.equals("(Ljava/io/File;)Z")) {
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitLdcInsn("AtomicFileOutputStream#close:" + line + ":File.renameTo");
              super.visitLdcInsn("rename");
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "atomicFileIo",
                  "(Ljava/lang/Object;Ljava/lang/String;Ljava/lang/String;)V", false);
            }
            super.visitMethodInsn(opcode, owner, called, calledDesc, itf);
            if (load && line == 1169 && owner.equals("java/io/File")
                && called.equals("exists") && calledDesc.equals("()Z")) {
              super.visitInsn(Opcodes.DUP);
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 5);
              super.visitVarInsn(Opcodes.LLOAD, 3);
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitFieldInsn(Opcodes.GETFIELD, PEER, "currentEpoch", "J");
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "guard11",
                  "(ZLjava/lang/Object;Ljava/io/File;JJ)V", false);
            }
          }
        };
      }
    }, ClassReader.EXPAND_FRAMES);
    return writer.toByteArray();
  }
}
