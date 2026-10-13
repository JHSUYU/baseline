/*
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 */
package org.apache.hadoop.hbase.ipc;

import org.apache.hadoop.hbase.ipc.GraphCheckerHBaseDoors;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.Map;
import java.util.UUID;
import java.util.WeakHashMap;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import org.apache.yetus.audience.InterfaceAudience;

/**
 * Carries a causal envelope alongside each client SASL response. The bytes
 * passed to the SASL mechanism are unchanged after the server removes this
 * envelope. All identity comes from the caller scope and the actual frame;
 * no token contents, thread names, or timing are used for pairing.
 */
@InterfaceAudience.Private
public final class GraphCheckerHBaseSaslProtocol {
  private static final byte[] MAGIC = "MALLORY-GC-SASL1".getBytes(StandardCharsets.US_ASCII);
  private static final String TRANSPORT = "hbase-sasl";
  private static final int MAX_CONTEXT_BYTES = 1 << 20;
  private static final Map<Object, Connection> CONNECTIONS =
      Collections.synchronizedMap(new WeakHashMap<Object, Connection>());
  private static final Map<Object, Connection> HANDLERS =
      Collections.synchronizedMap(new WeakHashMap<Object, Connection>());
  private static final Map<String, AtomicInteger> CONNECTION_ORDINALS =
      new ConcurrentHashMap<>();

  private GraphCheckerHBaseSaslProtocol() { }

  /** Executed on the original call thread, before Netty changes threads. */
  public static void connectionCreated(Object connection, String serviceName) {
    String source = GraphCheckerHBaseDoors.currentSourceKey();
    if (source == null || source.isEmpty()) {
      GraphCheckerHBaseDoors.gap("SASL_SOURCE_MISSING", TRANSPORT,
          "connection created outside a registered caller scope");
      return;
    }
    String key = source + "|" + serviceName;
    int ordinal = CONNECTION_ORDINALS.computeIfAbsent(key,
        ignored -> new AtomicInteger()).incrementAndGet();
    if (ordinal > 1) {
      GraphCheckerHBaseDoors.gap("SASL_REPLAY_KEY_COLLISION", key,
          "multiple SASL connections share source and service identity");
      // A local connection ordinal can change with scheduling. Leave this
      // connection untraced until a protocol-carried stable ID is available.
      return;
    }
    String correlation = UUID.nameUUIDFromBytes(("hbase-sasl-v1|" + key + "|connection:"
        + ordinal).getBytes(StandardCharsets.UTF_8)).toString();
    CONNECTIONS.put(connection, new Connection(correlation, GraphCheckerHBaseDoors.captureScope()));
  }

  public static void bindHandler(Object handler, Object connection) {
    Connection state = CONNECTIONS.get(connection);
    if (state != null) HANDLERS.put(handler, state);
  }

  /** One envelope per actual client response, including challenge responses. */
  public static Frame prepareResponse(Object handler, byte[] saslToken) {
    Connection state = HANDLERS.get(handler);
    if (state == null) return new Frame(saslToken, null);
    int round = state.round.incrementAndGet();
    String attempt = Integer.toString(round);
    GraphCheckerHBaseDoors.Outbound outbound = GraphCheckerHBaseDoors.prepareOutbound(TRANSPORT,
        state.correlation, attempt, GraphCheckerHBaseDoors.REQUEST, null, state.scope);
    if (!outbound.active()) return new Frame(saslToken, null);
    try {
      byte[] context = context(state.correlation, attempt, outbound);
      ByteArrayOutputStream bytes = new ByteArrayOutputStream(
          MAGIC.length + 4 + context.length + saslToken.length);
      DataOutputStream out = new DataOutputStream(bytes);
      out.write(MAGIC);
      out.writeInt(context.length);
      out.write(context);
      out.write(saslToken);
      out.flush();
      return new Frame(bytes.toByteArray(), outbound);
    } catch (IOException impossible) {
      throw new IllegalStateException(impossible);
    }
  }

