package research.zkactor.zk02;

import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.ByteBuffer;
import research.zkactor.Probe;

/** Isolated after-I/O experiment: never fault a partial client request. */
public final class AfterBridge {
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
}
