package research.zkactor.zk04;

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

/** Original ConnectionMetricsTest and production I/O, with actor-aware joins. */
public final class CaseAgent {
  static final String TEST = "org/apache/zookeeper/server/ConnectionMetricsTest";
  static final String CLIENT = "org/apache/zookeeper/ClientCnxnSocketNIO";
  static final String SERVER = "org/apache/zookeeper/server/NIOServerCnxn";
  static final String TARGET = "org/apache/zookeeper/server/ZooKeeperServer";
  static final String PEER = "org/apache/zookeeper/server/quorum/QuorumPeer";
  static final String BRIDGE = "research/zkactor/zk04/Bridge";
  static final String PROBE = "research/zkactor/Probe";
  private static final Set<String> SELECTED = new HashSet<>(Arrays.asList(
      TEST, CLIENT, SERVER, TARGET, PEER));

  private CaseAgent() {}

  public static void premain(String options, Instrumentation instrumentation) {
    instrumentation.addTransformer(new ClassFileTransformer() {
      @Override public byte[] transform(ClassLoader loader, String name, Class<?> old,
          ProtectionDomain domain, byte[] bytes) {
        if (!SELECTED.contains(name)) return null;
        try {
          byte[] transformed = transformBytes(name, bytes);
          if (name.equals(TARGET)) System.err.println("ZK04_ACTOR_V2_TARGET_TRANSFORMED");
          return transformed;
        }
        catch (Throwable failure) {
          System.err.println("ZK04_ACTOR_V2_TRANSFORM_ERROR " + name + " " + failure);
          failure.printStackTrace();
          return null;
        }
      }
    }, true);
    try {
      // Frame computation for another selected class can load this superclass
      // before its first instrumented use. Force one explicit retransform here.
      Class<?> target = Class.forName(TARGET.replace('/', '.'), false,
          ClassLoader.getSystemClassLoader());
      instrumentation.retransformClasses(target);
      System.err.println("ZK04_ACTOR_V2_TARGET_RETRANSFORMED");
    } catch (Throwable failure) {
      throw new IllegalStateException("ZK04 selected target class lacks retransformation", failure);
    }
  }

  static byte[] transformBytes(String className, byte[] bytes) {
    ClassReader reader = new ClassReader(bytes);
    ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_FRAMES);
    reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
      @Override public MethodVisitor visitMethod(int access, String name, String descriptor,
          String signature, String[] exceptions) {
        MethodVisitor delegate = super.visitMethod(access, name, descriptor, signature, exceptions);
        if (delegate == null) return null;
        boolean test = className.equals(TEST) && name.equals("testRevalidateCount")
            && descriptor.equals("()V");
        boolean target = className.equals(TARGET) && name.equals("processConnectRequest")
            && descriptor.equals("(Lorg/apache/zookeeper/server/ServerCnxn;Ljava/nio/ByteBuffer;)V");
        boolean file = className.equals(PEER) && (name.equals("readLongFromFile")
            || name.equals("writeLongToFile"));
        boolean client = className.equals(CLIENT) && name.equals("doIO");
        boolean server = className.equals(SERVER) && (name.equals("doIO")
            || name.equals("sendBufferSync") || name.equals("handleWrite")
            || name.equals("readPayload"));
        boolean production = target || file || client || server;
        return new MethodVisitor(Opcodes.ASM9, delegate) {
          int line = -1;
          boolean registered;
          @Override public void visitLineNumber(int number, Label start) {
            line = number;
            super.visitLineNumber(number, start);
            if (production) {
              super.visitLdcInsn(className.replace('/', '.'));
              super.visitLdcInsn(name);
              super.visitLdcInsn(number);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "coverage",
                  "(Ljava/lang/String;Ljava/lang/String;I)V", false);
            }
          }
          @Override public void visitVarInsn(int opcode, int variable) {
            super.visitVarInsn(opcode, variable);
            if (test && opcode == Opcodes.ASTORE && variable == 5 && !registered) {
              registered = true;
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitVarInsn(Opcodes.ILOAD, 2);
              super.visitVarInsn(Opcodes.ILOAD, 3);
              super.visitVarInsn(Opcodes.ALOAD, 5);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "registerTest",
                  "(Ljava/lang/Object;IILjava/lang/Object;)V", false);
            }
          }
          @Override public void visitMethodInsn(int opcode, String owner, String invoked,
              String calledDesc, boolean isInterface) {
            if (test && owner.equals("org/apache/zookeeper/test/ClientBase$CountdownWatcher")
                && invoked.equals("waitForConnected") && line == 66) {
              super.visitMethodInsn(opcode, owner, invoked, calledDesc, isInterface);
              super.visitVarInsn(Opcodes.ALOAD, 5);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "bindInitialSession",
                  "(Ljava/lang/Object;)V", false);
              return;
            }
            if (owner.equals("java/nio/channels/SocketChannel")
                && (invoked.equals("read") || invoked.equals("write")) && (client || server)) {
              String site = className.replace('/', '.') + "#" + name + ":" + line + ":"
                  + owner.replace('/', '.') + "#" + invoked + calledDesc;
              super.visitVarInsn(Opcodes.ALOAD, 0);
              if (client) super.visitVarInsn(Opcodes.ALOAD, 2);
              super.visitLdcInsn(site);
              super.visitLdcInsn(invoked);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE,
                  client ? "clientIo" : "serverIo",
                  client
                      ? "(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/String;Ljava/lang/String;)V"
                      : "(Ljava/lang/Object;Ljava/lang/String;Ljava/lang/String;)V", false);
            }
            if (file && ((name.equals("readLongFromFile")
                && owner.equals("java/io/FileReader") && invoked.equals("<init>"))
                || (name.equals("writeLongToFile")
                && owner.equals("org/apache/zookeeper/common/AtomicFileWritingIdiom")
                && invoked.equals("<init>")))) {
              String site = className.replace('/', '.') + "#" + name + ":" + line + ":"
                  + owner.replace('/', '.') + "#" + invoked + calledDesc;
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitLdcInsn(site);
              super.visitLdcInsn(name.equals("readLongFromFile") ? "read" : "write");
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "peerFileIo",
                  "(Ljava/lang/Object;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V", false);
            }
            super.visitMethodInsn(opcode, owner, invoked, calledDesc, isInterface);
          }
          @Override public void visitJumpInsn(int opcode, Label label) {
            if (target && line == 1431 && opcode == Opcodes.IFLE) {
              super.visitInsn(Opcodes.DUP);
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitVarInsn(Opcodes.ALOAD, 4);
              super.visitVarInsn(Opcodes.LLOAD, 5);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "targetGuard",
                  "(ILjava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;J)V", false);
            }
            super.visitJumpInsn(opcode, label);
          }
          @Override public void visitInsn(int opcode) {
            if (target && line == 1441 && opcode == Opcodes.ATHROW) {
              super.visitInsn(Opcodes.DUP);
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitVarInsn(Opcodes.ALOAD, 4);
              super.visitVarInsn(Opcodes.LLOAD, 5);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "targetThrow",
                  "(Ljava/lang/Throwable;Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/Object;J)V", false);
            }
            super.visitInsn(opcode);
          }
        };
      }
    }, 0);
    return writer.toByteArray();
  }
}
