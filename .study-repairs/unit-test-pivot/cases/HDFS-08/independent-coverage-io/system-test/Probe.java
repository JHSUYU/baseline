package org.apache.hadoop.hdfs.hdfs08independent;

import java.io.BufferedWriter;
import java.io.EOFException;
import java.io.File;
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
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Independent exact target and observed I/O recorder for original QJM JUnit. */
public final class Probe {
  private static final class Fault {
    final String marker;
    final String api;
    final String node;
    final int ordinal;
    final String exception;

    Fault(String marker, String api, String node, int ordinal,
        String exception) {
      this.marker = marker;
      this.api = api;
      this.node = node;
      this.ordinal = ordinal;
      this.exception = exception;
    }
  }

  private static final Pattern NODE = Pattern.compile("journalnode-(\\d+)");
  private static final List<Fault> FAULTS = new ArrayList<Fault>();
  private static final Map<String, Integer> HITS = new HashMap<String, Integer>();
  private static final Map<Integer, String> PORTS = new HashMap<Integer, String>();
  private static final ThreadLocal<String> LAST_TARGET = new ThreadLocal<String>();
  private static final ThreadLocal<String> LAST_NODE = new ThreadLocal<String>();
  private static final ThreadLocal<long[]> FINALIZE_CONTEXT =
      new ThreadLocal<long[]>();
  private static BufferedWriter writer;
  private static long sequence;
  private static int nextFault;

  static {
    try {
      String trace = System.getProperty("hdfs08.independent.trace");
      if (trace != null && !trace.isEmpty()) {
        Path path = Paths.get(trace);
        Files.createDirectories(path.getParent());
        writer = Files.newBufferedWriter(path, StandardCharsets.UTF_8,
            StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
      }
      String plan = System.getProperty("hdfs08.independent.fault.plan");
      if (plan != null && !plan.isEmpty()) {
        for (String line : Files.readAllLines(Paths.get(plan), StandardCharsets.UTF_8)) {
          if (line.trim().isEmpty() || line.startsWith("#")) {
            continue;
          }
          String[] fields = line.split("\\t", -1);
          if (fields.length != 5) {
            throw new IllegalArgumentException("Invalid fault plan line: " + line);
          }
          FAULTS.add(new Fault(fields[0], fields[1], fields[2],
              Integer.parseInt(fields[3]), fields[4]));
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
      throw new IllegalStateException("HDFS-08 independent trace write failed", error);
    }
  }

  public static String node(String path) {
    Matcher match = NODE.matcher(path == null ? "" : path);
    return match.find() ? "jn" + match.group(1) : "unknown";
  }

  public static synchronized void registerPort(int port, String storageRoot) {
    String node = node(storageRoot);
    PORTS.put(port, node);
    emit("NODE_PORT_REGISTER", ",\"port\":" + port +
        ",\"node\":\"" + escape(node) + "\"");
  }

  private static String rpcApi() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      String className = frame.getClassName();
      if (className.endsWith("QJournalProtocolTranslatorPB") ||
          className.endsWith("InterQJournalProtocolTranslatorPB")) {
        return className.substring(className.lastIndexOf('.') + 1) +
            "." + frame.getMethodName();
      }
    }
    return "other";
  }

  private static String journalCaller() {
    boolean seenCheck = false;
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (frame.getClassName().equals(
          "org.apache.hadoop.hdfs.qjournal.server.Journal")) {
        if (frame.getMethodName().equals("checkRequest")) {
          seenCheck = true;
        } else if (seenCheck) {
          return frame.getMethodName();
        }
      }
    }
    return "unknown";
  }

  public static synchronized void rpcResponse(int port) throws IOException {
    String api = rpcApi();
    String node = PORTS.containsKey(port) ? PORTS.get(port) : "unknown";
    io("RPC_RESPONSE", api, node);
  }

  public static synchronized void fileIo(String marker, File file, String detail)
      throws IOException {
    io(marker, file.getName() + ":" + detail, node(file.getAbsolutePath()));
  }

  public static synchronized void paxosIo(String phase) throws IOException {
    String node = LAST_NODE.get();
    io("PAXOS_FILE_WRITE", "persistPaxosData:" + phase,
        node == null ? "unknown" : node);
  }

  public static void finalizeContext(long startTxId, long endTxId) {
    FINALIZE_CONTEXT.set(new long[] {startTxId, endTxId});
  }

  public static void clearFinalizeContext() {
    FINALIZE_CONTEXT.remove();
  }

  private static void io(String marker, String api, String node)
      throws IOException {
    String key = marker + "\t" + api + "\t" + node;
    Integer previous = HITS.get(key);
    int ordinal = previous == null ? 1 : previous.intValue() + 1;
    HITS.put(key, ordinal);
    String fields = ",\"marker\":\"" + escape(marker) +
        "\",\"api\":\"" + escape(api) +
        "\",\"node\":\"" + escape(node) +
        "\",\"ordinal\":" + ordinal;
    emit("IO_OBSERVED", fields);
    if (nextFault < FAULTS.size()) {
      Fault fault = FAULTS.get(nextFault);
      if (fault.marker.equals(marker) && fault.api.equals(api) &&
          fault.node.equals(node) && fault.ordinal == ordinal) {
        emit("FAULT_MATCHED", fields);
        nextFault++;
        emit("FAULT_APPLIED", fields + ",\"exception\":\"" +
            escape(fault.exception) + "\"");
        if ("EOFException".equals(fault.exception)) {
          throw new EOFException("HDFS-08 independent injected at " + key +
              "#" + ordinal);
        }
        if ("SocketTimeoutException".equals(fault.exception)) {
          throw new SocketTimeoutException("HDFS-08 independent injected at " +
              key + "#" + ordinal);
        }
        throw new IOException("HDFS-08 independent injected at " + key +
            "#" + ordinal);
      }
    }
  }

  public static synchronized void guard(File currentDir, String journalId,
      long requestEpoch, long promisedEpoch, long serial) {
    String node = node(currentDir.getAbsolutePath());
    LAST_NODE.set(node);
    String caller = journalCaller();
    long[] segment = FINALIZE_CONTEXT.get();
    String key = node + "\t" + caller;
    Integer previous = HITS.get("TARGET\t" + key);
    int ordinal = previous == null ? 1 : previous.intValue() + 1;
    HITS.put("TARGET\t" + key, ordinal);
    String fields = ",\"site\":\"Journal.checkRequest:486\"" +
        ",\"node\":\"" + escape(node) +
        "\",\"caller\":\"" + escape(caller) +
        "\",\"ordinal\":" + ordinal +
        ",\"journalId\":\"" + escape(journalId) +
        "\",\"requestEpoch\":" + requestEpoch +
        ",\"promisedEpoch\":" + promisedEpoch +
        ",\"serial\":" + serial +
        ",\"segmentStartTxId\":" + (segment == null ? -1 : segment[0]) +
        ",\"segmentEndTxId\":" + (segment == null ? -1 : segment[1]) +
        ",\"allowed\":" + (requestEpoch >= promisedEpoch);
    LAST_TARGET.set(fields);
    emit("TARGET_GUARD", fields);
  }

  public static synchronized void targetException(IOException error) {
    emit("TARGET_EXCEPTION", LAST_TARGET.get() +
        ",\"type\":\"java.io.IOException\"" +
        ",\"message\":\"" + escape(error.getMessage()) + "\"");
  }
}
