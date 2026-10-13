/*
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
package org.apache.hadoop.hbase.ipc;

import edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.Map;
import java.util.UUID;
import java.util.WeakHashMap;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import org.apache.yetus.audience.InterfaceAudience;

/**
 * Small HBase 2.6.6 transport shim. This class is copied into hbase-client by
 * apply.py; hbase-server already depends on hbase-client.
 *
 * The header is prepared before serialization. MessageDoors.sent is called
 * only after the transport reports a successful write. An absent or malformed
 * header deliberately yields no causal edge.
 */
@InterfaceAudience.Private
public final class GraphCheckerHBaseProtocol {
  public static final String REQUEST_ATTRIBUTE = "mallory.graphchecker.context.v1";
  private static final String TRANSPORT = "hbase-rpc";
  private static final String ATTEMPT = "1";
  private static final int MAGIC = 0x4d474331; // MGC1
  private static final int MAX_FIELD_BYTES = 1 << 20;

  private static final Map<Object, Pending> REQUESTS =
      Collections.synchronizedMap(new WeakHashMap<Object, Pending>());
  private static final Map<Object, Pending> RESPONSES =
      Collections.synchronizedMap(new WeakHashMap<Object, Pending>());
  private static final Map<Object, Envelope> SERVER_REQUESTS =
      Collections.synchronizedMap(new WeakHashMap<Object, Envelope>());
  private static final Map<String, AtomicInteger> REPLAY_KEYS = new ConcurrentHashMap<>();

  private GraphCheckerHBaseProtocol() { }

  /** Capture the caller's request before Netty or blocking I/O changes thread. */
  public static void clientCallCreated(Object call) {
    if (!(call instanceof Call)) return;
    MessageDoors.registerCurrentSourceAlias(call);
    Call rpc = (Call) call;
    String source = MessageDoors.currentSourceKey();
    if (source == null || source.isEmpty() || rpc.id < 0 || rpc.md == null) {
      MessageDoors.gap("RPC_REPLAY_KEY_MISSING", "hbase-rpc",
          "source, call id, or method unavailable at Call creation");
      return;
    }
    String replayKey = source + "|" + rpc.md.getFullName() + "|call:" + rpc.id
        + "|attempt:" + ATTEMPT;
    int collision = REPLAY_KEYS.computeIfAbsent(replayKey,
        ignored -> new AtomicInteger()).incrementAndGet();
    if (collision > 1) {
      MessageDoors.gap("RPC_REPLAY_KEY_COLLISION", replayKey,
          "multiple HBase RpcClient instances used the same call id");
    }
    String correlation = UUID.nameUUIDFromBytes(
        (replayKey + "|collision:" + collision).getBytes(StandardCharsets.UTF_8)).toString();
    REQUESTS.put(call, new Pending(correlation, MessageDoors.captureScope()));
  }

  /** Called while RequestHeader is built; the byte array travels on the RPC. */
  public static byte[] prepareRequest(Object call) {
    Pending pending = REQUESTS.get(call);
    if (pending == null) return new byte[0];
    synchronized (pending) {
      if (pending.outbound == null) {
        pending.outbound = MessageDoors.prepareOutbound(TRANSPORT,
            pending.correlation, ATTEMPT, MessageDoors.REQUEST, null,
            pending.scope);
      }
      return encode(pending.correlation, pending.outbound);
    }
  }

  /** Netty future success or blocking IPCUtil.write's completed flush. */
  public static void requestSent(Object call) {
    Pending pending = REQUESTS.get(call);
    if (pending != null) pending.sent();
  }

  /** Enter the actual server handler with context from the transported header. */
  public static RequestScope enterRequest(Object rpcServer, Object rpcCall) {
    byte[] bytes = null;
    try {
      java.lang.reflect.Method attribute = rpcCall.getClass()
          .getMethod("getRequestAttribute", String.class);
      attribute.setAccessible(true);
      bytes = (byte[]) attribute.invoke(rpcCall, REQUEST_ATTRIBUTE);
    } catch (ReflectiveOperationException | RuntimeException failure) {
      MessageDoors.gap("RPC_ATTRIBUTE_UNAVAILABLE", REQUEST_ATTRIBUTE,
          failure.toString());
      return RequestScope.EMPTY;
    }
    Envelope envelope = decode(bytes);
    if (envelope == null) return RequestScope.EMPTY;
    Object owner = null;
    try {
      for (Class<?> type = rpcServer.getClass(); type != null;
          type = type.getSuperclass()) {
        try {
          java.lang.reflect.Field field = type.getDeclaredField("server");
          field.setAccessible(true);
          owner = field.get(rpcServer);
          break;
        } catch (NoSuchFieldException absent) {
          // The concrete RpcServer subclass inherits this field.
        }
      }
    } catch (ReflectiveOperationException | RuntimeException ignored) {
      // The inbound exchange remains unattributed; the graph records a gap.
    }
    MessageDoors.Inbound inbound = MessageDoors.inbound(envelope.trace,
        envelope.symbolic, TRANSPORT, envelope.correlation, ATTEMPT,
        MessageDoors.REQUEST, owner, false);
    SERVER_REQUESTS.put(rpcCall, envelope);
    return new RequestScope(inbound);
  }

