import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.io.EOFException;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.ProtectionDomain;
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;
import org.apache.hadoop.hbase.DoNotRetryIOException;
import org.apache.hadoop.hbase.TableName;
import org.apache.hadoop.hbase.client.RegionInfo;
import org.apache.hadoop.hbase.client.RegionReplicaUtil;
import org.apache.hadoop.hbase.ipc.HBaseRpcController;
import org.apache.hadoop.hbase.ipc.RpcCall;
import org.apache.hadoop.hbase.ipc.RpcServer;
import org.apache.hadoop.hbase.regionserver.HRegion;
import org.apache.hadoop.hbase.regionserver.RegionServerServices.RegionStateTransitionContext;
import org.apache.hadoop.hbase.shaded.protobuf.generated.WALProtos.FlushDescriptor;
import org.apache.hbase.thirdparty.com.google.protobuf.ServiceException;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Passive, case-local probes for I/O that can influence the B7 check. */
public final class HBase32UpstreamAgent {
  private static final String HANDLER =
    "org/apache/hadoop/hbase/regionserver/handler/RegionReplicaFlushHandler";
  private static final String CALLABLE = "org/apache/hadoop/hbase/client/FlushRegionCallable";
  private static final String META = "org/apache/hadoop/hbase/MetaTableAccessor";
  private static final String CONN = "org/apache/hadoop/hbase/client/ConnectionImplementation";
  private static final String SCANNER = "org/apache/hadoop/hbase/client/ScannerCallable";
  private static final String CLIENT_GET =
    "org/apache/hadoop/hbase/client/ClientServiceCallable";
  private static final String RS = "org/apache/hadoop/hbase/regionserver/HRegionServer";
  private static final String RS_RPC = "org/apache/hadoop/hbase/regionserver/RSRpcServices";
  private static final String WAL = "org/apache/hadoop/hbase/regionserver/wal/WALUtil";
  private static final String TRACE_ATTRIBUTE = "hbase32.target";
  private static final Map<String, Integer> targetHits = new HashMap<>();
  private static final Map<String, Integer> reportAttempts = new HashMap<>();
  private static final Map<String, Integer> markerAttempts = new HashMap<>();
  private static final ThreadLocal<Context> current = new ThreadLocal<>();
  private static final ThreadLocal<MarkerContext> marker = new ThreadLocal<>();
  private static final ThreadLocal<String> serverFlushActor = new ThreadLocal<>();
  private static final String[] faultPlan =
    System.getProperty("hbase32.upstream.fault.plan", "").split(";");
  private static int nextFault;
  private static long sequence;

  private static final class Context {
    final String primary;
    final int replica;
    final int ordinal;
    int metaGets;
    int metaGetRpcs;
    int metaScans;
    int metaScanRpcs;
    int flushRpcs;
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
    final String actorTag;

