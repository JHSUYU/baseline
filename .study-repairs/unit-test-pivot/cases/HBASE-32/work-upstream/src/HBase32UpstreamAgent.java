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
import org.apache.hadoop.hbase.regionserver.HRegionServer;
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
  private static final String SCANNER = "org/apache/hadoop/hbase/client/ScannerCallable";
  private static final String RS = "org/apache/hadoop/hbase/regionserver/HRegionServer";
  private static final String WAL = "org/apache/hadoop/hbase/regionserver/wal/WALUtil";
  private static final Map<String, Integer> targetHits = new HashMap<>();
  private static final Map<String, Integer> reportAttempts = new HashMap<>();
  private static final Map<String, Integer> markerAttempts = new HashMap<>();
  private static final ThreadLocal<Context> current = new ThreadLocal<>();
  private static final ThreadLocal<MarkerContext> marker = new ThreadLocal<>();
  private static long sequence;

  private static final class Context {
    final String primary;
    final int replica;
    final int ordinal;
    int metaGets;
    int metaScans;
    int metaScanRpcs;
    boolean inCatch;

    Context(String primary, int replica, int ordinal) {
      this.primary = primary;
      this.replica = replica;
      this.ordinal = ordinal;
    }
  }

  private static final class MarkerContext {
    final long id;
    final String region;
    final String stableRegion;
    final String action;
    final boolean sync;
    final boolean fromFlushRpc;
    final int ordinal;

    MarkerContext(long id, RegionInfo info, FlushDescriptor descriptor, boolean sync,
                  boolean fromFlushRpc, int ordinal) {
      this.id = id;
      this.region = raw(info.getRegionName());
      this.stableRegion = stable(info.getRegionName());
      this.action = descriptor.getAction().name();
      this.sync = sync;
      this.fromFlushRpc = fromFlushRpc;
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

  public static synchronized void targetCatch() {
    Context ctx = current.get();
    if (ctx != null && inTarget()) ctx.inCatch = true;
  }

  private static String phase(Context ctx) {
    return ctx.inCatch ? "after_rpc_exception" : "before_catch";
  }

  public static synchronized void beforeMetaStateGet(TableName table) {
    Context ctx = current.get();
    if (ctx == null || !inTarget()) return;
    int ordinal = ++ctx.metaGets;
    System.err.println("HBASE32U META_STATE_GET seq=" + (++sequence)
      + " table=" + table.getNameAsString() + " raw_primary_region=" + ctx.primary
      + " replica=" + ctx.replica + " target_ordinal=" + ctx.ordinal
      + " get_ordinal=" + ordinal + " phase=" + phase(ctx));
  }

  public static synchronized void beforeMetaScan(TableName table, byte[] row) {
    Context ctx = current.get();
    if (ctx == null || !inTarget()) return;
    int ordinal = ++ctx.metaScans;
    System.err.println("HBASE32U META_SCAN_NEXT_ATTEMPT seq=" + (++sequence)
      + " table=" + table.getNameAsString() + " row=" + raw(row)
      + " raw_primary_region=" + ctx.primary + " replica=" + ctx.replica
      + " target_ordinal=" + ctx.ordinal + " scan_ordinal=" + ordinal
      + " phase=" + phase(ctx));
  }

  public static synchronized void beforeMetaScanRpc() {
    Context ctx = current.get();
    if (ctx == null || !inTarget()) return;
    boolean inMetaLookup = false;
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (frame.getClassName().equals(
            "org.apache.hadoop.hbase.client.ConnectionImplementation")
          && frame.getMethodName().equals("locateRegionInMeta")) inMetaLookup = true;
    }
    if (!inMetaLookup) return;
    int ordinal = ++ctx.metaScanRpcs;
    System.err.println("HBASE32U META_SCAN_RPC seq=" + (++sequence)
      + " raw_primary_region=" + ctx.primary + " replica=" + ctx.replica
      + " target_ordinal=" + ctx.ordinal + " rpc_ordinal=" + ordinal
      + " phase=" + phase(ctx));
  }

  public static synchronized void beforeMasterReport(HRegionServer server,
                                                     RegionStateTransitionContext context) {
    if (!context.getCode().name().equals("OPENED")) return;
    RegionInfo[] regions = context.getHris();
    long[] procIds = context.getProcIds();
    for (int i = 0; i < regions.length; i++) {
      RegionInfo info = regions[i];
      if (!info.getTable().getNameAsString().startsWith("testLotsOfRegionRepli")) continue;
      String primary = raw(RegionReplicaUtil.getRegionInfoForDefaultReplica(info).getRegionName());
      String secondary = raw(info.getRegionName());
      String key = server.getServerName() + "~" + secondary;
      int attempt = reportAttempts.getOrDefault(key, 0) + 1;
      reportAttempts.put(key, attempt);
      System.err.println("HBASE32U MASTER_OPENED_RPC seq=" + (++sequence)
        + " raw_primary_region=" + primary
        + " raw_secondary_region=" + secondary
        + " stable_region=" + stable(info.getRegionName())
        + " replica=" + info.getReplicaId()
        + " server=" + server.getServerName() + " proc_id=" + procIds[i]
        + " attempt=" + attempt);
    }
  }

  public static synchronized void beforeFlushMarker(RegionInfo info, FlushDescriptor descriptor,
                                                      boolean sync) {
    marker.remove();
    if (!info.getTable().getNameAsString().startsWith("testLotsOfRegionRepli")) return;
    boolean fromFlushRpc = false;
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (frame.getClassName().equals(
            "org.apache.hadoop.hbase.regionserver.RSRpcServices")
          && frame.getMethodName().equals("flushRegion")) fromFlushRpc = true;
    }
    String key = raw(info.getRegionName()) + "~" + descriptor.getAction().name();
    int ordinal = markerAttempts.getOrDefault(key, 0) + 1;
    markerAttempts.put(key, ordinal);
    MarkerContext ctx = new MarkerContext(++sequence, info, descriptor, sync, fromFlushRpc,
                                          ordinal);
    marker.set(ctx);
    System.err.println("HBASE32U WAL_FLUSH_ATTEMPT seq=" + ctx.id
      + " raw_primary_region=" + ctx.region
      + " stable_region=" + ctx.stableRegion
      + " replica=" + info.getReplicaId() + " action=" + ctx.action
      + " sync=" + ctx.sync + " from_flush_rpc=" + ctx.fromFlushRpc
      + " marker_ordinal=" + ctx.ordinal);
  }

  private static boolean inFlushMarker() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (frame.getClassName().equals("org.apache.hadoop.hbase.regionserver.wal.WALUtil")
          && frame.getMethodName().equals("writeFlushMarker")) return true;
    }
    return false;
  }

  public static synchronized void walCall(String step) {
    MarkerContext ctx = marker.get();
    if (ctx == null || !inFlushMarker()) return;
    System.err.println("HBASE32U WAL_" + step + " seq=" + (++sequence)
      + " marker_seq=" + ctx.id + " raw_primary_region=" + ctx.region
      + " stable_region=" + ctx.stableRegion + " action=" + ctx.action
      + " sync=" + ctx.sync + " from_flush_rpc=" + ctx.fromFlushRpc
      + " marker_ordinal=" + ctx.ordinal);
  }

  private static final class Probes implements ClassFileTransformer {
    @Override
    public byte[] transform(ClassLoader loader, String className, Class<?> redefining,
                            ProtectionDomain domain, byte[] original) {
      if (!HANDLER.equals(className) && !META.equals(className)
          && !CONN.equals(className) && !SCANNER.equals(className)
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
                private int line;

                @Override
                public void visitCode() {
                  super.visitCode();
                  super.visitVarInsn(Opcodes.ALOAD, 1);
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32UpstreamAgent", "targetEnter",
                    "(Lorg/apache/hadoop/hbase/regionserver/HRegion;)V", false);
                }

                @Override
                public void visitLineNumber(int sourceLine, org.objectweb.asm.Label start) {
                  line = sourceLine;
                  super.visitLineNumber(sourceLine, start);
                  if (sourceLine == 130) {
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32UpstreamAgent",
                      "targetCatch", "()V", false);
                  }
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
            if (SCANNER.equals(className)) {
              return new MethodVisitor(Opcodes.ASM9, delegate) {
                @Override
                public void visitMethodInsn(int opcode, String owner, String invoked,
                                            String desc, boolean isInterface) {
                  if (invoked.equals("scan") && owner.contains("ClientService")
                      && desc.contains("ScanRequest")) {
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32UpstreamAgent",
                      "beforeMetaScanRpc", "()V", false);
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
                    super.visitVarInsn(Opcodes.ALOAD, 0);
                    super.visitVarInsn(Opcodes.ALOAD, 1);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32UpstreamAgent",
                      "beforeMasterReport",
                      "(Lorg/apache/hadoop/hbase/regionserver/HRegionServer;Lorg/apache/hadoop/hbase/regionserver/RegionServerServices$RegionStateTransitionContext;)V",
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
            if (WAL.equals(className) && method.equals("doFullMarkerAppendTransaction")) {
              return new MethodVisitor(Opcodes.ASM9, delegate) {
                @Override
                public void visitMethodInsn(int opcode, String owner, String invoked,
                                            String desc, boolean isInterface) {
                  String step = null;
                  if (owner.equals("org/apache/hadoop/hbase/wal/WAL")) {
                    if (invoked.equals("appendMarker")) step = "APPEND";
                    if (invoked.equals("sync")) step = "SYNC";
                  }
                  if (step != null) {
                    super.visitLdcInsn(step + "_START");
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32UpstreamAgent",
                      "walCall", "(Ljava/lang/String;)V", false);
                  }
                  super.visitMethodInsn(opcode, owner, invoked, desc, isInterface);
                  if (step != null) {
                    super.visitLdcInsn(step + "_COMPLETE");
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32UpstreamAgent",
                      "walCall", "(Ljava/lang/String;)V", false);
                  }
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
