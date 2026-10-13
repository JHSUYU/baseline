package org.apache.hadoop.hbase.ipc;

import edu.uva.liftlab.graphchecker.contract.GapClass;
import edu.uva.liftlab.graphchecker.contract.GapKind;
import edu.uva.liftlab.graphchecker.runtime.MessageDoors;
import edu.uva.liftlab.graphchecker.runtime.RowRuntime;
import edu.uva.liftlab.graphchecker.runtime.HBaseRuntimeSource;
import java.util.Locale;
import org.apache.yetus.audience.InterfaceAudience;

/** HBase protocol boundary backed only by the original GraphChecker runtime. */
@InterfaceAudience.Private
public final class GraphCheckerHBaseDoors {
  public static final String REQUEST = MessageDoors.REQUEST;
  public static final String RESPONSE = MessageDoors.RESPONSE;

  private GraphCheckerHBaseDoors() { }

  public static Object captureScope() { return MessageDoors.captureScope(); }
  public static String currentSourceKey() { return HBaseRuntimeSource.currentSourceKey(); }
  public static void registerCurrentSourceAlias(Object alias) {
    HBaseRuntimeSource.registerCurrentSourceAlias(alias);
  }
  public static void registerNode(Object anchor, String kind, String role, String id) {
    MessageDoors.registerNode(anchor, kind, role, id);
  }
  public static long beginTick(Object owner, String role) {
    return MessageDoors.beginTick(owner, role);
  }
  public static void endTick(long token) { MessageDoors.endTick(token); }
  public static long enterCarriedScope(Object scope, String role, String api) {
    return MessageDoors.enterCarriedScope(scope, role, api);
  }
  public static void exitCarriedScope(long token) {
    MessageDoors.exitCarriedScope(token);
  }

  /** Original GraphChecker mints the export when the wire header is made. */
  public static Outbound prepareOutbound(String transport, String correlation,
      String attempt, String half, Object owner, Object scope) {
    if (REQUEST.equals(half)) {
      // The correlation and attempt are copied into the actual wire envelope.
      // Include them in the original engine's request site so distinct async
      // HBase messages cannot mint one producer endpoint from a reused tick.
      return new Outbound(MessageDoors.outboundRequest(wireTransport(transport),
          correlation, attempt, owner, scope, correlation + "-" + attempt));
    }
    return new Outbound(MessageDoors.outbound(wireTransport(transport), correlation, attempt,
        half, owner, scope));
  }
  /** The original engine has already recorded SEND at outbound(). */
  public static void sent(Outbound outbound) { }
  public static void aborted(Outbound outbound, String reason) {
    if (outbound != null && outbound.active()) {
      gap("HBASE_SEND_ABORTED", "hbase-wire", reason);
    }
  }
  public static Inbound inbound(String trace, String symbolic,
      String transport, String correlation, String attempt, String half,
      Object owner, boolean keepSymbolic) {
    return new Inbound(MessageDoors.inbound(trace, symbolic, wireTransport(transport),
        correlation, attempt, half, owner, keepSymbolic));
  }
  public static void endInbound(Inbound inbound) {
    if (inbound != null) MessageDoors.endInbound(inbound.delegate);
  }
  public static void stored(String transport, String key, Object owner) {
    MessageDoors.stored(wireTransport(transport), key, owner);
  }
  public static void fetched(String transport, String key, Object owner) {
    MessageDoors.fetched(wireTransport(transport), key, owner);
  }
  private static String wireTransport(String transport) {
    return transport == null ? "" : transport.toUpperCase(Locale.ROOT);
  }
  public static void gap(String reason, String subject, String detail) {
    boolean missingState = reason.startsWith("HBASE_META_STATE_");
    boolean ambiguousReplay = "RPC_REPLAY_KEY_COLLISION".equals(reason)
        || "SASL_REPLAY_KEY_COLLISION".equals(reason);
    GapKind kind = missingState ? GapKind.UNSTATED_VALUE
        : reason.contains("SOURCE") || reason.contains("OWNER")
        ? GapKind.LINEAGE_LOST : GapKind.MESSAGE_CONTEXT_REFUSED;
    RowRuntime.gap(kind, missingState || ambiguousReplay
        ? GapClass.BLOCKING : GapClass.DIAGNOSTIC,
        subject, reason + ": " + detail);
  }

  public static final class Outbound {
    private final MessageDoors.Outbound delegate;
    public final String trace;
    public final String symbolic;
    private Outbound(MessageDoors.Outbound delegate) {
      this.delegate = delegate;
      this.trace = delegate.trace;
      this.symbolic = delegate.symbolic;
    }
    public boolean active() { return delegate.active(); }
  }
  public static final class Inbound {
    private final MessageDoors.Inbound delegate;
    private Inbound(MessageDoors.Inbound delegate) { this.delegate = delegate; }
  }
}
