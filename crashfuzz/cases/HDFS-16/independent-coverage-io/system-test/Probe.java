package org.apache.hadoop.hdfs.hdfs16independent;

import java.io.BufferedWriter;
import java.io.EOFException;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.net.SocketTimeoutException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Case-local recorder and exact ordered fault gate; no graph runtime. */
public final class Probe {
  private static final class Fault {
    final String marker;
    final String api;
    final int ordinal;
    final String exception;

    Fault(String marker, String api, int ordinal, String exception) {
      this.marker = marker;
      this.api = api;
      this.ordinal = ordinal;
      this.exception = exception;
    }
  }

  private static final List<Fault> FAULTS = new ArrayList<Fault>();
  private static final Map<String, Integer> HITS = new HashMap<String, Integer>();
  private static BufferedWriter writer;
  private static long sequence;
  private static int nextFault;
  private static int targetOrdinal;
  private static final ThreadLocal<String> LAST_TARGET =
      new ThreadLocal<String>();

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
          String[] parts = line.split("\\t", -1);
          if (parts.length != 4) {
            throw new IllegalArgumentException("Invalid fault plan line: " + line);
          }
          FAULTS.add(new Fault(parts[0], parts[1], Integer.parseInt(parts[2]),
              parts[3]));
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
      throw new IllegalStateException("HDFS-16 trace write failed", error);
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

  public static synchronized void io(String marker, String detail)
      throws IOException {
    String api = "RPC_RESPONSE".equals(marker) ? rpcApi() : fileApi(detail);
    String key = marker + "\t" + api;
    Integer previous = HITS.get(key);
    int ordinal = previous == null ? 1 : previous.intValue() + 1;
    HITS.put(key, ordinal);
    String fields = ",\"marker\":\"" + escape(marker) +
        "\",\"api\":\"" + escape(api) + "\",\"ordinal\":" + ordinal;
    emit("IO_OBSERVED", fields);
    if (nextFault < FAULTS.size()) {
      Fault fault = FAULTS.get(nextFault);
      if (fault.marker.equals(marker) && fault.api.equals(api) &&
          fault.ordinal == ordinal) {
        emit("FAULT_MATCHED", fields);
        nextFault++;
        emit("FAULT_APPLIED", fields + ",\"exception\":\"" +
            escape(fault.exception) + "\"");
        if ("EOFException".equals(fault.exception)) {
          throw new EOFException("HDFS-16 injected at " + key + "#" + ordinal);
        }
        if ("SocketTimeoutException".equals(fault.exception)) {
          throw new SocketTimeoutException(
              "HDFS-16 injected at " + key + "#" + ordinal);
        }
        throw new IOException("HDFS-16 injected at " + key + "#" + ordinal);
      }
    }
  }

  public static synchronized void guard(boolean allowed, long blockId,
      long currentGenerationStamp, long proposedGenerationStamp,
      boolean underConstructionPresent) {
    targetOrdinal++;
    String fields = ",\"site\":\"BlockInfo.setGenerationStampAndVerifyReplicas:428\"" +
        ",\"ordinal\":" + targetOrdinal + ",\"allowed\":" + allowed +
        ",\"caller\":\"" + targetCaller() + "\"" +
        ",\"blockId\":" + blockId +
        ",\"currentGenerationStamp\":" + currentGenerationStamp +
        ",\"proposedGenerationStamp\":" + proposedGenerationStamp +
        ",\"underConstructionPresent\":" + underConstructionPresent;
    LAST_TARGET.set(fields);
    emit("TARGET_GUARD", fields);
  }

  public static synchronized void targetException(IllegalStateException error) {
    emit("TARGET_EXCEPTION", LAST_TARGET.get() +
        ",\"type\":\"java.lang.IllegalStateException\"" +
        ",\"message\":\"" + escape(error.getMessage()) + "\"");
  }
}
