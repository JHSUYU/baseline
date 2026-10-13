package org.apache.hadoop.ipc;

import edu.uva.liftlab.graphchecker.contract.GapClass;
import edu.uva.liftlab.graphchecker.contract.GapKind;
import edu.uva.liftlab.graphchecker.runtime.HdfsRuntimeSource;
import edu.uva.liftlab.graphchecker.runtime.MessageDoors;
import edu.uva.liftlab.graphchecker.runtime.RowRuntime;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.util.concurrent.atomic.AtomicBoolean;

/** HDFS transport hooks backed by the original GraphChecker session. */
public final class NativeHdfsDoors {
  public static final String REQUEST = MessageDoors.REQUEST;
  public static final String RESPONSE = MessageDoors.RESPONSE;
  private static final Method PAYLOAD_OUTBOUND = payloadOutbound();

  private NativeHdfsDoors() { }

  public static Object captureScope() { return MessageDoors.captureScope(); }
  public static String currentSourceKey() {
    return HdfsRuntimeSource.currentSourceKey();
  }
  public static void registerCurrentSourceAlias(Object alias) {
    HdfsRuntimeSource.registerCurrentSourceAlias(alias);
  }
  public static void registerSource(Object anchor, String kind, String role,
                                    String id, long epoch) {
    MessageDoors.registerSource(anchor, kind, role, id, epoch);
    HdfsRuntimeSource.registerAnchor(anchor);
  }
  public static void restartSource(Object anchor, String kind, String role,
                                   String id, long epoch) {
    MessageDoors.restartSource(anchor, kind, role, id, epoch);
    HdfsRuntimeSource.registerAnchor(anchor);
  }
  public static void registerSourceAlias(Object alias, Object anchor) {
    MessageDoors.registerSourceAlias(alias, anchor);
  }
  public static long beginTick(Object owner, String role) {
    return MessageDoors.beginTick(owner, role);
  }
  public static void endTick(long tick) { MessageDoors.endTick(tick); }
  public static long enterCarriedScope(Object scope, String role, String api) {
    return MessageDoors.enterCarriedScope(scope, role, api);
  }
  public static void exitCarriedScope(long token) {
    MessageDoors.exitCarriedScope(token);
  }
  public static long beginRequest(Object owner, String api) {
    return MessageDoors.beginRequest(owner, api);
  }
  public static void endRequest(long token, String api) {
    MessageDoors.endRequest(token, api);
  }

  /** Record SEND only when Hadoop reports a successful socket handoff. */
  public static Outbound prepareOutbound(String transport, String correlation,
      String attempt, String half, Object owner, Object scope) {
    Object payload = owner instanceof Client.Call
        ? ((Client.Call) owner).rpcRequest : null;
    return new Outbound(transport, correlation, attempt, half, owner, scope,
        payload);
  }

  public static Outbound prepareOutbound(String transport, String correlation,
      String attempt, String half, Object owner, Object scope, Object payload) {
    return new Outbound(transport, correlation, attempt, half, owner, scope,
        payload);
  }

  public static void sent(Outbound outbound) {
    if (outbound == null) return;
    if (!outbound.sent.compareAndSet(false, true)) {
      gap("DUPLICATE_IPC_SEND", outbound.correlationId,
          "same prepared request/response sent twice");
      return;
    }
    Object payload = unwrapPayload(outbound.transport, outbound.payload);
    MessageDoors.Outbound emitted;
    if (PAYLOAD_OUTBOUND == null) {
      if (payload != null) {
        RowRuntime.gap(GapKind.UNSTATED_VALUE, GapClass.BLOCKING,
            outbound.correlationId,
            "original MessageDoors pin lacks payload outbound API");
      }
      emitted = MessageDoors.outbound(outbound.transport,
          outbound.correlationId, outbound.attemptId, outbound.half,
          outbound.owner, outbound.scope);
    } else {
      try {
        emitted = (MessageDoors.Outbound) PAYLOAD_OUTBOUND.invoke(null,
            outbound.transport, outbound.correlationId, outbound.attemptId,
            outbound.half, outbound.owner, outbound.scope, payload);
      } catch (IllegalAccessException | InvocationTargetException failure) {
        throw new IllegalStateException("original payload outbound failed", failure);
      }
    }
    outbound.trace = emitted.trace;
    outbound.symbolic = emitted.symbolic;
  }

  public static Inbound inbound(String trace, String symbolic,
      String transport, String correlation, String attempt, String half,
      Object owner, boolean keepSymbolic) {
    return new Inbound(MessageDoors.inbound(trace, symbolic, transport,
        correlation, attempt, half, owner, keepSymbolic));
  }
  public static void endInbound(Inbound inbound) {
    if (inbound != null) MessageDoors.endInbound(inbound.delegate);
  }

  public static void gap(String reason, String subject, String detail) {
    GapKind kind = reason.contains("SOURCE") || reason.contains("SCOPE")
        || reason.contains("PARENT") ? GapKind.LINEAGE_LOST
        : GapKind.MESSAGE_CONTEXT_REFUSED;
    RowRuntime.gap(kind, GapClass.BLOCKING, subject,
        reason + ": " + detail);
  }

  private static Method payloadOutbound() {
    try {
      return MessageDoors.class.getMethod("outbound", String.class,
          String.class, String.class, String.class, Object.class,
          Object.class, Object.class);
    } catch (NoSuchMethodException olderPin) {
      return null;
    }
  }

  private static Object unwrapPayload(String transport, Object payload) {
    if (payload == null) return null;
    try {
      if ("RpcProtobufRequest".equals(payload.getClass().getSimpleName())) {
        Field field = payload.getClass().getDeclaredField("payload");
        field.setAccessible(true);
        return field.get(payload);
      }
      if ("ProtobufWrapper".equals(payload.getClass().getSimpleName())) {
        Method getter = payload.getClass().getDeclaredMethod("getMessage");
        getter.setAccessible(true);
        return getter.invoke(payload);
      }
      return payload;
    } catch (ReflectiveOperationException | RuntimeException unreadable) {
      RowRuntime.gap(GapKind.UNSTATED_VALUE, GapClass.BLOCKING,
          transport, "HDFS RPC payload unread: "
              + payload.getClass().getName() + ": " + unreadable);
      return null;
    }
  }

  /** Pending transport leg. A false active result never means SEND occurred. */
  public static final class Outbound {
    public final String correlationId;
    public final String attemptId;
    private final String transport;
    private final String half;
    private final Object owner;
    private final Object scope;
    private final Object payload;
    private final AtomicBoolean sent = new AtomicBoolean();
    public volatile String trace = "";
    public volatile String symbolic = "";

    private Outbound(String transport, String correlation, String attempt,
        String half, Object owner, Object scope, Object payload) {
      this.transport = transport;
      this.correlationId = correlation;
      this.attemptId = attempt;
      this.half = half;
      this.owner = owner;
      this.scope = scope;
      this.payload = payload;
    }
    public boolean active() { return !trace.isEmpty() || !symbolic.isEmpty(); }
  }

  public static final class Inbound {
    private final MessageDoors.Inbound delegate;
    private Inbound(MessageDoors.Inbound delegate) { this.delegate = delegate; }
  }
}
