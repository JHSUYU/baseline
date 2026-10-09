package research.solrsubshardv2;

import java.io.BufferedWriter;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.Properties;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import org.apache.solr.common.SolrException;
import org.apache.solr.common.cloud.DocRouter;
import org.apache.solr.common.cloud.Slice;
import org.apache.solr.common.cloud.SolrZkClient;
import org.apache.solr.common.cloud.SolrZooKeeper;
import org.apache.zookeeper.KeeperException;
import org.apache.zookeeper.ZooKeeper;
import org.slf4j.MDC;

/** Logical subshard/replica identity and physical Jetty node recorded separately. */
public final class Probe {
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final ConcurrentHashMap<String, AtomicInteger> ORDINALS =
      new ConcurrentHashMap<>();
  private static final AtomicInteger NEXT_STEP = new AtomicInteger(1);
  private static final ThreadLocal<String> TARGET_SOURCE = new ThreadLocal<>();
  private static final ThreadLocal<String> TARGET_PHYSICAL = new ThreadLocal<>();
  private static final ThreadLocal<String> TARGET_PHASE = new ThreadLocal<>();
  private static final ThreadLocal<Object> TARGET_CLIENT = new ThreadLocal<>();
  private static final ThreadLocal<String> CHILD_RANGE = new ThreadLocal<>();
  private static final ThreadLocal<String> PARENT_RANGE = new ThreadLocal<>();
  private static final Map<Object, Binding> CLIENTS =
      Collections.synchronizedMap(new IdentityHashMap<Object, Binding>());
  private static final Map<Object, SessionTracker> SESSIONS =
      Collections.synchronizedMap(new IdentityHashMap<Object, SessionTracker>());
  private static final Map<Object, FixtureSession> FIXTURE_SESSIONS =
      Collections.synchronizedMap(new IdentityHashMap<Object, FixtureSession>());
  private static final ConcurrentHashMap<String, String> NODE_ACTORS =
      new ConcurrentHashMap<>();
  private static final Properties FAULT = new Properties();
  private static BufferedWriter output;
  private static int plannedSteps;

  private static final class Binding {
    final String actorKey;
    final String nodeName;
    final String solrHome;

    Binding(String actorKey, String nodeName, String solrHome) {
      this.actorKey = actorKey;
      this.nodeName = nodeName;
      this.solrHome = solrHome;
    }
  }

  private static final class SessionTracker {
    Object handle;
    int generation;
  }

  private static final class FixtureSession {
    Object handle;
    long sessionId;
    String endpoint;
    boolean connected;
    FixtureSession(Object handle, long sessionId, String endpoint, boolean connected) {
      this.handle = handle;
      this.sessionId = sessionId;
      this.endpoint = endpoint;
      this.connected = connected;
    }
  }

  private static final class SessionEvidence {
    final int clientIdentity;
    final int handleIdentity;
    final int generation;
    final long sessionId;
    final String endpoint;
    final String state;
    final boolean eligible;
    SessionEvidence(Object client, Object handle, int generation, long sessionId,
                    String endpoint, String state, boolean eligible) {
      this.clientIdentity = client == null ? 0 : System.identityHashCode(client);
      this.handleIdentity = handle == null ? 0 : System.identityHashCode(handle);
      this.generation = generation;
      this.sessionId = sessionId;
      this.endpoint = endpoint;
      this.state = state;
      this.eligible = eligible;
    }
  }

  /** Smoke-only session replacement. Production ignores this map unless explicitly enabled. */
  public static void bindFixtureSession(Object client, Object handle, long sessionId,
                                        String endpoint, boolean connected) {
    if (!Boolean.getBoolean("solrsubshard.fixture.identity"))
      throw new IllegalStateException("fixture identity disabled");
    FIXTURE_SESSIONS.put(client, new FixtureSession(handle, sessionId, endpoint, connected));
  }

  private static SessionEvidence session(Object client) {
    Object handle = null;
    long sessionId = 0;
    String endpoint = "";
    String state = "UNBOUND";
    boolean connected = false;
    if (client instanceof SolrZkClient) {
      SolrZkClient zk = (SolrZkClient) client;
      SolrZooKeeper keeper = zk.getSolrZooKeeper();
      handle = keeper;
      endpoint = zk.getZkServerAddress();
      if (keeper != null) {
        sessionId = keeper.getSessionId();
        ZooKeeper.States current = keeper.getState();
        state = String.valueOf(current);
        connected = current == ZooKeeper.States.CONNECTED;
      }
    } else if (Boolean.getBoolean("solrsubshard.fixture.identity")) {
      FixtureSession fixture = FIXTURE_SESSIONS.get(client);
      if (fixture != null) {
        handle = fixture.handle;
        sessionId = fixture.sessionId;
        endpoint = fixture.endpoint;
        state = fixture.connected ? "CONNECTED" : "DISCONNECTED";
        connected = fixture.connected;
      }
    }
    int generation = 0;
    if (handle != null) {
      synchronized (SESSIONS) {
        SessionTracker tracker = SESSIONS.get(client);
        if (tracker == null) {
          tracker = new SessionTracker();
          SESSIONS.put(client, tracker);
        }
        if (tracker.handle != handle) {
          tracker.handle = handle;
          tracker.generation++;
        }
        generation = tracker.generation;
      }
    }
    return new SessionEvidence(client, handle, generation, sessionId,
        endpoint, state, connected && handle != null && sessionId > 0);
  }

