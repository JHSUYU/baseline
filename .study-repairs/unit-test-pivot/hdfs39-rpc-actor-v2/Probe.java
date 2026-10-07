package org.apache.hadoop.hdfs.hdfs39independent;

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
import java.util.Set;
import java.util.HashSet;
import org.apache.hadoop.hdfs.server.datanode.DataNode;
import org.apache.hadoop.hdfs.server.protocol.DatanodeRegistration;

/** Independent, case-local source probes and ordered I/O exception gate. */
public final class Probe {
  public static final class Source {
    final String uuid;
    final String bp;
    final String role;
    Source(String uuid, String bp, String role) {
      this.uuid = uuid;
      this.bp = bp;
      this.role = role;
    }
  }

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
  private static final ThreadLocal<Source> REQUEST_SOURCE = new ThreadLocal<Source>();
  private static final Map<String, String> SOURCE_ROLES = new HashMap<String, String>();
  private static final Set<Integer> NN_PORTS = new HashSet<Integer>();
  private static String expectedBlockPool;
  private static BufferedWriter writer;
  private static long sequence;
  private static int nextFault;

  static {
    try {
      String trace = System.getProperty("hdfs39.independent.trace");
      if (trace != null && !trace.isEmpty()) {
        Path path = Paths.get(trace);
        Files.createDirectories(path.getParent());
        writer = Files.newBufferedWriter(path, StandardCharsets.UTF_8,
            StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
      }
      String plan = System.getProperty("hdfs39.independent.fault.plan");
      if (plan != null && !plan.isEmpty()) {
        for (String line : Files.readAllLines(Paths.get(plan), StandardCharsets.UTF_8)) {
          if (line.trim().isEmpty() || line.startsWith("#")) {
            continue;
          }
          String[] parts = line.split("\\t", -1);
          if (parts.length != 5) {
            throw new IllegalArgumentException("Invalid fault plan line: " + line);
          }
          if (!("IOException".equals(parts[4]) || "EOFException".equals(parts[4]) ||
                "SocketTimeoutException".equals(parts[4]))) {
            throw new IllegalArgumentException("Unsupported fault type: " + parts[4]);
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

  private static synchronized void emit(String event, String fields) {
    if (writer == null) {
      return;
    }
    try {
      writer.write("{\"seq\":" + (++sequence) + ",\"event\":\"" + event +
          "\",\"thread\":\"" + escape(Thread.currentThread().getName()) +
          "\"" + fields + "}\n");
      writer.flush();
    } catch (IOException error) {
      throw new IllegalStateException("HDFS-39 trace write failed", error);
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
          if (suffix > 0) method = method.substring(0, suffix);
        }
        return owner.substring(owner.lastIndexOf('.') + 1) + "." +
            method;
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

  /** Read-only actor map from the original four-DN MiniDFSCluster fixture. */
  public static synchronized void registerCluster(List<DataNode> nodes,
      int nnPort, String blockPoolId) {
    if (nodes.size() != 4 || nnPort <= 0 || blockPoolId == null || blockPoolId.isEmpty())
      throw new IllegalStateException("HDFS-39 actor calibration requires four DNs and known NN/BP");
    expectedBlockPool = blockPoolId;
    NN_PORTS.add(nnPort);
    emit("NN_ENDPOINT_REGISTER", ",\"peerPort\":" + nnPort +
        ",\"blockPoolId\":\"" + escape(blockPoolId) + "\"");
    for (int i = 0; i < nodes.size(); i++) {
      String uuid = nodes.get(i).getDatanodeUuid();
      if (uuid == null || uuid.isEmpty() || SOURCE_ROLES.put(uuid, "dn" + i) != null)
        throw new IllegalStateException("Missing/duplicate DN UUID at slot " + i);
      emit("DN_ROLE_MAP", ",\"role\":\"dn" + i +
          "\",\"sourceUuid\":\"" + escape(uuid) + "\"");
    }
  }

  public static Source requestSource(DatanodeRegistration registration) {
    Source prior = REQUEST_SOURCE.get();
    String uuid = registration == null ? null : registration.getDatanodeUuid();
    String bp = registration == null || registration.getNamespaceInfo() == null
        ? null : registration.getNamespaceInfo().getBlockPoolID();
    String role;
    synchronized (Probe.class) {
      role = uuid == null ? null : SOURCE_ROLES.get(uuid);
      if (expectedBlockPool == null || !expectedBlockPool.equals(bp)) role = null;
    }
    REQUEST_SOURCE.set(new Source(uuid, bp, role));
    emit("DN_RPC_BIND", ",\"sourceUuid\":\"" + escape(uuid) +
        "\",\"blockPoolId\":\"" + escape(bp) +
        "\",\"sourceRole\":\"" + escape(role) + "\"");
    return prior;
  }

  public static void restoreRequestSource(Source prior) {
    if (prior == null) REQUEST_SOURCE.remove(); else REQUEST_SOURCE.set(prior);
    emit("DN_RPC_UNBIND", "");
  }

  public static String requestContext(String value) {
    String prior = REQUEST_CONTEXT.get();
    REQUEST_CONTEXT.set(value);
    return prior;
  }

  public static void restoreRequestContext(String prior) {
    if (prior == null) REQUEST_CONTEXT.remove(); else REQUEST_CONTEXT.set(prior);
  }

  public static synchronized void rpcIo(String marker, int peerPort) throws IOException {
    rpcIoWithApi(marker, peerPort, rpcApi());
  }

  static synchronized void rpcIoWithApi(String marker, int peerPort, String api)
      throws IOException {
    boolean dnApi = api.startsWith("DatanodeProtocolClientSideTranslatorPB.");
    boolean clientApi = api.startsWith("ClientNamenodeProtocolTranslatorPB.");
    Source source = REQUEST_SOURCE.get();
    String context = REQUEST_CONTEXT.get();
    boolean blockReport = api.startsWith(
        "DatanodeProtocolClientSideTranslatorPB.blockReceivedAndDeleted");
    boolean validBlockContext = context != null && context.matches(
        "blockReceivedAndDeleted:blocks=\\[[1-9][0-9]*(, [1-9][0-9]*)*\\]");
    boolean append = api.startsWith("ClientNamenodeProtocolTranslatorPB.append");
    boolean validAppendContext = "append:/testMultipleAppend/foo".equals(context);
    if (!NN_PORTS.contains(peerPort) || (dnApi && (source == null || source.role == null))
        || (blockReport && !validBlockContext)
        || (append && !validAppendContext)
        || (!dnApi && !clientApi)) {
      emit("RPC_ACTOR_UNBOUND", ",\"api\":\"" + escape(api) +
          "\",\"peerPort\":" + peerPort);
      return;
    }
    if (context != null) api += "[" + context + "]";
    String role = dnApi ? source.role : "client";
    ioObserved(marker, api, "nn0<-" + role, peerPort,
        dnApi ? source.uuid : "", dnApi ? source.bp : "");
  }

  public static synchronized void io(String marker, String detail)
      throws IOException {
    if (marker.startsWith("RPC_"))
      throw new IllegalStateException("Coarse HDFS-39 RPC hook used with actor V2");
    ioObserved(marker, fileApi(detail), "nnlocal", -1, "", "");
  }

  private static void ioObserved(String marker, String api, String endpoint,
      int peerPort, String sourceUuid, String blockPoolId) throws IOException {
    String key = marker + "\t" + api + "\t" + endpoint;
    Integer previous = IO_HITS.get(key);
    int ordinal = previous == null ? 1 : previous.intValue() + 1;
    IO_HITS.put(key, ordinal);
    String fields = ",\"marker\":\"" + escape(marker) +
        "\",\"api\":\"" + escape(api) +
        "\",\"endpoint\":\"" + escape(endpoint) +
        "\",\"peerPort\":" + peerPort +
        ",\"sourceUuid\":\"" + escape(sourceUuid) +
        "\",\"blockPoolId\":\"" + escape(blockPoolId) +
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
          throw new EOFException("HDFS-39 injected at " + key + "#" + ordinal);
        }
        if ("SocketTimeoutException".equals(fault.exception)) {
          throw new SocketTimeoutException(
              "HDFS-39 injected at " + key + "#" + ordinal);
        }
        throw new IOException("HDFS-39 injected at " + key + "#" + ordinal);
      }
    }
  }

  public static synchronized void guard(boolean committed, String path,
      long blockId, String state) {
    String key = path + "#" + blockId;
    Integer previous = TARGET_HITS.get(key);
    int ordinal = previous == null ? 1 : previous.intValue() + 1;
    TARGET_HITS.put(key, ordinal);
    String fields = ",\"site\":\"FSDirAppendOp.appendFile:131\"" +
        ",\"path\":\"" + escape(path) + "\"" +
        ",\"blockId\":" + blockId +
        ",\"state\":\"" + escape(state) + "\"" +
        ",\"ordinal\":" + ordinal +
        ",\"committed\":" + committed;
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
