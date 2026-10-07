package org.apache.hadoop.hdfs.hdfs43actor;

import java.io.BufferedWriter;
import java.io.EOFException;
import java.io.IOException;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.ipc.Server;

/** Case-local, graph-free I/O and exact truncate-guard recorder. */
public final class Probe {
  private static final class Context {
    final String api;
    final String path;
    final long blockId;
    final long requestedLength;
    final String sourceUuid;

    Context(String api, String path, long blockId, long requestedLength,
        String sourceUuid) {
      this.api = api;
      this.path = path;
      this.blockId = blockId;
      this.requestedLength = requestedLength;
      this.sourceUuid = sourceUuid;
    }
  }

  private static final class Fault {
    final String marker;
    final String api;
    final String endpoint;
    final String sourceRole;
    final String path;
    final long blockId;
    final long requestedLength;
    final int ordinal;
    final String exception;

    Fault(String[] parts) {
      if (parts.length != 9) {
        throw new IllegalArgumentException("HDFS-43 selector must have nine fields");
      }
      marker = parts[0];
      api = parts[1];
      endpoint = parts[2];
      sourceRole = parts[3];
      path = parts[4];
      blockId = Long.parseLong(parts[5]);
      requestedLength = Long.parseLong(parts[6]);
      ordinal = Integer.parseInt(parts[7]);
      exception = parts[8];
    }
  }

  private static final List<Fault> FAULTS = new ArrayList<Fault>();
  private static final Map<String, Integer> IO_HITS = new HashMap<String, Integer>();
  private static final Map<String, Integer> TARGET_HITS = new HashMap<String, Integer>();
  private static final Map<String, String> SOURCE_ROLES = new HashMap<String, String>();
  private static final ThreadLocal<Context> CONTEXT = new ThreadLocal<Context>();
  private static final ThreadLocal<String> LAST_TARGET = new ThreadLocal<String>();
  private static volatile String phase = "setup";
  private static BufferedWriter writer;
  private static long sequence;
  private static int nextFault;

