package baseline.solr05v4;

import java.io.BufferedWriter;
import java.io.FileWriter;
import java.io.IOException;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.HashSet;
import java.util.Set;
import org.apache.solr.cloud.overseer.ZkWriteCommand;
import org.apache.solr.common.cloud.ClusterState;
import org.apache.solr.common.cloud.DocCollection;
import org.apache.solr.common.cloud.Replica;
import org.apache.solr.common.cloud.Slice;
import org.apache.zookeeper.KeeperException;

/** Actual ZK receiver, reader, Jetty role and registration-context I/O. */
public final class FeedbackProbe {
  private static final class Context {
    final Object client, reader;
    final String node, collection, shard, replica, core;
    Context(Object client, Object reader, String node, String collection,
            String shard, String replica, String core) {
      this.client = client;
      this.reader = reader;
      this.node = node;
      this.collection = collection;
      this.shard = shard;
      this.replica = replica;
      this.core = core;
    }
  }

  private static final class Fault {
    final String operation, path, caller, actor, collection, shard, replica, core, after;
    final int ordinal, seedGlobal;
    final boolean relative;
    int seen, globalSeen;
    Fault(String spec) {
      String[] f = spec.split("\\|", -1);
      if (f.length != 9 && f.length != 11)
        throw new IllegalArgumentException("Expected actor and register-context selector: " + spec);
      operation = f[0]; path = f[1]; relative = f[2].startsWith("@");
      ordinal = Integer.parseInt(relative ? f[2].substring(1) : f[2]);
      caller = f[3]; actor = f[4]; collection = f[5]; shard = f[6];
      replica = f[7]; core = f[8];
      after = relative ? f[9] : "";
      seedGlobal = relative ? Integer.parseInt(f[10].replaceFirst("^seed_global=", "")) : 0;
      if (operation.isEmpty() || path.isEmpty() || ordinal <= 0 ||
          !caller.startsWith("caller=") ||
          !(actor.equals("actor=receiver_state_read_for_replica") ||
            actor.equals("actor=jetty:host_of_replica") ||
            actor.equals("actor=overseer_writer_for_replica")) ||
          !collection.startsWith("collection=") || !shard.startsWith("shard=") ||
          !replica.startsWith("replica=") || !core.startsWith("core=") ||
          collection.endsWith("<none>") || shard.endsWith("<none>") ||
          replica.endsWith("<none>") || core.endsWith("<none>") ||
          relative != (f.length == 11) ||
          (relative && (!after.matches("after=F[0-9]+") ||
                        !f[10].startsWith("seed_global=") || seedGlobal <= 0)))
        throw new IllegalArgumentException("Invalid actor/context selector: " + spec);
    }
  }

  private static final Map<Object, String> NODE_BY_CLIENT = new IdentityHashMap<>();
  private static final Map<Object, Object> READER_BY_CLIENT = new IdentityHashMap<>();
  private static final Map<String, String> ROLE_BY_NODE = new HashMap<>();
  private static final Map<String, String> NODE_BY_ROLE = new HashMap<>();
  private static final Map<String, Context> REGISTER_BY_REPLICA = new HashMap<>();
  private static final class Pending {
    final String collection, shard, replica, core, targetNode;
    boolean ambiguous;
    Pending(String collection, String shard, Replica value, String node) {
      this.collection = collection;
      this.shard = shard;
      this.replica = value.getName();
      this.core = value.getCoreName();
      this.targetNode = node;
    }
    String semantic() {
      return collection + "\t" + shard + "\t" + replica + "\t" + core;
    }
  }
  private static final Map<Object, Map<String, Pending>> PENDING_BY_WRITER =
      new IdentityHashMap<>();
  private static final Map<String, Object> WRITER_BY_SEMANTIC = new HashMap<>();
  private static final Set<String> AMBIGUOUS_SEMANTICS = new HashSet<>();
  private static final class CommittedWrite {
    final Pending pending;
    final Object writer;
    final int version;
    CommittedWrite(Pending pending, Object writer, int version) {
      this.pending = pending;
      this.writer = writer;
      this.version = version;
    }
  }
  private static final Map<String, CommittedWrite> WRITES_BY_VERSION = new HashMap<>();
  private static final Set<String> AMBIGUOUS_VERSIONS = new HashSet<>();
  private static final ThreadLocal<Deque<Context>> REGISTERS =
      ThreadLocal.withInitial(ArrayDeque::new);
  private static final List<Fault> FAULTS = parseFaults();
  private static final BufferedWriter TRACE = openTrace();
  private static long sequence;
  private static int nextFault;
  private static String lastApplied = "<none>";
  private FeedbackProbe() {}