  private Probe() {}

  public static synchronized void initialize() {
    if (output != null) return;
    String trace = System.getProperty("solrsubshard.trace.file");
    if (trace == null || trace.isEmpty())
      throw new IllegalArgumentException("solrsubshard.trace.file required");
    try {
      Path path = Paths.get(trace);
      Files.createDirectories(path.toAbsolutePath().getParent());
      output = Files.newBufferedWriter(path, StandardCharsets.UTF_8,
          StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
      String plan = System.getProperty("solrsubshard.fault.plan", "");
      if (!plan.isEmpty()) {
        try (InputStream input = Files.newInputStream(Paths.get(plan))) {
          FAULT.load(input);
        }
        plannedSteps = Integer.parseInt(FAULT.getProperty("count", "1"));
        if (plannedSteps < 1 || plannedSteps > 10)
          throw new IllegalArgumentException("fault plan count must be 1..10");
        for (int step = 1; step <= plannedSteps; step++) {
          String prefix = "step." + step + ".";
          for (String field : new String[]{"marker", "siteId", "sourceKey", "actorKey", "resource", "hitOrdinal", "sessionGeneration"}) {
            if (FAULT.getProperty(prefix + field) == null)
              throw new IllegalArgumentException("missing fault field " + prefix + field);
          }
        }
      }
      Runtime.getRuntime().addShutdownHook(new Thread(Probe::close, "solrsubshard-probe-close"));
    } catch (IOException failure) {
      throw new IllegalStateException("SOLR subshard trace init failed", failure);
    }
  }

  public static synchronized void close() {
    if (output == null) return;
    emit("SUMMARY", "", "", "", "", "", "", 0, false,
        "applied=" + (NEXT_STEP.get() - 1) + "/" + plannedSteps);
    try { output.flush(); output.close(); }
    catch (IOException failure) { failure.printStackTrace(System.err); }
    output = null;
  }

  private static String quote(String value) {
    if (value == null) return "null";
    StringBuilder result = new StringBuilder(value.length() + 2).append('"');
    for (char character : value.toCharArray()) {
      if (character == '"' || character == '\\') result.append('\\').append(character);
      else if (character == '\n') result.append("\\n");
      else if (character == '\r') result.append("\\r");
      else if (character == '\t') result.append("\\t");
      else if (character < 0x20) result.append(String.format("\\u%04x", (int) character));
      else result.append(character);
    }
    return result.append('"').toString();
  }

  /** The original cluster test places each server under control/ or shardN/. */
  public static void bindServerClient(Object client, String nodeName, String solrHome) {
    if (client == null || nodeName == null || solrHome == null)
      throw new IllegalStateException("incomplete SolrZkClient server binding");
    String normalized = solrHome.replace('\\', '/');
    int separator = normalized.lastIndexOf('/');
    String slot = normalized.substring(separator + 1);
    String actor = ("control".equals(slot) || slot.matches("shard[0-9]+")) ?
        "JETTY/" + slot : "UNBOUND:SOLR_HOME:" + slot;
    Binding binding = new Binding(actor, nodeName, solrHome);
    synchronized (CLIENTS) {
      Binding old = CLIENTS.get(client);
      if (old != null && (!old.actorKey.equals(actor) || !old.nodeName.equals(nodeName)))
        throw new IllegalStateException("SolrZkClient rebound to a different actor");
      CLIENTS.put(client, binding);
    }
    if (!actor.startsWith("UNBOUND:")) {
      String oldActor = NODE_ACTORS.putIfAbsent(nodeName, actor);
      if (oldActor != null && !oldActor.equals(actor))
        throw new IllegalStateException("Solr physical node mapped to two test roles");
    }
    emit("CLIENT_BIND", "SOLRZKCLIENT_ACTOR", "ZkController.<init>", "", actor,
        nodeName, solrHome, 0, false,
        "clientIdentity=" + System.identityHashCode(client));
  }

  private static synchronized void emit(String event, String marker, String site,
                                        String source, String actorKey,
                                        String physicalNode,
                                        String resource, int ordinal, boolean applied,
                                        String detail) {
    emit(event, marker, site, source, actorKey, physicalNode, resource,
        ordinal, applied, detail, null);
  }

  private static synchronized void emit(String event, String marker, String site,
                                        String source, String actorKey,
                                        String physicalNode,
                                        String resource, int ordinal, boolean applied,
                                        String detail, SessionEvidence session) {
    if (output == null) return;
    String row = "{\"event\":" + quote(event)
        + ",\"seq\":" + SEQUENCE.incrementAndGet()
        + ",\"timeNs\":" + System.nanoTime()
        + ",\"threadId\":" + Thread.currentThread().getId()
        + ",\"marker\":" + quote(marker)
        + ",\"siteId\":" + quote(site)
        + ",\"sourceKey\":" + quote(source)
        + ",\"actorKey\":" + quote(actorKey)
        + ",\"physicalNode\":" + quote(physicalNode)
        + ",\"resource\":" + quote(resource)
        + ",\"hitOrdinal\":" + ordinal
        + ",\"applied\":" + applied
        + ",\"zkClientIdentity\":" + (session == null ? 0 : session.clientIdentity)
        + ",\"zkHandleIdentity\":" + (session == null ? 0 : session.handleIdentity)
        + ",\"sessionGeneration\":" + (session == null ? 0 : session.generation)
        + ",\"zkSessionId\":" + (session == null ? 0 : session.sessionId)
        + ",\"zkEndpoint\":" + quote(session == null ? "" : session.endpoint)
        + ",\"zkState\":" + quote(session == null ? "" : session.state)
        + ",\"sessionEligible\":" + (session != null && session.eligible)
        + ",\"detail\":" + quote(detail) + "}";
    try { output.write(row); output.newLine(); }
    catch (IOException failure) { throw new IllegalStateException("trace write failed", failure); }
  }

  private static String targetActor() {
    Object client = TARGET_CLIENT.get();
    Binding binding = CLIENTS.get(client);
    return binding != null && binding.nodeName.equals(TARGET_PHYSICAL.get()) ?
        binding.actorKey : "UNBOUND:TARGET_CLIENT";
  }

  public static void targetEnter(String collection, String shard, String replica,
                                 String physicalNode, Object client, Object phase) {
    String source = collection == null || shard == null || replica == null ?
        "UNRESOLVED:SUBSHARD_REPLICA" :
        "SOLR/SUBSHARD/" + collection + "/" + shard + "/" + replica;
    TARGET_SOURCE.set(source);
    TARGET_PHYSICAL.set(physicalNode);
    TARGET_CLIENT.set(client);
    TARGET_PHASE.set(String.valueOf(phase));
    CHILD_RANGE.remove();
    PARENT_RANGE.remove();
    emit("TARGET_ENTER", "SOLR36_37:DEFENSIVE_CHECKS",
        "DistributedZkUpdateProcessor.doDefensiveChecks", source,
        targetActor(), physicalNode,
        collection, 0, false, "phase=" + phase, session(client));
  }

  public static void guard36(Slice.State state) {
    emit("TARGET_CHECK", "SOLR36:ACTIVE_SUBSHARD_GUARD",
        "DistributedZkUpdateProcessor.java:986", TARGET_SOURCE.get(),
        targetActor(),
        TARGET_PHYSICAL.get(), "", 0, false,
        "state=" + state + ";phase=" + TARGET_PHASE.get(), session(TARGET_CLIENT.get()));
  }

  public static void rangeOperands(DocRouter.Range child, DocRouter.Range parent) {
    CHILD_RANGE.set(String.valueOf(child));
    PARENT_RANGE.set(String.valueOf(parent));
  }

  public static void guard37(boolean isSubset) {
    emit("TARGET_CHECK", "SOLR37:CHILD_RANGE_SUBSET_GUARD",
        "DistributedZkUpdateProcessor.java:994", TARGET_SOURCE.get(),
        targetActor(),
        TARGET_PHYSICAL.get(), "", 0, false,
        "child=" + CHILD_RANGE.get() + ";parent=" + PARENT_RANGE.get()
            + ";subset=" + isSubset + ";phase=" + TARGET_PHASE.get(), session(TARGET_CLIENT.get()));
  }

  public static void targetThrow(Throwable failure, int line) {
    if (!(failure instanceof SolrException)) return;
    String message = failure.getMessage();
    String marker;
    if (line == 987 && message != null && message.equals(
        "Request says it is coming from parent shard leader but we are in active state"))
      marker = "SOLR36:ACTIVE_SUBSHARD_THROW";
    else if (line == 995 && message != null && message.equals(
        "Request says it is coming from parent shard leader but parent hash range is not superset of my range"))
      marker = "SOLR37:CHILD_RANGE_THROW";
    else return;
    emit("TARGET_THROW", marker, "DistributedZkUpdateProcessor.java:" + line,
        TARGET_SOURCE.get(),
        targetActor(),
        TARGET_PHYSICAL.get(), "", 0, false,
        failure.getClass().getName() + ": " + message, session(TARGET_CLIENT.get()));
  }

  private static String mdcValue(String name, String prefix) {
    String value = MDC.get(name);
    return value != null && value.startsWith(prefix) ? value.substring(prefix.length()) : null;
  }

  private static String collectionSource(String path) {
    if (path.startsWith("/collections/")) {
      String suffix = path.substring("/collections/".length());
      return "SOLR/COLLECTION/" + suffix.split("/", 2)[0];
    }
    return "UNRESOLVED:ZK:" + path;
  }

  private static boolean apply(String marker, String site, String source,
                               String actorKey, String resource, int ordinal,
                               SessionEvidence session) {
    int step = NEXT_STEP.get();
    if (step > plannedSteps || !session.eligible) return false;
    String prefix = "step." + step + ".";
    boolean exact = marker.equals(FAULT.getProperty(prefix + "marker"))
        && site.equals(FAULT.getProperty(prefix + "siteId"))
        && source.equals(FAULT.getProperty(prefix + "sourceKey"))
        && actorKey.equals(FAULT.getProperty(prefix + "actorKey"))
        && resource.equals(FAULT.getProperty(prefix + "resource"))
        && ordinal == Integer.parseInt(FAULT.getProperty(prefix + "hitOrdinal"))
        && session.generation == Integer.parseInt(FAULT.getProperty(prefix + "sessionGeneration"));
    if (exact && (source.startsWith("UNRESOLVED:") || site.startsWith("UNRESOLVED:")
        || actorKey.startsWith("UNBOUND:")))
      throw new IllegalStateException("refuse fault on unresolved I/O identity");
    return exact && NEXT_STEP.compareAndSet(step, step + 1);
  }

  /** Observe a real ZooKeeper operation inside Solr's retry callable. */
  public static void nativeEntry(Object client, String path, String api) throws KeeperException {
    if (path == null) return;
    Binding binding = CLIENTS.get(client);
    SessionEvidence session = session(client);
    String actorKey = binding == null ? "UNBOUND:ZK_CLIENT" : binding.actorKey;
    String physicalNode = binding == null ? "" : binding.nodeName;
    StackTraceElement[] stack = Thread.currentThread().getStackTrace();
    StackTraceElement caller = null;
    boolean inDefensiveCheck = false;
    for (StackTraceElement frame : stack) {
      if (frame.getClassName().equals("org.apache.solr.update.processor.DistributedZkUpdateProcessor")
          && frame.getMethodName().equals("doDefensiveChecks")) inDefensiveCheck = true;
      if (caller == null && frame.getClassName().startsWith("org.apache.solr.")
          && !frame.getClassName().equals("org.apache.solr.common.cloud.SolrZkClient")
          && !frame.getClassName().equals("org.apache.solr.common.cloud.ZkCmdExecutor"))
        caller = frame;
    }
    String collection = mdcValue("collection", "c:");
    String shard = mdcValue("shard", "s:");
    String replica = mdcValue("replica", "r:");
    String source = inDefensiveCheck && TARGET_SOURCE.get() != null ?
        TARGET_SOURCE.get() :
        collection != null && shard != null && replica != null ?
            "SOLR/REPLICA/" + collection + "/" + shard + "/" + replica :
            collectionSource(path);
    String site = caller == null ? "UNRESOLVED:CALLER" : caller.getClassName()
        + "." + caller.getMethodName() + "#L" + caller.getLineNumber()
        + "->SolrZkClient." + api;
    int end = api.indexOf('$', "lambda$".length());
    if (!api.startsWith("lambda$") || end < 0)
      throw new IllegalArgumentException("unexpected retry method " + api);
    String marker = "FAULT:ZK_NATIVE:" + api.substring("lambda$".length(), end);
    String key = marker + '\u0000' + site + '\u0000' + source
        + '\u0000' + actorKey + '\u0000' + session.generation + '\u0000' + path;
    int ordinal = ORDINALS.computeIfAbsent(key, unused -> new AtomicInteger())
        .incrementAndGet();
    boolean matched = apply(marker, site, source, actorKey, path, ordinal, session);
    emit("IO_OBSERVED", marker, site, source, actorKey, physicalNode,
        path, ordinal, matched, "path=" + path
            + ";clientIdentity=" + System.identityHashCode(client)
            + ";mdcNode=" + MDC.get("node_name")
            + ";mdcCore=" + MDC.get("core")
            + ";targetPhysical=" + TARGET_PHYSICAL.get()
            + ";solrHome=" + (binding == null ? "" : binding.solrHome), session);
    if (matched) throw KeeperException.create(KeeperException.Code.CONNECTIONLOSS, path);
  }
}
