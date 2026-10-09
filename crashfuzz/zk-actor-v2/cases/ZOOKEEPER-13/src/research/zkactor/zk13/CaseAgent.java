package research.zkactor.zk13;

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

/** Original ReadOnlyModeTest and peer-1/global-session receiver instrumentation. */
public final class CaseAgent {
  static final String TEST = "org/apache/zookeeper/test/ReadOnlyModeTest";
  static final String CLIENT = "org/apache/zookeeper/ClientCnxnSocketNIO";
  static final String SERVER = "org/apache/zookeeper/server/NIOServerCnxn";
  static final String TARGET = "org/apache/zookeeper/server/quorum/ReadOnlyZooKeeperServer";
  static final String BRIDGE = "research/zkactor/zk13/Bridge";
  static final String PROBE = "research/zkactor/Probe";
  static final Set<String> SELECTED = new HashSet<>(Arrays.asList(TEST, CLIENT, SERVER, TARGET));

  private CaseAgent() {}

  public static void premain(String options, Instrumentation instrumentation) {
    instrumentation.addTransformer(new ClassFileTransformer() {
      @Override public byte[] transform(ClassLoader loader, String name, Class<?> clazz,
          ProtectionDomain domain, byte[] bytes) {
        if (!SELECTED.contains(name)) return null;
        try { return transformBytes(name, bytes); }
        catch (Throwable error) {
          System.err.println("ZK13_ACTOR_V2_TRANSFORM_ERROR " + name + " " + error);
          error.printStackTrace();
          return null;
        }
      }
    });
  }

  static byte[] transformBytes(String className, byte[] bytes) {
    if (!SELECTED.contains(className)) throw new IllegalArgumentException(className);
    ClassReader reader = new ClassReader(bytes);
    ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_FRAMES);
    reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
      @Override public MethodVisitor visitMethod(int access, String name, String descriptor,
          String signature, String[] exceptions) {
        MethodVisitor delegate = super.visitMethod(access, name, descriptor, signature, exceptions);
        if (delegate == null) return null;
        boolean workload = className.equals(TEST) && name.equals("testGlobalSessionInRO")
            && descriptor.equals("()V");
        boolean target = className.equals(TARGET) && name.equals("validateSession")
            && descriptor.equals("(Lorg/apache/zookeeper/server/ServerCnxn;J)V");
        boolean production = target || (className.equals(CLIENT) && name.equals("doIO"))
            || (className.equals(SERVER) && (name.equals("doIO")
                || name.equals("sendBufferSync") || name.equals("handleWrite")
                || name.equals("readPayload")));
        return new MethodVisitor(Opcodes.ASM9, delegate) {
          int line = -1;
          int clientsConstructed;
          int connectedWaits;
          boolean storeFirstClient;

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
            if (target && number == 123) {
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitVarInsn(Opcodes.LLOAD, 2);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "targetGuard",
                  "(Ljava/lang/Object;Ljava/lang/Object;J)V", false);
            }
          }

          @Override public void visitVarInsn(int opcode, int variable) {
            super.visitVarInsn(opcode, variable);
            if (workload && storeFirstClient && opcode == Opcodes.ASTORE && variable == 2) {
              storeFirstClient = false;
              super.visitVarInsn(Opcodes.ALOAD, 2);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "bindInitialClient",
                  "(Ljava/lang/Object;)V", false);
            }
          }

          @Override public void visitInsn(int opcode) {
            if (target && line == 126 && opcode == Opcodes.ATHROW) {
              super.visitInsn(Opcodes.DUP);
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitVarInsn(Opcodes.LLOAD, 2);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "targetThrow",
                  "(Ljava/lang/Throwable;Ljava/lang/Object;Ljava/lang/Object;J)V", false);
            }
            super.visitInsn(opcode);
          }

          @Override public void visitMethodInsn(int opcode, String owner, String invoked,
              String calledDesc, boolean isInterface) {
            if (workload && owner.equals("org/apache/zookeeper/ZooKeeper")
                && invoked.equals("<init>")) {
              clientsConstructed++;
              if (clientsConstructed == 1) {
                if (!calledDesc.equals("(Ljava/lang/String;ILorg/apache/zookeeper/Watcher;Z)V")) {
                  throw new IllegalStateException("unexpected first ZooKeeper constructor");
                }
                storeFirstClient = true;
              }
            }
            boolean socket = owner.equals("java/nio/channels/SocketChannel")
                && (invoked.equals("read") || invoked.equals("write"));
            if (socket && ((className.equals(CLIENT) && name.equals("doIO"))
                || (className.equals(SERVER) && (access & Opcodes.ACC_STATIC) == 0))) {
              String site = className.replace('/', '.') + "#" + name + ":" + line + ":"
                  + owner.replace('/', '.') + "#" + invoked + calledDesc;
              super.visitVarInsn(Opcodes.ALOAD, 0);
              if (className.equals(CLIENT)) super.visitVarInsn(Opcodes.ALOAD, 2);
              super.visitLdcInsn(site);
              super.visitLdcInsn(invoked);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE,
                  className.equals(CLIENT) ? "clientIo" : "serverIo",
                  className.equals(CLIENT)
                      ? "(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/String;Ljava/lang/String;)V"
                      : "(Ljava/lang/Object;Ljava/lang/String;Ljava/lang/String;)V", false);
            }
            super.visitMethodInsn(opcode, owner, invoked, calledDesc, isInterface);
            if (workload && owner.equals("org/apache/zookeeper/test/QuorumUtil")
                && invoked.equals("startQuorum") && line == 248) {
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "bindCluster",
                  "(Ljava/lang/Object;)V", false);
            }
            if (workload && owner.equals("org/apache/zookeeper/test/ClientBase$CountdownWatcher")
                && invoked.equals("waitForConnected") && line == 252) {
              connectedWaits++;
              if (connectedWaits != 1) throw new IllegalStateException("first wait duplicated");
              super.visitVarInsn(Opcodes.ALOAD, 2);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "bindInitialSession",
                  "(Ljava/lang/Object;)V", false);
            }
            if (workload && owner.equals("org/apache/zookeeper/test/QuorumUtil")
                && invoked.equals("shutdown") && line == 256) {
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "enterReadOnlyPhase",
                  "(Ljava/lang/Object;)V", false);
            }
          }
        };
      }
    }, 0);
    return writer.toByteArray();
  }
}
