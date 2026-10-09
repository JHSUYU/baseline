package org.apache.hadoop.hdfs.hdfs40independent;

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

/** Independent, case-local source probes and ordered I/O exception gate. */
public final class Probe {
  private static final class Fault {
    final String marker;
    final String api;
    final String endpoint;
    final int ordinal;
    final String exception;
    Fault(String marker, String api, String endpoint, int ordinal,
        String exception) {
      this.marker = marker;
      this.api = api;
      this.endpoint = endpoint;
      this.ordinal = ordinal;
      this.exception = exception;
    }
  }

  private static final List<Fault> FAULTS = new ArrayList<Fault>();
  private static final Map<String, Integer> IO_HITS = new HashMap<String, Integer>();
  private static final Map<String, Integer> TARGET_HITS = new HashMap<String, Integer>();
  private static final ThreadLocal<String> LAST_TARGET = new ThreadLocal<String>();
  private static final ThreadLocal<String> REQUEST_CONTEXT = new ThreadLocal<String>();
  private static BufferedWriter writer;
  private static long sequence;
  private static int nextFault;

  static {
    try {
      String trace = System.getProperty("hdfs40.independent.trace");
      if (trace != null && !trace.isEmpty()) {
        Path path = Paths.get(trace);
        Files.createDirectories(path.getParent());
        writer = Files.newBufferedWriter(path, StandardCharsets.UTF_8,
            StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
      }
      String plan = System.getProperty("hdfs40.independent.fault.plan");
      if (plan != null && !plan.isEmpty()) {
        for (String line : Files.readAllLines(Paths.get(plan), StandardCharsets.UTF_8)) {
          if (line.trim().isEmpty() || line.startsWith("#")) {
            continue;
          }
          String[] parts = line.split("\\t", -1);
          if (parts.length != 5) {
            throw new IllegalArgumentException("Invalid fault plan line: " + line);
          }
          FAULTS.add(new Fault(parts[0], parts[1], parts[2],
              Integer.parseInt(parts[3]), parts[4]));
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
      throw new IllegalStateException("HDFS-40 trace write failed", error);
    }
  }

  private static String rpcApi() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      String owner = frame.getClassName();
      if (owner.startsWith("org.apache.hadoop.hdfs.") &&
          owner.endsWith("TranslatorPB")) {
        return owner.substring(owner.lastIndexOf('.') + 1) + "." +
            frame.getMethodName();
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

  public static void requestContext(String key) {
    REQUEST_CONTEXT.set(key);
  }

  public static void clearRequestContext() {
    REQUEST_CONTEXT.remove();
  }

  public static synchronized void io(String marker, String detail)
      throws IOException {
    boolean rpc = marker.startsWith("RPC_");
    String context = REQUEST_CONTEXT.get();
    String api = rpc ? rpcApi() : fileApi(detail);
    if (rpc && context != null) {
      api += "[" + context + "]";
    }
    String endpoint = rpc ?
        ("other".equals(api) ? "other" : "nn0") : "nnlocal";
    String key = marker + "\t" + api + "\t" + endpoint;
    Integer previous = IO_HITS.get(key);
    int ordinal = previous == null ? 1 : previous.intValue() + 1;
    IO_HITS.put(key, ordinal);
    String fields = ",\"marker\":\"" + escape(marker) +
        "\",\"api\":\"" + escape(api) +
        "\",\"endpoint\":\"" + escape(endpoint) +
        "\",\"ordinal\":" + ordinal;
    emit("IO_OBSERVED", fields);
    if (nextFault < FAULTS.size()) {
      Fault fault = FAULTS.get(nextFault);
      if (fault.marker.equals(marker) && fault.api.equals(api) &&
          fault.endpoint.equals(endpoint) && fault.ordinal == ordinal) {
        emit("FAULT_MATCHED", fields);
        nextFault++;
        emit("FAULT_APPLIED", fields + ",\"exception\":\"" +
            escape(fault.exception) + "\"");
        if ("EOFException".equals(fault.exception)) {
          throw new EOFException("HDFS-40 injected at " + key + "#" + ordinal);
        }
        if ("SocketTimeoutException".equals(fault.exception)) {
          throw new SocketTimeoutException(
              "HDFS-40 injected at " + key + "#" + ordinal);
        }
        throw new IOException("HDFS-40 injected at " + key + "#" + ordinal);
      }
    }
  }

  public static synchronized void guard(boolean complete, boolean sufficient,
      String path, long blockId, String state) {
    String key = path + "#" + blockId;
    Integer previous = TARGET_HITS.get(key);
    int ordinal = previous == null ? 1 : previous.intValue() + 1;
    TARGET_HITS.put(key, ordinal);
    String fields = ",\"site\":\"FSDirAppendOp.appendFile:136-139\"" +
        ",\"path\":\"" + escape(path) + "\"" +
        ",\"blockId\":" + blockId +
        ",\"state\":\"" + escape(state) + "\"" +
        ",\"ordinal\":" + ordinal +
        ",\"complete\":" + complete +
        ",\"sufficient\":" + sufficient +
        ",\"fatal\":" + (complete && !sufficient);
    LAST_TARGET.set(fields);
    emit("TARGET_GUARD", fields);
  }

  public static synchronized void targetException(IOException error) {
    String fields = LAST_TARGET.get();
    if (fields == null) {
      throw new IllegalStateException("Exact target exception without guard");
    }
    emit("TARGET_EXCEPTION", fields +
        ",\"type\":\"" + escape(error.getClass().getName()) + "\"" +
        ",\"message\":\"" + escape(error.getMessage()) + "\"");
  }
}