  static {
    try {
      String trace = System.getProperty("hdfs43.actor.trace");
      if (trace != null && !trace.isEmpty()) {
        Path path = Paths.get(trace);
        Files.createDirectories(path.getParent());
        writer = Files.newBufferedWriter(path, StandardCharsets.UTF_8,
            StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
      }
      String plan = System.getProperty("hdfs43.actor.plan");
      if (plan != null && !plan.isEmpty()) {
        for (String line : Files.readAllLines(Paths.get(plan), StandardCharsets.UTF_8)) {
          if (!line.trim().isEmpty() && !line.startsWith("#")) {
            FAULTS.add(new Fault(line.split("\t", -1)));
          }
        }
      }
    } catch (IOException error) {
      throw new ExceptionInInitializerError(error);
    }
  }

  private Probe() { }

  private static String escape(String value) {
    if (value == null) {
      return "";
    }
    return value.replace("\\", "\\\\").replace("\"", "\\\"")
        .replace("\n", "\\n").replace("\r", "\\r");
  }

  private static String q(String value) {
    return "\"" + escape(value) + "\"";
  }

  public static String hex(byte[] bytes) {
    if (bytes == null) {
      return "";
    }
    final char[] digits = "0123456789abcdef".toCharArray();
    char[] result = new char[bytes.length * 2];
    for (int i = 0; i < bytes.length; i++) {
      result[2 * i] = digits[(bytes[i] >>> 4) & 15];
      result[2 * i + 1] = digits[bytes[i] & 15];
    }
    return new String(result);
  }

  private static void emit(String event, String fields) {
    if (writer == null) {
      return;
    }
    try {
      writer.write("{\"seq\":" + (++sequence) + ",\"event\":" + q(event)
          + ",\"thread\":" + q(Thread.currentThread().getName()) + fields + "}\n");
      writer.flush();
    } catch (IOException error) {
      throw new IllegalStateException("HDFS-43 actor trace write failed", error);
    }
  }

  public static synchronized void registerDatanodes(List<DataNode> nodes) {
    for (int i = 0; i < nodes.size(); i++) {
      String uuid = nodes.get(i).getDatanodeUuid();
      if (uuid == null) {
        throw new IllegalStateException("DataNode " + i + " has no UUID");
      }
      String role = "dn" + i;
      SOURCE_ROLES.put(uuid, role);
      emit("DN_ROLE_MAP", ",\"role\":" + q(role) + ",\"sourceUuid\":" + q(uuid));
    }
  }

  public static synchronized void markPhase(String value) {
    phase = value;
    emit("TEST_PHASE", ",\"phase\":" + q(value));
  }

  public static void truncateContext(String path, long newLength) {
    CONTEXT.set(new Context("truncate", path, -1L, newLength, null));
  }

  public static void blockReportContext(String sourceUuid, long blockId) {
    CONTEXT.set(new Context("blockReceivedAndDeleted", "", blockId, -1L,
        sourceUuid));
  }

  public static void clearContext() {
    CONTEXT.remove();
  }

  /** Called after Hadoop has sent an RPC, immediately before waiting for its reply. */
  public static synchronized void rpcResponse(int callId, byte[] clientId,
      String remote) throws IOException {
    Context context = CONTEXT.get();
    if (context == null) {
      return;
    }
    String role = context.sourceUuid == null ? "client"
        : SOURCE_ROLES.get(context.sourceUuid);
    if (role == null) {
      role = "unregistered";
    }
    String marker = "RPC_RESPONSE_WAIT";
    String endpoint = "nn0";
    String key = marker + "\t" + context.api + "\t" + endpoint + "\t" + role
        + "\t" + context.path + "\t" + context.blockId + "\t"
        + context.requestedLength;
    Integer old = IO_HITS.get(key);
    int ordinal = old == null ? 1 : old.intValue() + 1;
    IO_HITS.put(key, ordinal);
    String fields = ",\"marker\":" + q(marker) + ",\"api\":" + q(context.api)
        + ",\"endpoint\":" + q(endpoint) + ",\"sourceRole\":" + q(role)
        + ",\"sourceUuid\":" + q(context.sourceUuid)
        + ",\"path\":" + q(context.path)
        + ",\"blockId\":" + context.blockId
        + ",\"requestedLength\":" + context.requestedLength
        + ",\"ordinal\":" + ordinal + ",\"phase\":" + q(phase)
        + ",\"rpcKey\":" + q(hex(clientId) + ":" + callId)
        + ",\"remote\":" + q(remote);
    emit("IO_OBSERVED", fields);
    if (nextFault >= FAULTS.size()) {
      return;
    }
    Fault fault = FAULTS.get(nextFault);
    if (!fault.marker.equals(marker) || !fault.api.equals(context.api)
        || !fault.endpoint.equals(endpoint) || !fault.sourceRole.equals(role)
        || !fault.path.equals(context.path) || fault.blockId != context.blockId
        || fault.requestedLength != context.requestedLength
        || fault.ordinal != ordinal) {
      return;
    }
    emit("FAULT_MATCHED", fields);
    nextFault++;
    emit("FAULT_APPLIED", fields + ",\"exception\":" + q(fault.exception));
    String message = "HDFS-43 injected at " + key + "#" + ordinal;
    if ("EOFException".equals(fault.exception)) {
      throw new EOFException(message);
    }
    if ("SocketTimeoutException".equals(fault.exception)) {
      throw new SocketTimeoutException(message);
    }
    if (!"IOException".equals(fault.exception)) {
      throw new IllegalArgumentException("Unknown HDFS-43 fault: " + fault.exception);
    }
    throw new IOException(message);
  }

  public static synchronized void guard(String path, long blockId,
      long truncateBlockId, String state, long requestedLength,
      long inProgressLength) {
    String key = path + "#" + blockId;
    Integer old = TARGET_HITS.get(key);
    int ordinal = old == null ? 1 : old.intValue() + 1;
    TARGET_HITS.put(key, ordinal);
    String fields = ",\"site\":" + q("FSDirTruncateOp.truncate:113-117")
        + ",\"path\":" + q(path) + ",\"blockId\":" + blockId
        + ",\"truncateBlockId\":" + truncateBlockId
        + ",\"state\":" + q(state)
        + ",\"requestedLength\":" + requestedLength
        + ",\"inProgressLength\":" + inProgressLength
        + ",\"equal\":" + (requestedLength == inProgressLength)
        + ",\"ordinal\":" + ordinal + ",\"phase\":" + q(phase)
        + ",\"rpcKey\":" + q(hex(Server.getClientId()) + ":" + Server.getCallId());
    LAST_TARGET.set(fields);
    emit("TARGET_GUARD", fields);
  }

  public static synchronized void targetException(IOException error) {
    String fields = LAST_TARGET.get();
    if (fields == null) {
      throw new IllegalStateException("Truncate exception without matching guard");
    }
    emit("TARGET_EXCEPTION", fields + ",\"type\":" + q(error.getClass().getName())
        + ",\"message\":" + q(error.getMessage()));
  }
}