    MarkerContext(long id, RegionInfo info, FlushDescriptor descriptor, boolean sync,
                  boolean fromFlushRpc, int ordinal, String actorTag) {
      this.id = id;
      this.region = raw(info.getRegionName());
      this.stableRegion = stable(info.getRegionName());
      this.action = descriptor.getAction().name();
      this.sync = sync;
      this.fromFlushRpc = fromFlushRpc;
      this.ordinal = ordinal;
      this.actorTag = actorTag;
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

  private static IOException faultException(String kind, String selector) {
    String message = "HBASE32U_INJECTED " + selector;
    if (kind.equals("DO_NOT_RETRY_IOEXCEPTION")) return new DoNotRetryIOException(message);
    if (kind.equals("EOF_EXCEPTION")) return new EOFException(message);
    if (kind.equals("SOCKET_TIMEOUT")) return new java.net.SocketTimeoutException(message);
    return new IOException(message);
  }

  private static boolean matchesNextFault(String selector) {
    if (nextFault >= faultPlan.length || faultPlan[nextFault].isEmpty()) return false;
    int last = faultPlan[nextFault].lastIndexOf('~');
    return last > 0 && faultPlan[nextFault].substring(0, last).equals(selector);
  }

  private static String applyFault(String selector, String detail) {
    int step = ++nextFault;
    String planned = faultPlan[step - 1];
    String kind = planned.substring(planned.lastIndexOf('~') + 1);
    System.err.println("HBASE32U FAULT_APPLIED seq=" + (++sequence)
      + " step=" + step + " selector=" + selector + " kind=" + kind + " " + detail);
    return kind;
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

  public static synchronized void markClientFlush(HBaseRpcController controller,
                                                   byte[] regionName) {
    Context ctx = current.get();
    if (ctx == null || !inTarget() || !ctx.primary.equals(raw(regionName))) return;
    int rpcOrdinal = ++ctx.flushRpcs;
    String tag = ctx.primary + "|" + ctx.replica + "|" + ctx.ordinal + "|" + rpcOrdinal;
    Map<String, byte[]> attributes = new HashMap<>(controller.getRequestAttributes());
    attributes.put(TRACE_ATTRIBUTE, tag.getBytes(StandardCharsets.UTF_8));
    controller.setRequestAttributes(attributes);
    System.err.println("HBASE32U CLIENT_FLUSH_TAG seq=" + (++sequence)
      + " raw_primary_region=" + ctx.primary + " replica=" + ctx.replica
      + " target_ordinal=" + ctx.ordinal + " rpc_ordinal=" + rpcOrdinal
      + " actor_tag=" + tag);
  }

  public static synchronized void serverFlushEnter() {
    serverFlushActor.remove();
    RpcCall call = RpcServer.getCurrentCall().orElse(null);
    if (call == null) return;
    byte[] encoded = call.getRequestAttribute(TRACE_ATTRIBUTE);
    if (encoded == null) return;
    String tag = new String(encoded, StandardCharsets.UTF_8);
    serverFlushActor.set(tag);
    System.err.println("HBASE32U SERVER_FLUSH_TAG seq=" + (++sequence)
      + " actor_tag=" + tag + " actor_thread="
      + Thread.currentThread().getName().replace(' ', '_'));
  }

  public static void serverFlushExit() {
    serverFlushActor.remove();
  }

  private static String phase(Context ctx) {
    return ctx.inCatch ? "after_rpc_exception" : "before_catch";
  }

  public static synchronized void beforeMetaStateGet(TableName table) {
    Context ctx = current.get();
    if (ctx == null || !inTarget()) return;
    int ordinal = ++ctx.metaGets;
    System.err.println("HBASE32U META_STATE_GET_ATTEMPT seq=" + (++sequence)
      + " table=" + table.getNameAsString() + " raw_primary_region=" + ctx.primary
      + " replica=" + ctx.replica + " target_ordinal=" + ctx.ordinal
      + " get_ordinal=" + ordinal + " phase=" + phase(ctx));
  }

  public static synchronized void beforeMetaStateRpc() {
    Context ctx = current.get();
    if (ctx == null || !inTarget()) return;
    boolean inTableStateGet = false;
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (frame.getClassName().equals("org.apache.hadoop.hbase.MetaTableAccessor")
          && frame.getMethodName().equals("getTableState")) inTableStateGet = true;
    }
    if (!inTableStateGet) return;
    int ordinal = ++ctx.metaGetRpcs;
    System.err.println("HBASE32U META_STATE_GET_RPC seq=" + (++sequence)
      + " raw_primary_region=" + ctx.primary + " replica=" + ctx.replica
      + " target_ordinal=" + ctx.ordinal + " rpc_ordinal=" + ordinal
      + " phase=" + phase(ctx));
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

  public static synchronized void beforeMetaScanRpc(TableName scannedTable, byte[] scanStart,
                                                     String operation) {
    Context ctx = current.get();
    if (!TableName.META_TABLE_NAME.equals(scannedTable)) return;
    boolean linkedTargetThread = ctx != null && inTarget();
    int ordinal = linkedTargetThread ? ++ctx.metaScanRpcs : 0;
    System.err.println("HBASE32U META_SCAN_RPC seq=" + (++sequence)
      + " scan_start=" + raw(scanStart)
      + " raw_primary_region=" + (linkedTargetThread ? ctx.primary : "unknown")
      + " replica=" + (linkedTargetThread ? ctx.replica : "unknown")
      + " target_ordinal=" + (linkedTargetThread ? ctx.ordinal : "unknown")
      + " rpc_ordinal=" + ordinal
      + " phase=" + (linkedTargetThread ? phase(ctx) : "unlinked_thread")
      + " operation=" + operation);
  }

  public static synchronized void beforeMasterReport(Object server,
                                                     RegionStateTransitionContext context)
    throws ServiceException {
    if (!context.getCode().name().equals("OPENED")) return;
    RegionInfo[] regions = context.getHris();
    long[] procIds = context.getProcIds();
    for (int i = 0; i < regions.length; i++) {
      RegionInfo info = regions[i];
      if (!info.getTable().getNameAsString().startsWith("testLotsOfRegionRepli")) continue;
      String primary = raw(RegionReplicaUtil.getRegionInfoForDefaultReplica(info).getRegionName());
      String secondary = raw(info.getRegionName());
      String serverName;
      try {
        serverName = String.valueOf(server.getClass().getMethod("getServerName").invoke(server));
      } catch (ReflectiveOperationException error) {
        serverName = "unknown";
      }
      String key = serverName + "~" + secondary;
      int attempt = reportAttempts.getOrDefault(key, 0) + 1;
      reportAttempts.put(key, attempt);
      System.err.println("HBASE32U MASTER_OPENED_RPC seq=" + (++sequence)
        + " raw_primary_region=" + primary
        + " raw_secondary_region=" + secondary
        + " stable_region=" + stable(info.getRegionName())
        + " replica=" + info.getReplicaId()
        + " server=" + serverName + " proc_id=" + procIds[i]
        + " attempt=" + attempt);
      String selector = "MASTER_OPENED_RPC~" + stable(info.getRegionName())
        + "~replica-" + info.getReplicaId() + "~attempt-" + attempt;
      if (matchesNextFault(selector)) {
        String kind = applyFault(selector, "raw_primary_region=" + primary
          + " raw_secondary_region=" + secondary + " server=" + serverName
          + " proc_id=" + procIds[i]);
        throw new ServiceException(faultException(kind, selector));
      }
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
    String tag = fromFlushRpc ? serverFlushActor.get() : null;
    // An ordinal shared by all replicas of one primary changes with RPC
    // scheduling. Count inside the exact secondary actor instead.
    String logicalActor = tag == null || tag.lastIndexOf('|') < 0
      ? raw(info.getRegionName()) : tag.substring(0, tag.lastIndexOf('|'));
    String key = logicalActor
      + "~" + descriptor.getAction().name();
    int ordinal = markerAttempts.getOrDefault(key, 0) + 1;
    markerAttempts.put(key, ordinal);
    MarkerContext ctx = new MarkerContext(++sequence, info, descriptor, sync, fromFlushRpc,
                                          ordinal, tag == null ? "unknown" : tag);
    marker.set(ctx);
    System.err.println("HBASE32U WAL_FLUSH_ATTEMPT seq=" + ctx.id
      + " raw_primary_region=" + ctx.region
      + " stable_region=" + ctx.stableRegion
      + " replica=" + info.getReplicaId() + " action=" + ctx.action
      + " sync=" + ctx.sync + " from_flush_rpc=" + ctx.fromFlushRpc
      + " marker_ordinal=" + ctx.ordinal
      + " actor_tag=" + ctx.actorTag
      + " actor_thread=" + Thread.currentThread().getName().replace(' ', '_'));
  }

  private static boolean inFlushMarker() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (frame.getClassName().equals("org.apache.hadoop.hbase.regionserver.wal.WALUtil")
          && frame.getMethodName().equals("writeFlushMarker")) return true;
    }
    return false;
  }

  public static synchronized void walCall(String step) throws IOException {
    MarkerContext ctx = marker.get();
    if (ctx == null || !inFlushMarker()) return;
    System.err.println("HBASE32U WAL_" + step + " seq=" + (++sequence)
      + " marker_seq=" + ctx.id + " raw_primary_region=" + ctx.region
      + " stable_region=" + ctx.stableRegion + " action=" + ctx.action
      + " sync=" + ctx.sync + " from_flush_rpc=" + ctx.fromFlushRpc
      + " marker_ordinal=" + ctx.ordinal
      + " actor_tag=" + ctx.actorTag
      + " actor_thread=" + Thread.currentThread().getName().replace(' ', '_'));
    if (!step.endsWith("_START") || !ctx.fromFlushRpc
        || !ctx.action.equals("CANNOT_FLUSH") || ctx.actorTag.equals("unknown")) return;
    String[] actor = ctx.actorTag.split("\\|");
    if (actor.length != 4 || !actor[0].equals(ctx.region)) return;
    String selector = "WAL_" + step + "~" + ctx.stableRegion
      + "~replica-" + actor[1] + "~target-" + actor[2]
      + "~marker-" + ctx.ordinal;
    if (matchesNextFault(selector)) {
      String kind = applyFault(selector, "raw_primary_region=" + ctx.region
        + " actor_tag=" + ctx.actorTag + " action=" + ctx.action
        + " sync=" + ctx.sync + " marker_seq=" + ctx.id);
      throw faultException(kind, selector);
    }
  }

  private static final class Probes implements ClassFileTransformer {
    @Override
    public byte[] transform(ClassLoader loader, String className, Class<?> redefining,
                            ProtectionDomain domain, byte[] original) {
      if (!HANDLER.equals(className) && !CALLABLE.equals(className)
          && !META.equals(className)
          && !CONN.equals(className) && !SCANNER.equals(className)
          && !CLIENT_GET.equals(className)
          && !RS.equals(className) && !RS_RPC.equals(className)
          && !WAL.equals(className)) return null;
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
            if (CALLABLE.equals(className) && method.equals("call")) {
              return new MethodVisitor(Opcodes.ASM9, delegate) {
                @Override
                public void visitMethodInsn(int opcode, String owner, String invoked,
                                            String desc, boolean isInterface) {
                  if (invoked.equals("flushRegion") && desc.contains("FlushRegionRequest")) {
                    super.visitVarInsn(Opcodes.ALOAD, 1);
                    super.visitVarInsn(Opcodes.ALOAD, 0);
                    super.visitFieldInsn(Opcodes.GETFIELD, CALLABLE, "regionName", "[B");
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32UpstreamAgent",
                      "markClientFlush", "(Lorg/apache/hadoop/hbase/ipc/HBaseRpcController;[B)V",
                      false);
                  }
                  super.visitMethodInsn(opcode, owner, invoked, desc, isInterface);
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
                    String operation = method.equals("openScanner") ? "OPEN"
                      : method.equals("next") ? "NEXT"
                      : method.equals("close") ? "CLOSE" : "UNKNOWN";
                    super.visitVarInsn(Opcodes.ALOAD, 0);
                    super.visitMethodInsn(Opcodes.INVOKEVIRTUAL, SCANNER, "getTableName",
                      "()Lorg/apache/hadoop/hbase/TableName;", false);
                    super.visitVarInsn(Opcodes.ALOAD, 0);
                    super.visitMethodInsn(Opcodes.INVOKEVIRTUAL, SCANNER, "getScan",
                      "()Lorg/apache/hadoop/hbase/client/Scan;", false);
                    super.visitMethodInsn(Opcodes.INVOKEVIRTUAL,
                      "org/apache/hadoop/hbase/client/Scan", "getStartRow", "()[B", false);
                    super.visitLdcInsn(operation);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32UpstreamAgent",
                      "beforeMetaScanRpc", "(Lorg/apache/hadoop/hbase/TableName;[BLjava/lang/String;)V",
                      false);
                  }
                  super.visitMethodInsn(opcode, owner, invoked, desc, isInterface);
                }
              };
            }
            if (CLIENT_GET.equals(className) && method.equals("doGet")) {
              return new MethodVisitor(Opcodes.ASM9, delegate) {
                @Override
                public void visitMethodInsn(int opcode, String owner, String invoked,
                                            String desc, boolean isInterface) {
                  if (invoked.equals("get") && owner.contains("ClientService")
                      && desc.contains("GetRequest")) {
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32UpstreamAgent",
                      "beforeMetaStateRpc", "()V", false);
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
                      "(Ljava/lang/Object;Lorg/apache/hadoop/hbase/regionserver/RegionServerServices$RegionStateTransitionContext;)V",
                      false);
                  }
                  super.visitMethodInsn(opcode, owner, invoked, desc, isInterface);
                }
              };
            }
            if (RS_RPC.equals(className) && method.equals("flushRegion")) {
              return new MethodVisitor(Opcodes.ASM9, delegate) {
                @Override
                public void visitCode() {
                  super.visitCode();
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32UpstreamAgent",
                    "serverFlushEnter", "()V", false);
                }

                @Override
                public void visitInsn(int opcode) {
                  if (opcode == Opcodes.ARETURN || opcode == Opcodes.ATHROW) {
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, "HBase32UpstreamAgent",
                      "serverFlushExit", "()V", false);
                  }
                  super.visitInsn(opcode);
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
