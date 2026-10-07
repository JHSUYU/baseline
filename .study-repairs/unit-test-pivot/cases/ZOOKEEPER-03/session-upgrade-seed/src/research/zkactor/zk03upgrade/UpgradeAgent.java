package research.zkactor.zk03upgrade;

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

/** ZK03: original session-upgrade quorum JUnit and global tracker guard. */
public final class UpgradeAgent {
  static final String TEST = "org/apache/zookeeper/test/SessionUpgradeTest";
  static final String CLIENT = "org/apache/zookeeper/ClientCnxnSocketNIO";
  static final String SERVER = "org/apache/zookeeper/server/NIOServerCnxn";
  static final String TRACKER = "org/apache/zookeeper/server/SessionTrackerImpl";
  static final String PEER = "org/apache/zookeeper/server/quorum/QuorumPeer";
  static final String BRIDGE = "research/zkactor/zk03upgrade/UpgradeBridge";
  static final String PROBE = "research/zkactor/Probe";
  private static final Set<String> SELECTED = new HashSet<>(Arrays.asList(
      TEST, CLIENT, SERVER, TRACKER, PEER));

  private UpgradeAgent() {}

  public static void premain(String options, Instrumentation instrumentation) {
    instrumentation.addTransformer(new ClassFileTransformer() {
      @Override public byte[] transform(ClassLoader loader, String className, Class<?> clazz,
          ProtectionDomain domain, byte[] bytes) {
        if (!SELECTED.contains(className)) return null;
        try { return transformBytes(className, bytes); }
        catch (Throwable failure) {
          System.err.println("ZK03_UPGRADE_TRANSFORM_ERROR " + className + " " + failure);
          failure.printStackTrace();
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
        boolean testWorkload = className.equals(TEST)
            && name.equals("testUpgradeWithEphemeral") && descriptor.equals("(Z)V");
        boolean target = className.equals(TRACKER) && name.equals("setOwner")
            && descriptor.equals("(JLjava/lang/Object;)V");
        boolean peerFile = className.equals(PEER) && (name.equals("readLongFromFile")
            || name.equals("writeLongToFile"));
        boolean production = target || peerFile || (className.equals(CLIENT)
            && name.equals("doIO")) || (className.equals(SERVER)
            && (name.equals("doIO") || name.equals("sendBufferSync")
                || name.equals("handleWrite") || name.equals("readPayload")));
        return new MethodVisitor(Opcodes.ASM9, delegate) {
          int line = -1;
          int constructors = 0;
          boolean storeInitialClient;
          boolean storeMovedClient;

          @Override public void visitCode() {
            super.visitCode();
            if (testWorkload) {
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "enterTest",
                  "(Ljava/lang/Object;)V", false);
            }
          }

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
            if (target && number == 329) {
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.LLOAD, 1);
              super.visitVarInsn(Opcodes.ALOAD, 3);
              super.visitVarInsn(Opcodes.ALOAD, 4);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "targetGuard",
                  "(Ljava/lang/Object;JLjava/lang/Object;Ljava/lang/Object;)V", false);
            }
            if (testWorkload && number == 180) {
              super.visitVarInsn(Opcodes.ALOAD, 9);
              super.visitVarInsn(Opcodes.LLOAD, 10);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "bindUpgradedSession",
                  "(Ljava/lang/Object;J)V", false);
            }
            if (testWorkload && number == 182) {
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE,
                  "beginUpgradeReconnect", "()V", false);
            }
            if (testWorkload && number == 192) {
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE,
                  "endUpgradeReconnect", "()V", false);
            }
          }

          @Override public void visitVarInsn(int opcode, int variable) {
            super.visitVarInsn(opcode, variable);
            if (testWorkload && storeInitialClient && opcode == Opcodes.ASTORE && variable == 9) {
              storeInitialClient = false;
              super.visitVarInsn(Opcodes.ALOAD, 9);
              super.visitVarInsn(Opcodes.ILOAD, 6);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "registerInitial",
                  "(Ljava/lang/Object;I)V", false);
            }
            if (testWorkload && storeMovedClient && opcode == Opcodes.ASTORE && variable == 9) {
              storeMovedClient = false;
              super.visitVarInsn(Opcodes.ALOAD, 9);
              super.visitVarInsn(Opcodes.ILOAD, 5);
              super.visitVarInsn(Opcodes.LLOAD, 10);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "registerReconnected",
                  "(Ljava/lang/Object;IJ)V", false);
            }
          }

          @Override public void visitInsn(int opcode) {
            if (target && line == 330 && opcode == Opcodes.ATHROW) {
              super.visitInsn(Opcodes.DUP);
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.LLOAD, 1);
              super.visitVarInsn(Opcodes.ALOAD, 3);
              super.visitVarInsn(Opcodes.ALOAD, 4);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, BRIDGE, "targetThrow",
                  "(Ljava/lang/Throwable;Ljava/lang/Object;JLjava/lang/Object;Ljava/lang/Object;)V", false);
            }
            super.visitInsn(opcode);
          }

          @Override public void visitMethodInsn(int opcode, String owner, String invoked,
              String calledDesc, boolean isInterface) {
            if (testWorkload && owner.equals("org/apache/zookeeper/test/DisconnectableZooKeeper")
                && invoked.equals("<init>")) {
              constructors++;
              if (constructors > 4) throw new IllegalStateException("more than four clients");
              if (constructors == 1 && calledDesc.equals(
                  "(Ljava/lang/String;ILorg/apache/zookeeper/Watcher;)V")) {
                storeInitialClient = true;
              } else if (constructors == 2 && calledDesc.equals(
                  "(Ljava/lang/String;ILorg/apache/zookeeper/Watcher;J[B)V")) {
                storeMovedClient = true;
              } else if (constructors <= 2) {
                throw new IllegalStateException("unexpected upgrade constructor " + calledDesc);
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
            if (peerFile && ((name.equals("readLongFromFile")
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
        };
      }
    }, 0);
    return writer.toByteArray();
  }
}
