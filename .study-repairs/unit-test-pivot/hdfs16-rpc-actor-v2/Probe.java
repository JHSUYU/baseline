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
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.apache.hadoop.hdfs.server.protocol.DatanodeRegistration;
import org.apache.hadoop.hdfs.server.datanode.DataNode;

/** Case-local recorder and exact ordered fault gate; no graph runtime. */
public final class Probe {
  private static final class Fault {
    final String marker;
    final String api;
    final String senderRole;
    final int ordinal;
    final String exception;

    Fault(String marker, String api, String senderRole, int ordinal, String exception) {
      this.marker = marker;
      this.api = api;
      this.senderRole = senderRole;
      this.ordinal = ordinal;
      this.exception = exception;
    }
  }

  private static final List<Fault> FAULTS = new ArrayList<Fault>();
  private static final Map<String, Integer> HITS = new HashMap<String, Integer>();
  private static final Set<Integer> NN_PORTS = new HashSet<Integer>();
  private static final Map<String, String> DN_ROLES = new HashMap<String, String>();
  private static final Map<String, String> ROLE_UUIDS = new HashMap<String, String>();
  private static final Set<String> CONFLICTED_ROLES = new HashSet<String>();
  private static BufferedWriter writer;
  private static long sequence;
  private static int nextFault;
  private static int targetOrdinal;
  private static final ThreadLocal<String> LAST_TARGET =
      new ThreadLocal<String>();
  private static final ThreadLocal<String> DN_RPC_ACTOR =
      new ThreadLocal<String>();
  private static final ThreadLocal<String> DN_RPC_ROLE =
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
          if (parts.length != 5) {
            throw new IllegalArgumentException("V2 fault plans require marker, API, sender actor, ordinal, exception: " + line);
          }
          FAULTS.add(new Fault(parts[0], parts[1], parts[2], Integer.parseInt(parts[3]),
              parts[4]));
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
          "\",\"threadId\":" + Thread.currentThread().getId() +
          fields + "}\n");
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

  /** The original JUnit obtains DN0 from this exact MiniDFSCluster list. */
  public static synchronized void registerRoles(List<DataNode> nodes) {
    if (nodes == null) return;
    for (int index = 0; index < nodes.size(); index++) {
      DataNode node = nodes.get(index);
      String uuid = node == null ? null : node.getDatanodeUuid();
      if (uuid == null || uuid.isEmpty()) continue;
      String role = "dn" + index;
      String existing = DN_ROLES.get(uuid);
      String roleUuid = ROLE_UUIDS.get(role);
      if (CONFLICTED_ROLES.contains(role)) continue;
      if ((existing != null && !existing.equals(role)) ||
          (roleUuid != null && !roleUuid.equals(uuid))) {
        DN_ROLES.remove(uuid); // Conflicting list position is never injectible.
        if (roleUuid != null) DN_ROLES.remove(roleUuid);
        ROLE_UUIDS.remove(role);
        CONFLICTED_ROLES.add(role);
        emit("DN_ROLE_CONFLICT", ",\"senderRole\":\"" + role +
            "\",\"dnUuid\":\"" + escape(uuid) + "\"");
        continue;
      }
      DN_ROLES.put(uuid, role);
      ROLE_UUIDS.put(role, uuid);
      emit("DN_ROLE_REGISTER", ",\"senderRole\":\"" + role +
          "\",\"dnUuid\":\"" + escape(uuid) +
          "\",\"dnObjectId\":" + System.identityHashCode(node));
    }
  }

  /** Offline smoke only; production uses registerRoles on the JUnit DN list. */
  public static synchronized void registerRoleForSmoke(String uuid, int index) {
    if (uuid == null || uuid.isEmpty() || index < 0) return;
    String role = "dn" + index;
    DN_ROLES.put(uuid, role);
    ROLE_UUIDS.put(role, uuid);
    emit("DN_ROLE_REGISTER", ",\"senderRole\":\"" + role +
        "\",\"dnUuid\":\"" + escape(uuid) +
        "\",\"dnObjectId\":-1");
  }

  /** Bind only a synchronous DatanodeProtocol RPC that carries its registration. */
  public static String bindDatanodeRpc(DatanodeRegistration registration) {
    String prior = DN_RPC_ACTOR.get();
    String uuid = registration == null ? null : registration.getDatanodeUuid();
    String bp = registration == null || registration.getNamespaceInfo() == null
        ? null : registration.getNamespaceInfo().getBlockPoolID();
    String actor = uuid == null || uuid.isEmpty() || bp == null || bp.isEmpty()
        ? null : "dn:" + uuid + "|bp:" + bp;
    DN_RPC_ACTOR.set(actor);
    String role;
    synchronized (Probe.class) { role = DN_ROLES.get(uuid); }
    DN_RPC_ROLE.set(role);
    emit("DN_RPC_BIND", ",\"senderActor\":\"" + escape(actor) +
        "\",\"senderRole\":\"" + escape(role) +
        "\",\"senderDnUuid\":\"" + escape(uuid) +
        "\",\"blockPoolId\":\"" + escape(bp) + "\"");
    return prior;
  }

  public static void restoreDatanodeRpc(String prior) {
    if (prior == null) {
      DN_RPC_ACTOR.remove();
      DN_RPC_ROLE.remove();
    } else {
      DN_RPC_ACTOR.set(prior);
      String uuid = prior.startsWith("dn:") && prior.contains("|bp:")
          ? prior.substring(3, prior.indexOf("|bp:")) : null;
      synchronized (Probe.class) { DN_RPC_ROLE.set(DN_ROLES.get(uuid)); }
    }
    emit("DN_RPC_UNBIND", ",\"senderActor\":\"" + escape(prior) +
        "\",\"senderRole\":\"" + escape(DN_RPC_ROLE.get()) + "\"");
  }

  public static synchronized void registerNnPort(int port) {
    if (port <= 0) return;
    NN_PORTS.add(port);
    emit("NN_ENDPOINT_REGISTER", ",\"peerPort\":" + port);
  }

  /** The Client hook provides the real remote NN port, not a thread-name guess. */
  public static synchronized void rpcResponse(int peerPort) throws IOException {
    String actor = DN_RPC_ACTOR.get();
    String role = DN_RPC_ROLE.get();
    if (actor == null || role == null || peerPort <= 0 || !NN_PORTS.contains(peerPort)) {
      emit("RPC_ACTOR_UNBOUND", ",\"api\":\"" + escape(rpcApi()) +
          "\",\"peerPort\":" + peerPort);
      return; // No actor identity, no fault injection.
    }
    ioObserved("RPC_RESPONSE", "Client.getRpcResponse", role, actor, peerPort);
  }

  public static synchronized void io(String marker, String detail)
      throws IOException {
    if ("RPC_RESPONSE".equals(marker)) {
      throw new IllegalStateException("coarse RPC hook used with V2 recorder");
    }
    ioObserved(marker, detail, "nn-editlog", "nn-editlog", -1);
  }

  private static void ioObserved(String marker, String detail,
      String senderRole, String senderActor, int peerPort) throws IOException {
    String api = "RPC_RESPONSE".equals(marker) ? rpcApi() : fileApi(detail);
    String key = marker + "\t" + api + "\t" + senderRole;
    Integer previous = HITS.get(key);
    int ordinal = previous == null ? 1 : previous.intValue() + 1;
    HITS.put(key, ordinal);
    String fields = ",\"marker\":\"" + escape(marker) +
        "\",\"api\":\"" + escape(api) +
        "\",\"senderActor\":\"" + escape(senderActor) +
        "\",\"senderRole\":\"" + escape(senderRole) +
        "\",\"peerPort\":" + peerPort +
        ",\"ordinal\":" + ordinal;
    emit("IO_OBSERVED", fields);
    if (nextFault < FAULTS.size()) {
      Fault fault = FAULTS.get(nextFault);
      if (fault.marker.equals(marker) && fault.api.equals(api) &&
          fault.senderRole.equals(senderRole) &&
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
