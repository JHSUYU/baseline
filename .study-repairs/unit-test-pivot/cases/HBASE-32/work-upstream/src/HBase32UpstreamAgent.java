import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.security.ProtectionDomain;
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.RegionInfo;
import org.apache.hadoop.hbase.client.RegionReplicaUtil;
import org.apache.hadoop.hbase.regionserver.HRegion;
import org.apache.hadoop.hbase.regionserver.RegionServerServices.RegionStateTransitionContext;
import org.apache.hadoop.hbase.shaded.protobuf.generated.WALProtos.FlushDescriptor;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Passive, case-local probes for I/O that can influence the B7 check. */
public final class HBase32UpstreamAgent {
  private static final String HANDLER =
    "org/apache/hadoop/hbase/regionserver/handler/RegionReplicaFlushHandler";
  private static final String META = "org/apache/hadoop/hbase/MetaTableAccessor";
  private static final String CONN = "org/apache/hadoop/hbase/client/ConnectionImplementation";
  private static final String RS = "org/apache/hadoop/hbase/regionserver/HRegionServer";
  private static final String WAL = "org/apache/hadoop/hbase/regionserver/wal/WALUtil";
  private static final Map<String, Integer> targetHits = new HashMap<>();
  private static final ThreadLocal<Context> current = new ThreadLocal<>();
  private static long sequence;

  private static final class Context {
    final String primary;
    final int replica;
    final int ordinal;
    int metaGets;
    int metaScans;

    Context(String primary, int replica, int ordinal) {
      this.primary = primary;
      this.replica = replica;
      this.ordinal = ordinal;
    }
  }

  public static void premain(String arguments, Instrumentation instrumentation) {
    instrumentation.addTransformer(new Probes());
  }

  private static String raw(byte[] bytes) {
    return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
  }

  private static String stable(byte[] bytes) {
    int comma = -1;
    for (int i = 0; i < bytes.length; i++) if (bytes[i] == ',') comma = i;
    byte[] prefix = new byte[comma < 0 ? bytes.length : comma];
    System.arraycopy(bytes, 0, prefix, 0, prefix.length);
    return raw(prefix);
  }

