import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.security.ProtectionDomain;
import java.time.Instant;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.locks.Lock;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Trace-only observer for the s203 ServerStateNode lock identity question. */
public final class HBase32LockDiagAgent {
  private static final String NODE =
      "org/apache/hadoop/hbase/master/assignment/ServerStateNode";
  private static final String MANAGER =
      "org/apache/hadoop/hbase/master/assignment/AssignmentManager";
  private static final String SELF = "HBase32LockDiagAgent";
  private static final Map<Lock, String> LOCKS =
      Collections.synchronizedMap(new IdentityHashMap<Lock, String>());
  private static final AtomicLong SEQUENCE = new AtomicLong();

  public static void premain(String arguments, Instrumentation instrumentation) {
    instrumentation.addTransformer(new Transformer());
  }

  private static void emit(String phase, Lock lock) {
    String node = LOCKS.get(lock);
    if (node == null) return;
    Thread thread = Thread.currentThread();
    System.err.println("HBASE32LOCK seq=" + SEQUENCE.incrementAndGet()
        + " utc=" + Instant.now() + " phase=" + phase
        + " thread_id=" + thread.getId() + " thread=" + thread.getName()
        + " " + node + " lock_identity="
        + Integer.toHexString(System.identityHashCode(lock)));
  }

  public static void mapLock(Lock lock, Object node, String mode) {
    String server;
    try {
      server = String.valueOf(node.getClass().getMethod("getServerName").invoke(node));
    } catch (ReflectiveOperationException error) {
      server = "UNKNOWN:" + error.getClass().getSimpleName();
    }
    LOCKS.put(lock, "mode=" + mode + " node_identity="
        + Integer.toHexString(System.identityHashCode(node)) + " server=" + server);
  }

  public static void beforeLock(Lock lock) { emit("BEFORE_LOCK", lock); }
  public static void afterLock(Lock lock) { emit("ACQUIRED", lock); }
  public static void afterUnlock(Lock lock) { emit("RELEASED", lock); }

  private static final class Transformer implements ClassFileTransformer {
    @Override
    public byte[] transform(ClassLoader loader, String className, Class<?> redefining,
        ProtectionDomain domain, byte[] original) {
      if (!NODE.equals(className) && !MANAGER.equals(className)) return null;
      try {
        ClassReader reader = new ClassReader(original);
        ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
        reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
          @Override
          public MethodVisitor visitMethod(int access, String method, String descriptor,
              String signature, String[] exceptions) {
            MethodVisitor delegate = super.visitMethod(access, method, descriptor,
                signature, exceptions);
            if (NODE.equals(className) &&
                (method.equals("readLock") || method.equals("writeLock")) &&
                descriptor.equals("()Ljava/util/concurrent/locks/Lock;")) {
              final String mode = method.equals("readLock") ? "READ" : "WRITE";
              return new MethodVisitor(Opcodes.ASM9, delegate) {
                @Override
                public void visitInsn(int opcode) {
                  if (opcode == Opcodes.ARETURN) {
                    super.visitInsn(Opcodes.DUP);
                    super.visitVarInsn(Opcodes.ALOAD, 0);
                    super.visitLdcInsn(mode);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, SELF, "mapLock",
                        "(Ljava/util/concurrent/locks/Lock;Ljava/lang/Object;Ljava/lang/String;)V",
                        false);
                  }
                  super.visitInsn(opcode);
                }
              };
            }
            if (MANAGER.equals(className) &&
                (method.equals("reportRegionStateTransition") ||
                    method.equals("submitServerCrash"))) {
              return new MethodVisitor(Opcodes.ASM9, delegate) {
                @Override
                public void visitMethodInsn(int opcode, String owner, String invoked,
                    String desc, boolean isInterface) {
                  boolean lockCall = owner.equals("java/util/concurrent/locks/Lock")
                      && desc.equals("()V") &&
                      (invoked.equals("lock") || invoked.equals("unlock"));
                  if (lockCall && invoked.equals("lock")) {
                    super.visitInsn(Opcodes.DUP);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, SELF, "beforeLock",
                        "(Ljava/util/concurrent/locks/Lock;)V", false);
                  }
                  if (lockCall) super.visitInsn(Opcodes.DUP);
                  super.visitMethodInsn(opcode, owner, invoked, desc, isInterface);
                  if (lockCall) {
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, SELF,
                        invoked.equals("lock") ? "afterLock" : "afterUnlock",
                        "(Ljava/util/concurrent/locks/Lock;)V", false);
                  }
                }
              };
            }
            return delegate;
          }
        }, 0);
        System.err.println("HBASE32LOCK PROBE_WOVEN class=" + className);
        return writer.toByteArray();
      } catch (Throwable error) {
        System.err.println("HBASE32LOCK PROBE_FAILED class=" + className + " error=" + error);
        error.printStackTrace(System.err);
        return null;
      }
    }
  }
}