  private static List<Fault> parseFaults() {
    List<Fault> faults = new ArrayList<>();
    String value = System.getProperty("solr05.v4.faults", "");
    if (!value.isEmpty()) for (String spec : value.split(";")) faults.add(new Fault(spec));
    return faults;
  }
  private static BufferedWriter openTrace() {
    String path = System.getProperty("solr05.v4.trace", "");
    if (path.isEmpty()) return null;
    try { return new BufferedWriter(new FileWriter(path)); }
    catch (IOException e) { throw new ExceptionInInitializerError(e); }
  }
  private static void event(String kind, String payload) {
    long current = ++sequence;
    if (TRACE == null) return;
    try {
      TRACE.write(current + "\t" + System.nanoTime() + "\t" + kind + "\t" + payload + "\n");
      TRACE.flush();
    } catch (IOException e) { throw new IllegalStateException(e); }
  }
  private static String safe(String value) {
    return value == null ? "<none>" : value.replace('\t', '_').replace('\n', '_').replace('|', '_');
  }
  private static String contextFields(Context ctx) {
    return "collection=" + safe(ctx == null ? null : ctx.collection) +
        "\tshard=" + safe(ctx == null ? null : ctx.shard) +
        "\treplica=" + safe(ctx == null ? null : ctx.replica) +
        "\tcore=" + safe(ctx == null ? null : ctx.core);
  }
  private static String stableCaller() {
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      String name = frame.getClassName();
      if (name.startsWith("org.apache.solr.") &&
          !name.equals("org.apache.solr.common.cloud.SolrZkClient"))
        return name + "#" + frame.getMethodName() + ":" + frame.getLineNumber();
    }
    return "<external>";
  }

  public static synchronized void registerNode(Object client, Object reader, String node) {
    if (client == null || reader == null || node == null)
      throw new IllegalArgumentException("Incomplete client/reader/node registration");
    String existing = NODE_BY_CLIENT.put(client, node);
    Object priorReader = READER_BY_CLIENT.put(client, reader);
    if ((existing != null && !existing.equals(node)) ||
        (priorReader != null && priorReader != reader))
      throw new IllegalStateException("Client registration changed identity");
    event("ACTOR_REGISTERED", "client_id=" + System.identityHashCode(client) +
        "\treader_id=" + System.identityHashCode(reader) + "\tnode=" + safe(node));
  }
  public static synchronized void registerJettyRole(String role, String node) {
    if (!role.matches("node[1-9][0-9]*") || node == null)
      throw new IllegalArgumentException("Invalid Jetty role/node");
    String oldRole = ROLE_BY_NODE.put(node, role);
    String oldNode = NODE_BY_ROLE.put(role, node);
    if ((oldRole != null && !oldRole.equals(role)) ||
        (oldNode != null && !oldNode.equals(node)))
      throw new IllegalStateException("Ambiguous Jetty role assignment");
    event("JETTY_ROLE_BOUND", "role=" + role + "\tnode=" + safe(node));
  }
  public static synchronized void enterRegister(Object client, Object reader, String node,
      String collection, String shard, String replica, String core) {
    if (!node.equals(NODE_BY_CLIENT.get(client)) || READER_BY_CLIENT.get(client) != reader ||
        collection == null || shard == null || replica == null || core == null)
      throw new IllegalStateException("Unbound or incomplete register context");
    Context ctx = new Context(client, reader, node, collection, shard, replica, core);
    String semantic = collection + "\t" + shard + "\t" + replica + "\t" + core;
    Context previous = REGISTER_BY_REPLICA.get(semantic);
    if (previous != null && (previous.client != client || previous.reader != reader ||
        !previous.node.equals(node)))
      throw new IllegalStateException("Ambiguous replica host/client/reader within run");
    REGISTER_BY_REPLICA.put(semantic, ctx);
    REGISTERS.get().push(ctx);
    event("REGISTER_ENTER", contextFields(ctx) + "\tnode=" + safe(node) +
        "\tclient_id=" + System.identityHashCode(client) +
        "\treader_id=" + System.identityHashCode(reader) +
        "\tthread=" + safe(Thread.currentThread().getName()));
  }
  public static synchronized void exitRegister(Object client, String core) {
    Deque<Context> stack = REGISTERS.get();
    if (stack.isEmpty() || stack.peek().client != client || !stack.peek().core.equals(core))
      throw new IllegalStateException("Register context stack mismatch");
    Context ctx = stack.pop();
    event("REGISTER_EXIT", contextFields(ctx) + "\tnode=" + safe(ctx.node) +
        "\tclient_id=" + System.identityHashCode(client) +
        "\treader_id=" + System.identityHashCode(ctx.reader) +
        "\tthread=" + safe(Thread.currentThread().getName()));
    if (stack.isEmpty()) REGISTERS.remove();
  }

  public static synchronized void recordUpstreamUpdate(Object writer,
      ClusterState previous, List<ZkWriteCommand> commands) {
    for (ZkWriteCommand cmd : commands) {
      if (cmd.noop || !"testAddMultipleReplicas".equals(cmd.name) ||
          cmd.collection == null || !cmd.persistCollState) continue;
      DocCollection before = previous.getCollectionOrNull(cmd.name);
      Map<String, Pending> byCollection = PENDING_BY_WRITER.computeIfAbsent(
          writer, ignored -> new HashMap<>());
      for (Slice slice : cmd.collection.getSlices()) {
        for (Replica replica : slice.getReplicas()) {
          if (before != null && before.getReplica(replica.getName()) != null) continue;
          Pending pending = new Pending(cmd.name, slice.getName(), replica,
                                        replica.getNodeName());
          if (pending.core == null || pending.targetNode == null) continue;
          Pending old = byCollection.get(cmd.name);
          if (old != null && !old.semantic().equals(pending.semantic())) {
            old.ambiguous = true;
            event("UPSTREAM_BATCH_AMBIGUOUS", "collection=" + safe(cmd.name) +
                "\tfirst_replica=" + safe(old.replica) +
                "\tnext_replica=" + safe(pending.replica));
          } else if (old == null) {
            byCollection.put(cmd.name, pending);
          }
          Object oldWriter = WRITER_BY_SEMANTIC.putIfAbsent(pending.semantic(), writer);
          if (oldWriter != null && oldWriter != writer)
            AMBIGUOUS_SEMANTICS.add(pending.semantic());
          event("UPSTREAM_UPDATE_PENDING", "collection=" + safe(cmd.name) +
              "\tshard=" + safe(pending.shard) + "\treplica=" + safe(pending.replica) +
              "\tcore=" + safe(pending.core) +
              "\ttarget_node=" + safe(pending.targetNode) +
              "\twriter_id=" + System.identityHashCode(writer));
        }
      }
    }
  }

  public static synchronized void upstreamWrite(Object writer, Object client, Object reader,
      String collection, String path, DocCollection written)
      throws KeeperException.ConnectionLossException {
    upstreamWriteAtPoint("STATE_SET_DATA_PRE", writer, client, reader,
                         collection, path, written);
  }

  public static synchronized void upstreamWriteDone(Object writer, Object client, Object reader,
      String collection, String path, DocCollection written, int version)
      throws KeeperException.ConnectionLossException {
    try {
      upstreamWriteAtPoint("STATE_SET_DATA_POST", writer, client, reader,
                           collection, path, written, version);
    } finally {
      Map<String, Pending> pending = PENDING_BY_WRITER.get(writer);
      if (pending != null) pending.remove(collection);
    }
  }

  private static void upstreamWriteAtPoint(String operation, Object writer,
      Object client, Object reader, String collection, String path,
      DocCollection written) throws KeeperException.ConnectionLossException {
    upstreamWriteAtPoint(operation, writer, client, reader, collection, path, written, -1);
  }

  private static void upstreamWriteAtPoint(String operation, Object writer,
      Object client, Object reader, String collection, String path,
      DocCollection written, int version) throws KeeperException.ConnectionLossException {
    Map<String, Pending> pendingMap = PENDING_BY_WRITER.get(writer);
    Pending pending = pendingMap == null ? null : pendingMap.get(collection);
    if (pending == null || pending.ambiguous ||
        AMBIGUOUS_SEMANTICS.contains(pending.semantic()) ||
        written.getReplica(pending.replica) == null ||
        !path.equals("/collections/" + collection + "/state.json")) return;
    String node = NODE_BY_CLIENT.get(client);
    String role = node == null ? null : ROLE_BY_NODE.get(node);
    String targetRole = ROLE_BY_NODE.get(pending.targetNode);
    if (node == null || role == null || targetRole == null ||
        !node.equals(NODE_BY_ROLE.get(role)) ||
        !pending.targetNode.equals(NODE_BY_ROLE.get(targetRole)) ||
        READER_BY_CLIENT.get(client) != reader) return;
    if ("STATE_SET_DATA_POST".equals(operation) && version >= 0) {
      String versionKey = collection + "\t" + version;
      CommittedWrite old = WRITES_BY_VERSION.putIfAbsent(
          versionKey, new CommittedWrite(pending, writer, version));
      if (old != null && (old.writer != writer ||
          !old.pending.semantic().equals(pending.semantic()) ||
          !old.pending.targetNode.equals(pending.targetNode)))
        AMBIGUOUS_VERSIONS.add(versionKey);
    }
    String caller = "caller=" + stableCaller();
    String actor = "actor=jetty:" + role;
    String context = "collection=" + safe(collection) + "\tshard=" + safe(pending.shard) +
        "\treplica=" + safe(pending.replica) + "\tcore=" + safe(pending.core);
    String runtime = "\tnode=" + safe(node) +
        "\tclient_id=" + System.identityHashCode(client) +
        "\treader_id=" + System.identityHashCode(reader) +
        "\twriter_id=" + System.identityHashCode(writer) +
        "\tzk_version=" + version +
        "\ttarget_node=" + safe(pending.targetNode) +
        "\ttarget_actor=jetty:" + targetRole +
        "\tthread=" + safe(Thread.currentThread().getName());
    event("UPSTREAM_IO_OBSERVED", operation + "\t" + safe(path) + "\t" +
        caller + "\t" + actor + "\t" + context + runtime);
    int active = nextFault;
    for (int index = 0; index < FAULTS.size(); index++) {
      Fault fault = FAULTS.get(index);
      if (matchesUpstream(fault, operation, path, caller, context)) {
        fault.globalSeen++;
        if (!fault.relative || index == active) fault.seen++;
      }
    }
    if (active >= FAULTS.size()) return;
    Fault fault = FAULTS.get(active);
    if (!matchesUpstream(fault, operation, path, caller, context) ||
        fault.seen != fault.ordinal) return;
    if (fault.relative && !fault.after.equals("after=" + lastApplied))
      throw new IllegalStateException("Upstream fault phase mismatch");
    String details = operation + "\t" + safe(path) +
        "\tordinal=" + (fault.relative ? "@" : "") + fault.ordinal +
        "\trelative_count=" + (fault.relative ? fault.seen : 0) +
        "\tglobal_hit_ordinal=" + fault.globalSeen +
        "\tseed_global=" + fault.seedGlobal +
        "\tprevious_fault_id=" + lastApplied +
        "\tfault_id=F" + active + "\tplan_index=" + active +
        "\t" + caller + "\t" + actor + "\t" + context + runtime;
    event("IO_MATCHED", details);
    event("IO_APPLIED_CONNECTION_LOSS", details);
    lastApplied = "F" + active;
    nextFault++;
    throw new KeeperException.ConnectionLossException();
  }

  /** After a real ZooKeeper state read, bind its version and contents to one committed write. */
  public static synchronized void receiverRead(Object client, Object reader,
      String collection, String path, int version, DocCollection loaded)
      throws KeeperException.ConnectionLossException {
    if (loaded == null || version < 0 || !path.equals(
        "/collections/" + collection + "/state.json")) return;
    String key = collection + "\t" + version;
    CommittedWrite committed = WRITES_BY_VERSION.get(key);
    if (committed == null || AMBIGUOUS_VERSIONS.contains(key)) return;
    Pending pending = committed.pending;
    String node = NODE_BY_CLIENT.get(client);
    String role = node == null ? null : ROLE_BY_NODE.get(node);
    if (node == null || !node.equals(pending.targetNode) || role == null ||
        !node.equals(NODE_BY_ROLE.get(role)) || READER_BY_CLIENT.get(client) != reader ||
        AMBIGUOUS_SEMANTICS.contains(pending.semantic())) return;
    Replica replica = loaded.getReplica(pending.replica);
    if (replica == null || !pending.core.equals(replica.getCoreName()) ||
        !node.equals(replica.getNodeName())) return;
    String caller = "caller=org.apache.solr.common.cloud.ZkStateReader#fetchCollectionState";
    String actor = "actor=jetty:" + role;
    String context = "collection=" + safe(collection) + "\tshard=" +
        safe(pending.shard) + "\treplica=" + safe(pending.replica) +
        "\tcore=" + safe(pending.core);
    String runtime = "\tnode=" + safe(node) +
        "\tclient_id=" + System.identityHashCode(client) +
        "\treader_id=" + System.identityHashCode(reader) +
        "\twriter_id=" + System.identityHashCode(committed.writer) +
        "\ttarget_node=" + safe(pending.targetNode) +
        "\tzk_version=" + version +
        "\tthread=" + safe(Thread.currentThread().getName());
    event("RECEIVER_IO_OBSERVED", "STATE_GET_DATA_POST\t" + safe(path) +
        "\t" + caller + "\t" + actor + "\t" + context + runtime);
    int active = nextFault;
    for (int index = 0; index < FAULTS.size(); index++) {
      Fault fault = FAULTS.get(index);
      if (matchesReceiver(fault, path, caller, context)) {
        fault.globalSeen++;
        if (!fault.relative || index == active) fault.seen++;
      }
    }
    if (active >= FAULTS.size()) return;
    Fault fault = FAULTS.get(active);
    if (!matchesReceiver(fault, path, caller, context) ||
        fault.seen != fault.ordinal) return;
    if (fault.relative && !fault.after.equals("after=" + lastApplied))
      throw new IllegalStateException("Receiver fault phase mismatch");
    String details = "STATE_GET_DATA_POST\t" + safe(path) +
        "\tordinal=" + (fault.relative ? "@" : "") + fault.ordinal +
        "\trelative_count=" + (fault.relative ? fault.seen : 0) +
        "\tglobal_hit_ordinal=" + fault.globalSeen +
        "\tseed_global=" + fault.seedGlobal +
        "\tprevious_fault_id=" + lastApplied +
        "\tfault_id=F" + active + "\tplan_index=" + active +
        "\t" + caller + "\t" + actor + "\t" + context + runtime;
    event("IO_MATCHED", details);
    event("IO_APPLIED_CONNECTION_LOSS", details);
    lastApplied = "F" + active;
    nextFault++;
    throw new KeeperException.ConnectionLossException();
  }

  private static boolean matchesReceiver(Fault fault, String path, String caller,
      String context) {
    return fault.actor.equals("actor=receiver_state_read_for_replica") &&
        fault.operation.equals("STATE_GET_DATA_POST") &&
        fault.path.equals(path) && fault.caller.equals(caller) &&
        context.equals(fault.collection + "\t" + fault.shard + "\t" +
            fault.replica + "\t" + fault.core);
  }

  private static boolean matchesUpstream(Fault fault, String operation, String path,
      String caller, String context) {
    return fault.actor.equals("actor=overseer_writer_for_replica") &&
        operation.equals(fault.operation) && path.equals(fault.path) &&
        caller.equals(fault.caller) &&
        context.equals(fault.collection + "\t" + fault.shard + "\t" +
                       fault.replica + "\t" + fault.core);
  }

  public static synchronized void io(String operation, String path, Object receiver)
      throws KeeperException.ConnectionLossException {
    String node = NODE_BY_CLIENT.get(receiver);
    String role = node == null ? null : ROLE_BY_NODE.get(node);
    Context ctx = REGISTERS.get().peek();
    if (ctx != null && (ctx.client != receiver ||
        READER_BY_CLIENT.get(receiver) != ctx.reader || !ctx.node.equals(node))) ctx = null;
    String caller = "caller=" + stableCaller();
    String actor = "actor=" + (role == null ? "unbound" : "jetty:" + role);
    String identity = operation + "\t" + safe(path);
    String context = contextFields(ctx);
    String runtime = "\tnode=" + safe(node) + "\tclient_id=" +
        System.identityHashCode(receiver) + "\treader_id=" +
        (READER_BY_CLIENT.containsKey(receiver)
            ? System.identityHashCode(READER_BY_CLIENT.get(receiver)) : -1) +
        "\tthread=" + safe(Thread.currentThread().getName());
    event("IO_OBSERVED", identity + "\t" + caller + "\t" + actor + "\t" + context + runtime);
    int active = nextFault;
    for (int index = 0; index < FAULTS.size(); index++) {
      Fault fault = FAULTS.get(index);
      if (matches(fault, operation, path, caller, actor, context, ctx)) {
        fault.globalSeen++;
        if (!fault.relative || index == active) fault.seen++;
      }
    }
    if (active >= FAULTS.size()) return;
    Fault fault = FAULTS.get(active);
    if (!matches(fault, operation, path, caller, actor, context, ctx) ||
        fault.seen != fault.ordinal) return;
    if (fault.relative && !fault.after.equals("after=" + lastApplied))
      throw new IllegalStateException("Fault phase mismatch");
    String details = identity + "\tordinal=" + (fault.relative ? "@" : "") +
        fault.ordinal + "\trelative_count=" + (fault.relative ? fault.seen : 0) +
        "\tglobal_hit_ordinal=" + fault.globalSeen + "\tseed_global=" +
        fault.seedGlobal + "\tprevious_fault_id=" + lastApplied +
        "\tfault_id=F" + active + "\tplan_index=" + active +
        "\t" + caller + "\t" + actor + "\t" + context + runtime;
    event("IO_MATCHED", details);
    event("IO_APPLIED_CONNECTION_LOSS", details);
    lastApplied = "F" + active;
    nextFault++;
    throw new KeeperException.ConnectionLossException();
  }
  private static boolean matches(Fault f, String operation, String path, String caller,
                                 String actor, String context, Context ctx) {
    if (ctx == null || !actor.matches("actor=jetty:node[1-9][0-9]*") ||
        !ctx.node.equals(NODE_BY_ROLE.get(actor.substring("actor=jetty:".length()))) ||
        !ctx.node.equals(NODE_BY_CLIENT.get(ctx.client)) ||
        READER_BY_CLIENT.get(ctx.client) != ctx.reader ||
        REGISTER_BY_REPLICA.get(ctx.collection + "\t" + ctx.shard + "\t" +
                                ctx.replica + "\t" + ctx.core).client != ctx.client)
      return false;
    return operation.equals(f.operation) && f.path.equals(path) &&
        f.caller.equals(caller) && f.actor.equals("actor=jetty:host_of_replica") &&
        context.equals(f.collection + "\t" + f.shard + "\t" + f.replica + "\t" + f.core);
  }
  public static synchronized void targetCheck(boolean missing, String collection, String shard,
      String replica, String core, Object client, Object reader, String node) {
    Context ctx = REGISTERS.get().peek();
    if (ctx == null || ctx.client != client || ctx.reader != reader ||
        !ctx.node.equals(node) || !ctx.collection.equals(collection) ||
        !ctx.shard.equals(shard) || !ctx.replica.equals(replica) ||
        !ctx.core.equals(core) || !node.equals(NODE_BY_CLIENT.get(client)) ||
        READER_BY_CLIENT.get(client) != reader ||
        REGISTER_BY_REPLICA.get(collection + "\t" + shard + "\t" + replica +
                                "\t" + core).client != client)
      throw new IllegalStateException("Target guard context differs from register I/O context");
    String role = ROLE_BY_NODE.get(node);
    if (role == null || !node.equals(NODE_BY_ROLE.get(role)))
      throw new IllegalStateException("Target guard has no unique Jetty role");
    String identity = contextFields(ctx) + "\tactor=jetty:" + role +
        "\tnode=" + safe(node) + "\tclient_id=" + System.identityHashCode(client) +
        "\treader_id=" + System.identityHashCode(reader) +
        "\tthread=" + safe(Thread.currentThread().getName()) +
        "\tlast_fault=" + lastApplied;
    event("TARGET_CHECK", (missing ? "missing" : "present") + "\tSOLR-05\t" + identity);
    if (missing) event("TARGET_EXCEPTION", "SOLR-05\t" + identity);
  }
}