  /** Called on the server immediately around the original evaluateResponse. */
  public static Scope enterResponse(Object rpcServer, byte[] wireToken) throws IOException {
    if (!hasMagic(wireToken)) return new Scope(wireToken, null);
    if (wireToken.length < MAGIC.length + 4) throw new IOException("short SASL graph envelope");
    DataInputStream in = new DataInputStream(new ByteArrayInputStream(wireToken,
        MAGIC.length, wireToken.length - MAGIC.length));
    int length = in.readInt();
    if (length <= 0 || length > MAX_CONTEXT_BYTES || length > in.available()) {
      GraphCheckerHBaseDoors.gap("SASL_HEADER_INVALID", TRANSPORT, "invalid context length");
      throw new IOException("invalid SASL graph envelope length");
    }
    byte[] context = new byte[length];
    in.readFully(context);
    byte[] token = new byte[in.available()];
    in.readFully(token);
    DataInputStream fields = new DataInputStream(new ByteArrayInputStream(context));
    String correlation = field(fields);
    String attempt = field(fields);
    String trace = field(fields);
    String symbolic = field(fields);
    if (fields.available() != 0) throw new IOException("trailing SASL graph context");
    Object owner = serverOwner(rpcServer);
    GraphCheckerHBaseDoors.Inbound inbound = GraphCheckerHBaseDoors.inbound(trace, symbolic,
        TRANSPORT, correlation, attempt, GraphCheckerHBaseDoors.REQUEST, owner, false);
    return new Scope(token, inbound);
  }

  private static byte[] context(String correlation, String attempt,
                                GraphCheckerHBaseDoors.Outbound outbound) throws IOException {
    ByteArrayOutputStream bytes = new ByteArrayOutputStream();
    DataOutputStream out = new DataOutputStream(bytes);
    field(out, correlation);
    field(out, attempt);
    field(out, outbound.trace);
    field(out, outbound.symbolic);
    out.flush();
    if (bytes.size() > MAX_CONTEXT_BYTES) throw new IOException("SASL graph context too large");
    return bytes.toByteArray();
  }

  private static void field(DataOutputStream out, String value) throws IOException {
    byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
    if (bytes.length > MAX_CONTEXT_BYTES) throw new IOException("SASL field too large");
    out.writeInt(bytes.length);
    out.write(bytes);
  }

  private static String field(DataInputStream in) throws IOException {
    int length = in.readInt();
    if (length < 0 || length > MAX_CONTEXT_BYTES || length > in.available()) {
      throw new IOException("invalid SASL graph field");
    }
    byte[] bytes = new byte[length];
    in.readFully(bytes);
    return new String(bytes, StandardCharsets.UTF_8);
  }

  private static boolean hasMagic(byte[] token) {
    if (token.length < MAGIC.length) return false;
    for (int i = 0; i < MAGIC.length; i++) if (token[i] != MAGIC[i]) return false;
    return true;
  }

  private static Object serverOwner(Object rpcServer) {
    for (Class<?> type = rpcServer.getClass(); type != null; type = type.getSuperclass()) {
      try {
        Field field = type.getDeclaredField("server");
        field.setAccessible(true);
        return field.get(rpcServer);
      } catch (NoSuchFieldException absent) {
        // The concrete server inherits the actor field.
      } catch (ReflectiveOperationException | RuntimeException failure) {
        GraphCheckerHBaseDoors.gap("SASL_OWNER_UNAVAILABLE", TRANSPORT, failure.toString());
        return null;
      }
    }
    GraphCheckerHBaseDoors.gap("SASL_OWNER_UNAVAILABLE", TRANSPORT, "RpcServer.server absent");
    return null;
  }

  private static final class Connection {
    final String correlation;
    final Object scope;
    final AtomicInteger round = new AtomicInteger();
    Connection(String correlation, Object scope) {
      this.correlation = correlation;
      this.scope = scope;
    }
  }

  public static final class Frame {
    public final byte[] payload;
    private final GraphCheckerHBaseDoors.Outbound outbound;
    private Frame(byte[] payload, GraphCheckerHBaseDoors.Outbound outbound) {
      this.payload = payload;
      this.outbound = outbound;
    }
    public void sent() { GraphCheckerHBaseDoors.sent(outbound); }
    public void aborted() {
      GraphCheckerHBaseDoors.aborted(outbound, "SASL response write did not complete");
    }
  }

  public static final class Scope implements AutoCloseable {
    public final byte[] saslToken;
    private final GraphCheckerHBaseDoors.Inbound inbound;
    private Scope(byte[] saslToken, GraphCheckerHBaseDoors.Inbound inbound) {
      this.saslToken = saslToken;
      this.inbound = inbound;
    }
    @Override public void close() { GraphCheckerHBaseDoors.endInbound(inbound); }
  }
}
