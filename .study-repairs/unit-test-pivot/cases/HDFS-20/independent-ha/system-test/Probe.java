package org.apache.hadoop.hdfs.hdfs20haindependent;

import java.io.BufferedWriter;
import java.io.EOFException;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.net.SocketTimeoutException;
import java.net.InetSocketAddress;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;

/** Case-local recorder and exact ordered fault gate; no graph runtime. */
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
  private static final Map<String, Integer> HITS = new HashMap<String, Integer>();
  private static final Map<Integer, String> ENDPOINT_LABELS =
      new HashMap<Integer, String>();
  private static final IdentityHashMap<Object, Integer> BPOS_IDS =
      new IdentityHashMap<Object, Integer>();
  private static final IdentityHashMap<Object, Integer> ACTOR_IDS =
      new IdentityHashMap<Object, Integer>();
  private static BufferedWriter writer;
  private static long sequence;
  private static int nextFault;
  private static int targetOrdinal;
  private static final ThreadLocal<String> LAST_TARGET =
      new ThreadLocal<String>();

  static {
    try {
      String trace = System.getProperty("hdfs20ha.independent.trace");
      if (trace != null && !trace.isEmpty()) {
        Path path = Paths.get(trace);
        Files.createDirectories(path.getParent());
        writer = Files.newBufferedWriter(path, StandardCharsets.UTF_8,
            StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
      }
      String plan = System.getProperty("hdfs20ha.independent.fault.plan");
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
      throw new IllegalStateException("HDFS-20 trace write failed", error);
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

  private static int identityOrdinal(IdentityHashMap<Object, Integer> ids,
      Object value) {
    Integer previous = ids.get(value);
    if (previous != null) {
      return previous.intValue();
    }
    int ordinal = ids.size() + 1;
    ids.put(value, ordinal);
    return ordinal;
  }

  public static synchronized void bposCreated(Object bpos,
      Iterable<?> actors, List<InetSocketAddress> addresses) {
    int bposId = identityOrdinal(BPOS_IDS, bpos);
    int count = 0;
    for (Object actor : actors) {
      int actorId = identityOrdinal(ACTOR_IDS, actor);
      if (count >= addresses.size()) {
        throw new IllegalStateException("missing NameNode address for actor");
      }
      ENDPOINT_LABELS.put(addresses.get(count).getPort(),
          "bpos" + bposId + ":actor" + actorId);
      count++;
    }
    emit("BPOS_CREATED", ",\"bposInstance\":" + bposId +
        ",\"actorCount\":" + count);
  }

  public static synchronized void io(String marker, String detail)
      throws IOException {
    apply(marker, fileApi(detail), "local");
  }

  public static synchronized void io(String marker,
      InetSocketAddress address) throws IOException {
    String endpoint = ENDPOINT_LABELS.get(address.getPort());
    apply(marker, rpcApi(), endpoint == null ? "unmapped" : endpoint);
  }

  private static void apply(String marker, String api, String endpoint)
      throws IOException {
    String key = marker + "\t" + api + "\t" + endpoint;
    Integer previous = HITS.get(key);
    int ordinal = previous == null ? 1 : previous.intValue() + 1;
    HITS.put(key, ordinal);
    String fields = ",\"marker\":\"" + escape(marker) +
        "\",\"api\":\"" + escape(api) +
        "\",\"endpoint\":\"" + escape(endpoint) +
        "\",\"ordinal\":" + ordinal;
    emit("IO_OBSERVED", fields);
    if (nextFault < FAULTS.size()) {
      Fault fault = FAULTS.get(nextFault);
      if (fault.marker.equals(marker) && fault.api.equals(api) &&
          fault.endpoint.equals(endpoint) &&
          fault.ordinal == ordinal) {
        emit("FAULT_MATCHED", fields);
        nextFault++;
        emit("FAULT_APPLIED", fields + ",\"exception\":\"" +
            escape(fault.exception) + "\"");
        if ("EOFException".equals(fault.exception)) {
          throw new EOFException("HDFS-20 injected at " + key + "#" + ordinal);
        }
        if ("SocketTimeoutException".equals(fault.exception)) {
          throw new SocketTimeoutException(
              "HDFS-20 injected at " + key + "#" + ordinal);
        }
        throw new IOException("HDFS-20 injected at " + key + "#" + ordinal);
      }
    }
  }

  public static synchronized void guard(boolean allowed, Object bpos,
      Object actor, long txid, long lastActiveClaimTxId,
      boolean nnClaimsActive, boolean bposThinksActive) {
    targetOrdinal++;
    String fields = ",\"site\":\"BPOfferService.updateActorStatesFromHeartbeat:606\"" +
        ",\"ordinal\":" + targetOrdinal + ",\"allowed\":" + allowed +
        ",\"bposInstance\":" + identityOrdinal(BPOS_IDS, bpos) +
        ",\"actorInstance\":" + identityOrdinal(ACTOR_IDS, actor) +
        ",\"txid\":" + txid +
        ",\"lastActiveClaimTxId\":" + lastActiveClaimTxId +
        ",\"nnClaimsActive\":" + nnClaimsActive +
        ",\"bposThinksActive\":" + bposThinksActive;
    LAST_TARGET.set(fields);
    emit("TARGET_GUARD", fields);
  }

  public static synchronized void targetException(AssertionError error) {
    emit("TARGET_EXCEPTION", LAST_TARGET.get() +
        ",\"type\":\"java.lang.AssertionError\"" +
        ",\"message\":\"" + escape(error.getMessage()) + "\"");
  }
}
