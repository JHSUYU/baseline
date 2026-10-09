package org.apache.hadoop.hdfs.hdfs16independent;

import java.io.BufferedWriter;
import java.io.EOFException;
import java.io.IOException;
import java.net.InetSocketAddress;
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

/** Exact actor-aware HDFS-16 I/O doors and the original target guard. */
public final class Probe {
  private static final class Fault {
    final String marker;
    final String api;
    final String actor;
    final String peer;
    final String pool;
    final int ordinal;
    final String exception;

    Fault(String[] parts) {
      marker = parts[0];
      api = parts[1];
      actor = parts[2];
      peer = parts[3];
      pool = parts[4];
      ordinal = Integer.parseInt(parts[5]);
      exception = parts[6];
    }
  }

  private static final List<Fault> FAULTS = new ArrayList<Fault>();
  private static final Map<String, Integer> HITS = new HashMap<String, Integer>();
  private static final ThreadLocal<String> LAST_TARGET = new ThreadLocal<String>();
  private static BufferedWriter writer;
  private static long sequence;
  private static int nextFault;
  private static int targetOrdinal;

  static {
    try {
      String trace = System.getProperty("hdfs16.independent.trace");
      if (trace != null && !trace.isEmpty()) {
        Path path = Paths.get(trace);
        Files.createDirectories(path.getParent());
        writer = Files.newBufferedWriter(path, StandardCharsets.UTF_8,
            StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
      }
      String plan = System.getProperty("hdfs16.independent.fault.plan");
      if (plan != null && !plan.isEmpty()) {
        for (String line : Files.readAllLines(Paths.get(plan), StandardCharsets.UTF_8)) {
          if (line.trim().isEmpty() || line.startsWith("#")) {
            continue;
          }
          String[] parts = line.split("\t", -1);
          if (parts.length != 7) {
            throw new IllegalArgumentException("V3 fault plan needs seven fields: " + line);
          }
          FAULTS.add(new Fault(parts));
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

  private static String field(String name, String value) {
    return ",\"" + name + "\":\"" + escape(value) + "\"";
  }

  private static void emit(String event, String fields) {
    if (writer == null) {
      return;
    }
    try {
      writer.write("{\"seq\":" + (++sequence) + ",\"event\":\"" + event +
          "\",\"thread\":\"" + escape(Thread.currentThread().getName()) +
          "\"" + fields + "}\n");
      writer.flush();
    } catch (IOException error) {
      throw new IllegalStateException("HDFS-16 V3 trace write failed", error);
    }
  }

  private static String rpcApi() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      String owner = frame.getClassName();
      if (owner.startsWith("org.apache.hadoop.hdfs.") &&
          owner.endsWith("TranslatorPB")) {
        String method = frame.getMethodName();
        if (method.startsWith("lambda$")) {
          method = method.substring(7);
          int suffix = method.indexOf('$');
          if (suffix > 0) {
            method = method.substring(0, suffix);
          }
        }
        return owner.substring(owner.lastIndexOf('.') + 1) + "." + method;
      }
    }
    return "other";
  }

  private static String fileApi(String detail) {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (frame.getClassName().equals(
          "org.apache.hadoop.hdfs.server.namenode.FSNamesystem")) {
        return frame.getMethodName() + ":" + detail;
      }
    }
    return "editLog:" + detail;
  }

  private static String targetCaller() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      String owner = frame.getClassName();
      if (owner.equals("org.apache.hadoop.hdfs.server.blockmanagement.BlockInfo") &&
          frame.getMethodName().equals("commitBlock")) {
        return "BlockInfo.commitBlock";
      }
      if (owner.equals("org.apache.hadoop.hdfs.server.blockmanagement.BlockManager") &&
          frame.getMethodName().equals("updateLastBlock")) {
        return "BlockManager.updateLastBlock";
      }
    }
    return "other";
  }

