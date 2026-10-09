package research.zkactor.zk03;

import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.List;
import research.zkactor.Probe;

/** Isolated after-I/O experiment: never fault a partial client request. */
public final class AfterBridge {
  private static final class Response {
    final Object handler;
    final long raw;
    final boolean valid;
    final String writeSite;
    Response(Object handler, long raw, boolean valid, String writeSite) {
      this.handler = handler;
      this.raw = raw;
      this.valid = valid;
      this.writeSite = writeSite;
    }
  }

  private static final ThreadLocal<List<Response>> PENDING =
      ThreadLocal.withInitial(ArrayList::new);

  private AfterBridge() {}

  private static Object field(Object receiver, String name) throws Exception {
    for (Class<?> type = receiver.getClass(); type != null; type = type.getSuperclass()) {
      try {
        Field member = type.getDeclaredField(name);
        member.setAccessible(true);
        return member.get(receiver);
      } catch (NoSuchFieldException ignored) { }
    }
    throw new NoSuchFieldException(receiver.getClass().getName() + "." + name);
  }

  public static void clientWriteAfter(int written, Object socket, Object client,
      Object packet, String site) throws IOException {
    try {
      ByteBuffer buffer = (ByteBuffer) field(packet, "bb");
      Object header = field(packet, "requestHeader");
      int remaining = buffer.remaining();
      int opcode = -1;
      if (header != null) {
        Method getType = header.getClass().getMethod("getType");
        opcode = ((Number) getType.invoke(header)).intValue();
      }
      Probe.diagnostic("AFTER_WRITE_RESULT", site, Integer.toString(written),
          Integer.toString(remaining), Integer.toString(opcode));
      // ZooKeeper's setData=5 and sync=9 are the two actual requests in
      // QuorumTest.testSessionMoved. Connect, heartbeat and auth are excluded.
      if (written > 0 && remaining == 0 && (opcode == 5 || opcode == 9)) {
        Bridge.clientIo(socket, client, site, "write");
      }
    } catch (IOException fault) {
      throw fault;
    } catch (Throwable failure) {
      Probe.diagnostic("AFTER_WRITE_UNBOUND", site, failure.getClass().getName(),
          String.valueOf(failure.getMessage()));
    }
  }

  public static void serverResponseAfter(Object connection, String site) throws IOException {
    Probe.diagnostic("AFTER_RESPONSE_SENT", site, "packetSent-after-complete-write");
    Bridge.serverIo(connection, site, "write");
  }

  /** Record only a serialized REVALIDATE response, before the buffered stream flush. */
  public static void quorumPacketWritten(Object handler, Object packet, String site) {
    try {
      int type = ((Number) packet.getClass().getMethod("getType").invoke(packet)).intValue();
      if (type != 6) return; // Leader.REVALIDATE in the pinned ZooKeeper source.
      byte[] data = (byte[]) packet.getClass().getMethod("getData").invoke(packet);
      if (data == null || data.length != 9) {
        Probe.diagnostic("QUORUM_RESPONSE_UNBOUND", site, "bad-revalidate-data-length",
            data == null ? "null" : Integer.toString(data.length));
        return;
      }
      ByteBuffer bytes = ByteBuffer.wrap(data);
      long raw = bytes.getLong();
      boolean valid = bytes.get() != 0;
      PENDING.get().add(new Response(handler, raw, valid, site));
      Probe.diagnostic("QUORUM_REVALIDATE_WRITTEN", site, Long.toString(raw),
          Boolean.toString(valid));
    } catch (Throwable failure) {
      Probe.diagnostic("QUORUM_RESPONSE_UNBOUND", site, failure.getClass().getName(),
          String.valueOf(failure.getMessage()));
    }
  }

  /** An IOException here occurs only after the complete buffered response flushed. */
  public static void quorumAfterFlush(Object handler, String site) throws IOException {
    List<Response> pending = PENDING.get();
    if (pending.isEmpty()) return;
    List<Response> flushed = new ArrayList<>(pending);
    pending.clear();
    for (Response response : flushed) {
      if (response.handler != handler) {
        Probe.diagnostic("QUORUM_RESPONSE_UNBOUND", site, "handler-changed");
        continue;
      }
      Probe.diagnostic("QUORUM_FLUSH_COMPLETE", response.writeSite, site,
          Long.toString(response.raw), Boolean.toString(response.valid));
      Bridge.quorumResponseAfter(handler, response.raw, response.valid, site);
    }
  }
}
