import java.io.IOException;
import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.security.ProtectionDomain;
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;
import org.apache.hadoop.hbase.client.RegionReplicaUtil;
import org.apache.hadoop.hbase.regionserver.HRegion;
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
  private static final Map<String, Integer> targetHits = new HashMap<>();
  private static final ThreadLocal<TargetContext> activeTarget = new ThreadLocal<>();
  private static final String plan = System.getProperty("hbase32.fault.plan", "");
  private static final String[] plannedSteps = plan.isEmpty() ? new String[0] : plan.split(";");
  private static int nextStep;
  private static long sequence;

  private static final class TargetContext {
    final String primary;
    final int replica;
    final int ordinal;
    int rpcOrdinal;

    TargetContext(String primary, int replica, int ordinal) {
      this.primary = primary;
      this.replica = replica;
      this.ordinal = ordinal;
    }
  }

  public static void premain(String args, Instrumentation instrumentation) {
    instrumentation.addTransformer(new ProbeTransformer());
  }

  public static synchronized void beforeFlushRpc(byte[] regionName) throws IOException {
    // HBase allocates a fresh numeric region ID in every MiniHBaseCluster run.
    // Match across runs by table and start key; keep the complete region bytes
    // in the trace so that a fault can only be credited to its actual region.
    int finalComma = -1;
    for (int i = 0; i < regionName.length; i++) {
      if (regionName[i] == ',') finalComma = i;
    }
    byte[] stableBytes = new byte[finalComma < 0 ? regionName.length : finalComma];
    System.arraycopy(regionName, 0, stableBytes, 0, stableBytes.length);
    String stableRegion = Base64.getUrlEncoder().withoutPadding().encodeToString(stableBytes);
    String fullRegion = Base64.getUrlEncoder().withoutPadding().encodeToString(regionName);
    TargetContext context = activeTarget.get();
    boolean contextMatch = context != null && context.primary.equals(fullRegion);
    int rpcOrdinal = contextMatch ? ++context.rpcOrdinal : 0;
    String selector = "RPC_FLUSH_REGION~" + stableRegion + "~replica-"
      + (contextMatch ? context.replica : "unknown") + "~target-"
      + (contextMatch ? context.ordinal : "unknown") + "~rpc-" + rpcOrdinal
      + "~FlushRegionCallable.call:81";
    long id = ++sequence;
    System.err.println("HBASE32 IO seq=" + id + " selector=" + selector
      + " raw_primary_region=" + fullRegion + " context_match=" + contextMatch);
    if (!contextMatch || nextStep >= plannedSteps.length
        || !plannedSteps[nextStep].startsWith(selector + "~")) {
      return;
    }
    String kind = plannedSteps[nextStep].substring(selector.length() + 1);
    if (!kind.equals("DO_NOT_RETRY_IOEXCEPTION") && !kind.equals("IOEXCEPTION")
        && !kind.equals("SOCKET_TIMEOUT") && !kind.equals("EOF_EXCEPTION")
        && !kind.equals("TABLE_NOT_FOUND")) return;
    int step = ++nextStep;
    System.err.println("HBASE32 FAULT_MATCHED seq=" + id + " selector=" + selector
      + " raw_primary_region=" + fullRegion + " step=" + step + " kind=" + kind);
    System.err.println("HBASE32 FAULT_APPLIED seq=" + id + " selector=" + selector
      + " raw_primary_region=" + fullRegion + " step=" + step + " kind=" + kind);
    String message = "HBASE32 injected flush RPC " + kind + " for " + selector;
    switch (kind) {
      case "DO_NOT_RETRY_IOEXCEPTION":
        throw new org.apache.hadoop.hbase.DoNotRetryIOException(message);
      case "SOCKET_TIMEOUT":
        throw new java.net.SocketTimeoutException(message);
      case "EOF_EXCEPTION":
        throw new java.io.EOFException(message);
      case "TABLE_NOT_FOUND":
        throw new org.apache.hadoop.hbase.TableNotFoundException(message);
      default:
        throw new IOException(message);
    }
  }

  public static synchronized void targetEnter(HRegion region) {
    String primary = Base64.getUrlEncoder().withoutPadding().encodeToString(
      RegionReplicaUtil.getRegionInfoForDefaultReplica(region.getRegionInfo()).getRegionName());
    String secondary = Base64.getUrlEncoder().withoutPadding().encodeToString(
      region.getRegionInfo().getRegionName());
    int replica = region.getRegionInfo().getReplicaId();
    String targetKey = primary + "~" + replica;
    int ordinal = targetHits.getOrDefault(targetKey, 0) + 1;
    targetHits.put(targetKey, ordinal);
    activeTarget.set(new TargetContext(primary, replica, ordinal));
    System.err.println("HBASE32 TARGET_ENTER seq=" + (++sequence)
      + " method=RegionReplicaFlushHandler.triggerFlushInPrimaryRegion"
      + " raw_primary_region=" + primary + " raw_secondary_region=" + secondary
      + " replica_id=" + replica + " target_ordinal=" + ordinal);
  }

  public static synchronized void targetRethrow(HRegion region, Throwable cause) {
    String primary = Base64.getUrlEncoder().withoutPadding().encodeToString(
      RegionReplicaUtil.getRegionInfoForDefaultReplica(region.getRegionInfo()).getRegionName());
    TargetContext context = activeTarget.get();
    System.err.println("HBASE32 TARGET_B7_RETHROW seq=" + (++sequence)
      + " raw_primary_region=" + primary + " replica_id="
      + region.getRegionInfo().getReplicaId() + " target_ordinal="
      + (context == null ? "unknown" : context.ordinal) + " exception="
      + cause.getClass().getName() + " message=" + String.valueOf(cause.getMessage()));
  }

  public static synchronized void targetGuard(HRegion region, Throwable cause) {
    String primary = Base64.getUrlEncoder().withoutPadding().encodeToString(
      RegionReplicaUtil.getRegionInfoForDefaultReplica(region.getRegionInfo()).getRegionName());
    TargetContext context = activeTarget.get();
    System.err.println("HBASE32 TARGET_GUARD seq=" + (++sequence)
      + " raw_primary_region=" + primary + " replica_id="
      + region.getRegionInfo().getReplicaId() + " target_ordinal="
      + (context == null ? "unknown" : context.ordinal) + " exception="
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
                private int exceptionSlot = -1;

                @Override
                public void visitCode() {
                  super.visitCode();
                  super.visitVarInsn(Opcodes.ALOAD, 1);
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32Agent", "targetEnter",
                                        "(Lorg/apache/hadoop/hbase/regionserver/HRegion;)V", false);
                }

                @Override
                public void visitLineNumber(int sourceLine, org.objectweb.asm.Label start) {
                  line = sourceLine;
                  super.visitLineNumber(sourceLine, start);
                  if (sourceLine == 130) {
                    if (exceptionSlot < 0) {
                      throw new IllegalStateException("Could not resolve IOException catch local");
                    }
                    super.visitVarInsn(Opcodes.ALOAD, 1);
                    super.visitVarInsn(Opcodes.ALOAD, exceptionSlot);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32Agent", "targetGuard",
                      "(Lorg/apache/hadoop/hbase/regionserver/HRegion;Ljava/lang/Throwable;)V",
                      false);
                  }
                }

                @Override
                public void visitVarInsn(int opcode, int variable) {
                  if (line == 129 && opcode == Opcodes.ASTORE) exceptionSlot = variable;
                  super.visitVarInsn(opcode, variable);
                }

                @Override
                public void visitInsn(int opcode) {
                  if (opcode == Opcodes.ATHROW && line == 136) {
                    super.visitInsn(Opcodes.DUP);
                    super.visitVarInsn(Opcodes.ALOAD, 1);
                    super.visitInsn(Opcodes.SWAP);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32Agent",
                                          "targetRethrow",
                                          "(Lorg/apache/hadoop/hbase/regionserver/HRegion;Ljava/lang/Throwable;)V",
                                          false);
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