  private static boolean inTarget() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (frame.getClassName().equals(
            "org.apache.hadoop.hbase.regionserver.handler.RegionReplicaFlushHandler")
          && frame.getMethodName().equals("triggerFlushInPrimaryRegion")) return true;
    }
    return false;
  }

  public static synchronized void targetEnter(HRegion region) {
    RegionInfo info = region.getRegionInfo();
    String primary = raw(RegionReplicaUtil.getRegionInfoForDefaultReplica(info).getRegionName());
    int replica = info.getReplicaId();
    String key = primary + "~" + replica;
    int ordinal = targetHits.getOrDefault(key, 0) + 1;
    targetHits.put(key, ordinal);
    current.set(new Context(primary, replica, ordinal));
    System.err.println("HBASE32U TARGET seq=" + (++sequence) + " raw_primary_region=" + primary
      + " raw_secondary_region=" + raw(info.getRegionName())
      + " replica=" + replica + " target_ordinal=" + ordinal);
  }

  public static synchronized void beforeMetaStateGet(TableName table) {
    Context ctx = current.get();
    if (ctx == null || !inTarget()) return;
    int ordinal = ++ctx.metaGets;
    System.err.println("HBASE32U META_STATE_GET seq=" + (++sequence)
      + " table=" + table.getNameAsString() + " raw_primary_region=" + ctx.primary
      + " replica=" + ctx.replica + " target_ordinal=" + ctx.ordinal
      + " get_ordinal=" + ordinal);
  }

  public static synchronized void beforeMetaScan(TableName table, byte[] row) {
    Context ctx = current.get();
    if (ctx == null || !inTarget()) return;
    int ordinal = ++ctx.metaScans;
    System.err.println("HBASE32U META_SCAN_NEXT seq=" + (++sequence)
      + " table=" + table.getNameAsString() + " row=" + raw(row)
      + " raw_primary_region=" + ctx.primary + " replica=" + ctx.replica
      + " target_ordinal=" + ctx.ordinal + " scan_ordinal=" + ordinal);
  }

  public static synchronized void beforeMasterReport(RegionStateTransitionContext context) {
    if (!context.getCode().name().equals("OPENED")) return;
    for (RegionInfo info : context.getHris()) {
      if (!info.getTable().getNameAsString().startsWith("testLotsOfRegionRepli")) continue;
      String primary = raw(RegionReplicaUtil.getRegionInfoForDefaultReplica(info).getRegionName());
      System.err.println("HBASE32U MASTER_OPENED_RPC seq=" + (++sequence)
        + " raw_primary_region=" + primary
        + " raw_secondary_region=" + raw(info.getRegionName())
        + " stable_region=" + stable(info.getRegionName())
        + " replica=" + info.getReplicaId());
    }
  }

  public static synchronized void beforeFlushMarker(RegionInfo info, FlushDescriptor descriptor,
                                                      boolean sync) {
    if (!info.getTable().getNameAsString().startsWith("testLotsOfRegionRepli")) return;
    boolean fromFlushRpc = false;
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (frame.getClassName().equals(
            "org.apache.hadoop.hbase.regionserver.RSRpcServices")
          && frame.getMethodName().equals("flushRegion")) fromFlushRpc = true;
    }
    System.err.println("HBASE32U WAL_FLUSH_MARKER seq=" + (++sequence)
      + " raw_primary_region=" + raw(info.getRegionName())
      + " stable_region=" + stable(info.getRegionName())
      + " action=" + descriptor.getAction().name() + " sync=" + sync
      + " from_flush_rpc=" + fromFlushRpc);
  }

  private static final class Probes implements ClassFileTransformer {
    @Override
    public byte[] transform(ClassLoader loader, String className, Class<?> redefining,
                            ProtectionDomain domain, byte[] original) {
      if (!HANDLER.equals(className) && !META.equals(className) && !CONN.equals(className)
          && !RS.equals(className) && !WAL.equals(className)) return null;
      try {
        ClassReader reader = new ClassReader(original);
        ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
        reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
          @Override
          public MethodVisitor visitMethod(int access, String method, String descriptor,
                                           String signature, String[] exceptions) {
            MethodVisitor delegate = super.visitMethod(access, method, descriptor,
                                                       signature, exceptions);
            if (HANDLER.equals(className) && method.equals("triggerFlushInPrimaryRegion")) {
              return new MethodVisitor(Opcodes.ASM9, delegate) {
                @Override
                public void visitCode() {
                  super.visitCode();
                  super.visitVarInsn(Opcodes.ALOAD, 1);
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32UpstreamAgent", "targetEnter",
                    "(Lorg/apache/hadoop/hbase/regionserver/HRegion;)V", false);
                }
              };
            }
            if (META.equals(className) && method.equals("getTableState")
                && descriptor.startsWith("(Lorg/apache/hadoop/hbase/client/Connection;")) {
              return new MethodVisitor(Opcodes.ASM9, delegate) {
                @Override
                public void visitMethodInsn(int opcode, String owner, String invoked,
                                            String desc, boolean isInterface) {
                  if (invoked.equals("get") && owner.equals("org/apache/hadoop/hbase/client/Table")
                      && desc.startsWith("(Lorg/apache/hadoop/hbase/client/Get;)")) {
                    super.visitVarInsn(Opcodes.ALOAD, 1);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32UpstreamAgent",
                      "beforeMetaStateGet", "(Lorg/apache/hadoop/hbase/TableName;)V", false);
                  }
                  super.visitMethodInsn(opcode, owner, invoked, desc, isInterface);
                }
              };
            }
            if (CONN.equals(className) && method.equals("locateRegionInMeta")) {
              return new MethodVisitor(Opcodes.ASM9, delegate) {
                @Override
                public void visitMethodInsn(int opcode, String owner, String invoked,
                                            String desc, boolean isInterface) {
                  if (invoked.equals("next")
                      && owner.equals("org/apache/hadoop/hbase/client/ReversedClientScanner")) {
                    super.visitVarInsn(Opcodes.ALOAD, 1);
                    super.visitVarInsn(Opcodes.ALOAD, 2);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32UpstreamAgent",
                      "beforeMetaScan", "(Lorg/apache/hadoop/hbase/TableName;[B)V", false);
                  }
                  super.visitMethodInsn(opcode, owner, invoked, desc, isInterface);
                }
              };
            }
            if (RS.equals(className) && method.equals("reportRegionStateTransition")) {
              return new MethodVisitor(Opcodes.ASM9, delegate) {
                @Override
                public void visitMethodInsn(int opcode, String owner, String invoked,
                                            String desc, boolean isInterface) {
                  if (invoked.equals("reportRegionStateTransition")
                      && owner.contains("RegionServerStatusService")) {
                    super.visitVarInsn(Opcodes.ALOAD, 1);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32UpstreamAgent",
                      "beforeMasterReport",
                      "(Lorg/apache/hadoop/hbase/regionserver/RegionServerServices$RegionStateTransitionContext;)V",
                      false);
                  }
                  super.visitMethodInsn(opcode, owner, invoked, desc, isInterface);
                }
              };
            }
            if (WAL.equals(className) && method.equals("writeFlushMarker")) {
              return new MethodVisitor(Opcodes.ASM9, delegate) {
                @Override
                public void visitCode() {
                  super.visitCode();
                  super.visitVarInsn(Opcodes.ALOAD, 2);
                  super.visitVarInsn(Opcodes.ALOAD, 3);
                  super.visitVarInsn(Opcodes.ILOAD, 4);
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32UpstreamAgent",
                    "beforeFlushMarker",
                    "(Lorg/apache/hadoop/hbase/client/RegionInfo;Lorg/apache/hadoop/hbase/shaded/protobuf/generated/WALProtos$FlushDescriptor;Z)V",
                    false);
                }
              };
            }
            return delegate;
          }
        }, 0);
        System.err.println("HBASE32U PROBE_WOVEN class=" + className);
        return writer.toByteArray();
      } catch (Throwable error) {
        System.err.println("HBASE32U PROBE_FAILED class=" + className + " error=" + error);
        error.printStackTrace(System.err);
        return null;
      }
    }
  }
}
