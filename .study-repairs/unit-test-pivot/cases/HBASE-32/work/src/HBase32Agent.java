import java.io.IOException;
import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.security.ProtectionDomain;
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Case-local runtime probes for the original region-replica failover JUnit. */
public final class HBase32Agent {
  private static final String HANDLER =
    "org/apache/hadoop/hbase/regionserver/handler/RegionReplicaFlushHandler";
  private static final String CALLABLE =
    "org/apache/hadoop/hbase/client/FlushRegionCallable";
  private static final Map<String, Integer> hits = new HashMap<>();
  private static final String plan = System.getProperty("hbase32.fault.plan", "");
  private static long sequence;

  public static void premain(String args, Instrumentation instrumentation) {
    instrumentation.addTransformer(new ProbeTransformer());
  }

  public static synchronized void beforeFlushRpc(byte[] regionName) throws IOException {
    String region = Base64.getUrlEncoder().withoutPadding().encodeToString(regionName);
    String key = "RPC_FLUSH_REGION~" + region + "~FlushRegionCallable.call:81";
    int ordinal = hits.getOrDefault(key, 0) + 1;
    hits.put(key, ordinal);
    String selector = key + "~" + ordinal;
    long id = ++sequence;
    System.err.println("HBASE32 IO seq=" + id + " selector=" + selector);
    if (!plan.equals(selector + "~DO_NOT_RETRY_IOEXCEPTION")) return;
    System.err.println("HBASE32 FAULT_MATCHED seq=" + id + " selector=" + selector);
    System.err.println("HBASE32 FAULT_APPLIED seq=" + id + " selector=" + selector);
    throw new org.apache.hadoop.hbase.DoNotRetryIOException(
      "HBASE32 injected flush RPC IOException for " + selector);
  }

  public static void targetEnter() {
    System.err.println("HBASE32 TARGET_ENTER method=RegionReplicaFlushHandler.triggerFlushInPrimaryRegion");
  }

  public static void targetRethrow(Throwable cause) {
    System.err.println("HBASE32 TARGET_B7_RETHROW exception="
      + cause.getClass().getName() + " message=" + String.valueOf(cause.getMessage()));
  }

  private static final class ProbeTransformer implements ClassFileTransformer {
    @Override
    public byte[] transform(ClassLoader loader, String name, Class<?> redefining,
                            ProtectionDomain domain, byte[] original) {
      if (!HANDLER.equals(name) && !CALLABLE.equals(name)) return null;
      try {
        ClassReader reader = new ClassReader(original);
        ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
        reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
          @Override
          public MethodVisitor visitMethod(int access, String method, String descriptor,
                                           String signature, String[] exceptions) {
            MethodVisitor delegate = super.visitMethod(access, method, descriptor,
                                                       signature, exceptions);
            if (HANDLER.equals(name) && method.equals("triggerFlushInPrimaryRegion")
                && descriptor.endsWith(")V")) {
              return new MethodVisitor(Opcodes.ASM9, delegate) {
                private int line;

                @Override
                public void visitCode() {
                  super.visitCode();
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32Agent", "targetEnter",
                                        "()V", false);
                }

                @Override
                public void visitLineNumber(int sourceLine, org.objectweb.asm.Label start) {
                  line = sourceLine;
                  super.visitLineNumber(sourceLine, start);
                }

                @Override
                public void visitInsn(int opcode) {
                  if (opcode == Opcodes.ATHROW && line == 136) {
                    super.visitInsn(Opcodes.DUP);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32Agent",
                                          "targetRethrow", "(Ljava/lang/Throwable;)V", false);
                  }
                  super.visitInsn(opcode);
                }
              };
            }
            if (CALLABLE.equals(name) && method.equals("call")) {
              return new MethodVisitor(Opcodes.ASM9, delegate) {
                @Override
                public void visitMethodInsn(int opcode, String owner, String invoked,
                                            String invokedDescriptor, boolean isInterface) {
                  if (invoked.equals("flushRegion")
                      && invokedDescriptor.contains("FlushRegionRequest")) {
                    super.visitVarInsn(Opcodes.ALOAD, 0);
                    super.visitFieldInsn(Opcodes.GETFIELD, CALLABLE, "regionName", "[B");
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32Agent",
                                          "beforeFlushRpc", "([B)V", false);
                  }
                  super.visitMethodInsn(opcode, owner, invoked, invokedDescriptor, isInterface);
                }
              };
            }
            return delegate;
          }
        }, 0);
        System.err.println("HBASE32 PROBE_WOVEN class=" + name);
        return writer.toByteArray();
      } catch (Throwable failure) {
        System.err.println("HBASE32 PROBE_FAILED class=" + name + " error=" + failure);
        failure.printStackTrace(System.err);
        return null;
      }
    }
  }
}