  /** ResponseHeader extension, prepared while still inside the request scope. */
  public static byte[] prepareResponse(Object rpcCall) {
    Envelope request = SERVER_REQUESTS.get(rpcCall);
    if (request == null) return new byte[0];
    Pending pending = RESPONSES.get(rpcCall);
    if (pending == null) {
      pending = new Pending(request.correlation, MessageDoors.captureScope());
      RESPONSES.put(rpcCall, pending);
    }
    synchronized (pending) {
      if (pending.outbound == null) {
        pending.outbound = MessageDoors.prepareOutbound(TRANSPORT,
            pending.correlation, ATTEMPT, MessageDoors.RESPONSE, null,
            pending.scope);
      }
      return encode(pending.correlation, pending.outbound);
    }
  }

  /** Called only after the complete response was written successfully. */
  public static void responseSent(Object rpcResponse) {
    Pending pending = RESPONSES.remove(rpcResponse);
    if (pending != null) pending.sent();
    SERVER_REQUESTS.remove(rpcResponse);
  }

  public static void responseWriteFailed(Object rpcResponse) {
    RESPONSES.remove(rpcResponse);
    SERVER_REQUESTS.remove(rpcResponse);
  }

  /** Scope remains active while RpcConnection dispatches the decoded response. */
  public static ResponseScope enterResponse(byte[] bytes, Object call) {
    Envelope envelope = decode(bytes);
    Pending request = REQUESTS.remove(call);
    if (envelope == null || request == null
        || !request.correlation.equals(envelope.correlation)) {
      return ResponseScope.EMPTY;
    }
    MessageDoors.Inbound inbound = MessageDoors.inbound(envelope.trace,
        envelope.symbolic, TRANSPORT, envelope.correlation, ATTEMPT,
        MessageDoors.RESPONSE, call, false);
    return new ResponseScope(inbound);
  }

  public static void registerMiniClusterNode(Object server, String role, int index) {
    if (server == null || index < 0) return;
    String id = "MASTER".equals(role) ? "master" + index : "rs" + index;
    MessageDoors.registerNode(server, "HBASE", role, id);
  }

  /** The MiniCluster's dedicated actor thread is a real root for background work. */
  public static long enterMiniClusterActor(Object server, String role) {
    return MessageDoors.beginTick(server, role);
  }

  public static void exitMiniClusterActor(long token) {
    MessageDoors.endTick(token);
  }

  private static byte[] encode(String correlation, MessageDoors.Outbound outbound) {
    if (outbound == null || !outbound.active()) return new byte[0];
    try {
      ByteArrayOutputStream bytes = new ByteArrayOutputStream();
      DataOutputStream out = new DataOutputStream(bytes);
      out.writeInt(MAGIC);
      field(out, correlation);
      field(out, outbound.trace);
      field(out, outbound.symbolic);
      out.flush();
      return bytes.toByteArray();
    } catch (IOException impossible) {
      throw new IllegalStateException(impossible);
    }
  }

  private static void field(DataOutputStream out, String value) throws IOException {
    byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
    if (bytes.length > MAX_FIELD_BYTES) throw new IOException("trace field too large");
    out.writeInt(bytes.length);
    out.write(bytes);
  }

  private static Envelope decode(byte[] bytes) {
    if (bytes == null || bytes.length == 0) return null;
    try {
      DataInputStream in = new DataInputStream(new ByteArrayInputStream(bytes));
      if (in.readInt() != MAGIC) return null;
      String correlation = field(in);
      String trace = field(in);
      String symbolic = field(in);
      if (in.available() != 0 || correlation.isEmpty()) return null;
      return new Envelope(correlation, trace, symbolic);
    } catch (IOException | RuntimeException malformed) {
      return null;
    }
  }

  private static String field(DataInputStream in) throws IOException {
    int length = in.readInt();
    if (length < 0 || length > MAX_FIELD_BYTES || length > in.available()) {
      throw new IOException("invalid trace field length");
    }
    byte[] bytes = new byte[length];
    in.readFully(bytes);
    return new String(bytes, StandardCharsets.UTF_8);
  }

  private static final class Pending {
    final String correlation;
    final Object scope;
    MessageDoors.Outbound outbound;
    boolean committed;
    Pending(String correlation, Object scope) {
      this.correlation = correlation;
      this.scope = scope;
    }
    synchronized void sent() {
      if (!committed && outbound != null) {
        MessageDoors.sent(outbound);
        committed = true;
      }
    }
  }

  private static final class Envelope {
    final String correlation;
    final String trace;
    final String symbolic;
    Envelope(String correlation, String trace, String symbolic) {
      this.correlation = correlation;
      this.trace = trace;
      this.symbolic = symbolic;
    }
  }

  public static final class RequestScope implements AutoCloseable {
    static final RequestScope EMPTY = new RequestScope(null);
    private final MessageDoors.Inbound inbound;
    RequestScope(MessageDoors.Inbound inbound) { this.inbound = inbound; }
    @Override public void close() { MessageDoors.endInbound(inbound); }
  }

  public static final class ResponseScope implements AutoCloseable {
    static final ResponseScope EMPTY = new ResponseScope(null);
    private final MessageDoors.Inbound inbound;
    ResponseScope(MessageDoors.Inbound inbound) { this.inbound = inbound; }
    @Override public void close() { MessageDoors.endInbound(inbound); }
  }
}