  /** Called by the actual Client.getRpcResponse or durable edit-log flush. */
  public static synchronized void io(String marker, String detail,
      InetSocketAddress remote, int callId) throws IOException {
    String api = "RPC_RESPONSE".equals(marker) ? rpcApi() : fileApi(detail);
    String actor = "FILE_FLUSH".equals(marker)
        ? "NN0" : Hdfs16ActorRegistry.currentActorKey();
    String peer = Hdfs16ActorRegistry.peerClass(remote);
    String pool = Hdfs16ActorRegistry.currentPool();
    if (pool == null) {
      pool = "NO_BP";
    }
    String key = marker + "\t" + api + "\t" + actor + "\t" + peer + "\t" + pool;
    Integer previous = HITS.get(key);
    int ordinal = previous == null ? 1 : previous.intValue() + 1;
    HITS.put(key, ordinal);
    String fields = field("marker", marker) + field("api", api) +
        field("actorKey", actor) + field("peerClass", peer) +
        field("poolClass", pool) + ",\"ordinal\":" + ordinal +
        ",\"rpcCallId\":" + callId +
        field("rawDatanodeUuid", Hdfs16ActorRegistry.currentUuid()) +
        field("rawBlockPoolId", Hdfs16ActorRegistry.currentRawPool()) +
        field("rawRemoteEndpoint", remote == null ? null : remote.toString()) +
        ",\"manualSelectedRegistration\":" +
        Hdfs16ActorRegistry.manualRegistration();
    emit("IO_OBSERVED", fields);
    if (nextFault < FAULTS.size()) {
      Fault fault = FAULTS.get(nextFault);
      if (fault.marker.equals(marker) && fault.api.equals(api) &&
          fault.actor.equals(actor) && fault.peer.equals(peer) &&
          fault.pool.equals(pool) && fault.ordinal == ordinal &&
          !"UNBOUND".equals(actor) && !"UNBOUND".equals(peer)) {
        emit("FAULT_MATCHED", fields + field("exception", fault.exception) +
            ",\"planIndex\":" + nextFault);
        nextFault++;
        emit("FAULT_APPLIED", fields + field("exception", fault.exception) +
            ",\"planIndex\":" + (nextFault - 1));
        if ("EOFException".equals(fault.exception)) {
          throw new EOFException("HDFS-16 V3 injected at " + key + "#" + ordinal);
        }
        if ("SocketTimeoutException".equals(fault.exception)) {
          throw new SocketTimeoutException(
              "HDFS-16 V3 injected at " + key + "#" + ordinal);
        }
        throw new IOException("HDFS-16 V3 injected at " + key + "#" + ordinal);
      }
    }
  }

  public static synchronized void guard(boolean allowed, long blockId,
      long currentGenerationStamp, long proposedGenerationStamp,
      boolean underConstructionPresent) {
    targetOrdinal++;
    String fields = field("site", "BlockInfo.setGenerationStampAndVerifyReplicas:428") +
        ",\"ordinal\":" + targetOrdinal + ",\"allowed\":" + allowed +
        field("targetActor", "NN0") +
        field("selectedDatanodeActor", Hdfs16ActorRegistry.selectedActorKey()) +
        field("selectedDatanodeUuid", Hdfs16ActorRegistry.selectedUuid()) +
        field("selectedBlockPool", Hdfs16ActorRegistry.selectedPool()) +
        field("caller", targetCaller()) + ",\"blockId\":" + blockId +
        ",\"currentGenerationStamp\":" + currentGenerationStamp +
        ",\"proposedGenerationStamp\":" + proposedGenerationStamp +
        ",\"underConstructionPresent\":" + underConstructionPresent;
    LAST_TARGET.set(fields);
    emit("TARGET_GUARD", fields);
  }

  public static synchronized void targetException(IllegalStateException error) {
    emit("TARGET_EXCEPTION", LAST_TARGET.get() +
        field("type", "java.lang.IllegalStateException") +
        field("message", error.getMessage()));
  }
}
