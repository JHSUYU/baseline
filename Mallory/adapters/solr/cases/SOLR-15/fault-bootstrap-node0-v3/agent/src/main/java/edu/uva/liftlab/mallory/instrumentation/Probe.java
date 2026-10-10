package edu.uva.liftlab.mallory.instrumentation;

import com.google.gson.Gson;
import java.io.BufferedWriter;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStreamWriter;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Deque;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Callable;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/** Public hooks for instrumented methods and small system-specific adapters. */
public final class Probe {
  private static volatile Sink sink;
  private static volatile FaultPlan plan = new FaultPlan();
  private static final ThreadLocal<Context> CONTEXT = new ThreadLocal<Context>() {
    @Override protected Context initialValue() { return new Context(); }
  };
  private static final ThreadLocal<Solr15ParentSelector> SOLR15_PARENT =
      new ThreadLocal<Solr15ParentSelector>() {
        @Override protected Solr15ParentSelector initialValue() {
          return new Solr15ParentSelector();
        }
      };
  private static final ConcurrentHashMap<String, AtomicLong> REGION_COUNTS =
      new ConcurrentHashMap<String, AtomicLong>();
  private static final ConcurrentHashMap<String, AtomicLong> DOOR_HITS =
      new ConcurrentHashMap<String, AtomicLong>();
  private static final ConcurrentHashMap<String, AtomicLong> DOOR_ORDINALS =
      new ConcurrentHashMap<String, AtomicLong>();
  private static final ConcurrentHashMap<CoverageKey, Set<Integer>> COVERAGE =
      new ConcurrentHashMap<CoverageKey, Set<Integer>>();
  private static final ConcurrentHashMap<String, Integer> COVERAGE_IDS =
      new ConcurrentHashMap<String, Integer>();
  private static final Set<Integer> EMITTED_COVERAGE_DEFS =
      ConcurrentHashMap.<Integer>newKeySet();
  private static final AtomicInteger COVERAGE_ID_SEQUENCE = new AtomicInteger();
  private static boolean coverageShutdownHookInstalled;
  private static final AtomicLong TASK_SEQUENCE = new AtomicLong();
  private static final Object STATE_LOCK = new Object();
  private static final Object NODE_LOCK = new Object();
  private static final IdentityHashMap<Object, NodeIdentity> NODE_ALIASES =
      new IdentityHashMap<Object, NodeIdentity>();
  private static final Map<String, Integer> NODE_EPOCHS = new HashMap<String, Integer>();
  private static final IdentityHashMap<Object, Long> OBJECT_IDS = new IdentityHashMap<Object, Long>();
  private static final Map<String, Long> STATE_VERSIONS = new HashMap<String, Long>();
  private static long nextObjectId;

  private Probe() { }

  static synchronized void install(String runId, File events, FaultPlan faults) throws IOException {
    if (sink != null) {
      flushCoverage();
      sink.close();
    }
    COVERAGE.clear();
    COVERAGE_IDS.clear();
    EMITTED_COVERAGE_DEFS.clear();
    COVERAGE_ID_SEQUENCE.set(0);
    sink = new Sink(runId, events);
    if (!coverageShutdownHookInstalled) {
      Runtime.getRuntime().addShutdownHook(new Thread(new Runnable() {
        @Override public void run() { flushCoverage(); }
      }, "mallory-coverage-flush"));
      coverageShutdownHookInstalled = true;
    }
    plan = faults == null ? new FaultPlan() : faults;
    REGION_COUNTS.clear();
    DOOR_HITS.clear();
    DOOR_ORDINALS.clear();
    TASK_SEQUENCE.set(0);
    synchronized (STATE_LOCK) {
      OBJECT_IDS.clear();
      STATE_VERSIONS.clear();
      nextObjectId = 0;
    }
    synchronized (NODE_LOCK) {
      NODE_ALIASES.clear();
      NODE_EPOCHS.clear();
    }
    CONTEXT.remove();
    SOLR15_PARENT.remove();
  }

  static void configureLimits(long maxEvents, long maxBytes) {
    Sink current = sink;
    if (current != null) current.setLimits(maxEvents, maxBytes);
  }

  public static void setNode(String node, int epoch) {
    Context context = CONTEXT.get();
    String next = node == null ? "unknown" : node;
    if (context.frames.isEmpty() && (!next.equals(context.node) || epoch != context.epoch))
      context.unscopedSegment++;
    context.node = next;
    context.epoch = epoch;
  }

  public static String currentNode() { return CONTEXT.get().node; }

  public static int currentEpoch() { return CONTEXT.get().epoch; }

  public static NodeScope withNode(String node, int epoch) {
    Context context = CONTEXT.get();
    NodeScope scope = new NodeScope(context.node, context.epoch);
    setNode(node, epoch);
    return scope;
  }

  /** Register an identity only when a system lifecycle hook knows the receiver's logical owner. */
  public static void registerNode(Object receiver, String node, int epoch) {
    if (receiver == null || node == null || node.isEmpty() || epoch < 0)
      throw new IllegalArgumentException("A concrete receiver, node, and nonnegative epoch are required");
    synchronized (NODE_LOCK) {
      NodeIdentity previous = NODE_ALIASES.get(receiver);
      if (previous != null && (!previous.node.equals(node) || previous.epoch != epoch))
        throw new IllegalStateException("Conflicting logical node registration for one receiver");
      NODE_ALIASES.put(receiver, new NodeIdentity(node, epoch));
    }
  }

  /** Preserve a named node across an explicit queued-object handoff. */
  public static void registerCurrentNode(Object receiver) {
    Context context = CONTEXT.get();
    if ("unknown".equals(context.node) || context.node == null)
      throw new IllegalStateException("Cannot register an unbound current node");
    registerNode(receiver, context.node, context.epoch);
  }

  public static NodeScope withRegisteredNode(Object receiver) {
    NodeIdentity identity;
    synchronized (NODE_LOCK) { identity = NODE_ALIASES.get(receiver); }
    if (identity == null) {
      event("NODE_IDENTITY_GAP", "registered-receiver", fields("reason", "unregistered_receiver"));
      return withNode("unknown", 0);
    }
    return withNode(identity.node, identity.epoch);
  }

  /** A selectable binding for classes with a real instance field identifying their node. */
  public static void enterNodeFromField(Object receiver, String fieldName, String prefix) {
    enterNodeFromMember(receiver, fieldName, prefix, false);
  }

  /** Bind from a selected zero-argument numeric getter on the actual receiver. */
  public static void enterNodeFromGetter(Object receiver, String getterName, String prefix) {
    enterNodeFromMember(receiver, getterName, prefix, true);
  }

  private static void enterNodeFromMember(Object receiver, String memberName, String prefix,
                                          boolean getter) {
    Context context = CONTEXT.get();
    context.nodeScopes.push(new NodeIdentity(context.node, context.epoch));
    if (receiver == null || memberName == null) {
      setNode("unknown", 0);
      event("NODE_IDENTITY_GAP", "node-member", fields("reason", "missing_receiver_or_member"));
      return;
    }
    synchronized (NODE_LOCK) {
      NodeIdentity identity = NODE_ALIASES.get(receiver);
      if (identity == null) {
        try {
          Object value;
          if (getter) {
            java.lang.reflect.Method method = lookupGetter(receiver.getClass(), memberName);
            method.setAccessible(true);
            value = method.invoke(receiver);
          } else {
            Field field = lookupField(receiver.getClass(), memberName);
            field.setAccessible(true);
            value = field.get(receiver);
          }
          if (!(value instanceof Number)) throw new IllegalArgumentException("node ID member is not numeric");
          String node = (prefix == null ? "" : prefix) + value;
          Integer next = NODE_EPOCHS.get(node);
          int epoch = next == null ? 0 : next.intValue();
          NODE_EPOCHS.put(node, epoch + 1);
          identity = new NodeIdentity(node, epoch);
          NODE_ALIASES.put(receiver, identity);
        } catch (ReflectiveOperationException | RuntimeException failure) {
          setNode("unknown", 0);
          event("NODE_IDENTITY_GAP", "node-member", fields("reason", failure.getClass().getName()));
          return;
        }
      }
      setNode(identity.node, identity.epoch);
    }
  }

  public static void exitNode() {
    Context context = CONTEXT.get();
    if (context.nodeScopes.isEmpty()) return;
    NodeIdentity previous = context.nodeScopes.pop();
    setNode(previous.node, previous.epoch);
  }

  private static Field lookupField(Class<?> type, String name) throws NoSuchFieldException {
    for (Class<?> cursor = type; cursor != null; cursor = cursor.getSuperclass()) {
      try { return cursor.getDeclaredField(name); }
      catch (NoSuchFieldException ignored) { }
    }
    throw new NoSuchFieldException(name);
  }

  private static java.lang.reflect.Method lookupGetter(Class<?> type, String name)
      throws NoSuchMethodException {
    for (Class<?> cursor = type; cursor != null; cursor = cursor.getSuperclass()) {
      try { return cursor.getDeclaredMethod(name); }
      catch (NoSuchMethodException ignored) { }
    }
    throw new NoSuchMethodException(name);
  }

  public static final class NodeScope implements AutoCloseable {
    private final String previousNode;
    private final int previousEpoch;
    private NodeScope(String node, int epoch) { previousNode = node; previousEpoch = epoch; }
    @Override public void close() { setNode(previousNode, previousEpoch); }
  }

  public static String captureContext() {
    Context context = CONTEXT.get();
    return context.frames.isEmpty() ? context.causalContext : context.frames.peek().occurrence;
  }

  /**
   * Enter an already observed handoff's causal context without recording a second handoff.
   * The caller must supply the exact correlation token from the corresponding RECV or
   * TASK_CLAIM event. A root region entered in this scope records that token as its parent.
   * Logical node and epoch are deliberately left to the caller's explicit actor binding.
   */
  public static ContextScope withCausalContext(String token) {
    if (token == null || token.trim().isEmpty())
      throw new IllegalArgumentException("A concrete causal correlation token is required");
    Context context = CONTEXT.get();
    ContextScope scope = new ContextScope(context.causalContext);
    setCausalContext(context, token);
    return scope;
  }

  public static void taskSubmit(String token, String site) {
    event("TASK_SUBMIT", site, fields("correlation", token, "parent_id", captureContext()));
  }

  public static Runnable wrapRunnable(final Runnable task, final String site) {
    if (task == null) return null;
    final Context context = CONTEXT.get();
    final String node = context.node;
    final int epoch = context.epoch;
    final String token = newTaskToken();
    taskSubmit(token, site);
    return new Runnable() {
      @Override public void run() {
        try (NodeScope ignoredNode = withNode(node, epoch);
             ContextScope ignoredContext = taskClaim(token, site)) {
          task.run();
        }
      }
    };
  }

  public static <T> Callable<T> wrapCallable(final Callable<T> task, final String site) {
    if (task == null) return null;
    final Context context = CONTEXT.get();
    final String node = context.node;
    final int epoch = context.epoch;
    final String token = newTaskToken();
    taskSubmit(token, site);
    return new Callable<T>() {
      @Override public T call() throws Exception {
        try (NodeScope ignoredNode = withNode(node, epoch);
             ContextScope ignoredContext = taskClaim(token, site)) {
          return task.call();
        }
      }
    };
  }

  public static String newTaskToken() {
    Sink current = sink;
    return (current == null ? "run" : current.runId) + ":task:" + TASK_SEQUENCE.incrementAndGet();
  }

  public static ContextScope taskClaim(String token, String site) {
    Context context = CONTEXT.get();
    ContextScope scope = new ContextScope(context.causalContext);
    setCausalContext(context, token == null ? "lost" : token);
    event("TASK_CLAIM", site, fields("correlation", token, "parent_id", token));
    return scope;
  }

  /** Observe a synchronous completion in the current region without changing its context. */
  public static void taskObserve(String token, String site) {
    event("TASK_CLAIM", site, fields("correlation", token, "parent_id", token));
  }

  public static final class ContextScope implements AutoCloseable {
    private final String previous;
    private ContextScope(String previous) { this.previous = previous; }
    @Override public void close() { setCausalContext(CONTEXT.get(), previous); }
  }

  private static void setCausalContext(Context context, String next) {
    if (context.frames.isEmpty() && !next.equals(context.causalContext))
      context.unscopedSegment++;
    context.causalContext = next;
  }

  public static void send(String transport, String correlation, String port, String site) {
    event("SEND", site, fields("transport", transport, "correlation", correlation,
        "port", port));
  }

  public static void receive(String transport, String correlation, String port, String site) {
    event("RECV", site, fields("transport", transport, "correlation", correlation,
        "port", port));
  }

  /** For a request handler, restores the previous context when the handler exits. */
  public static ContextScope receiveScope(String transport, String correlation, String port, String site) {
    Context context = CONTEXT.get();
    ContextScope scope = new ContextScope(context.causalContext);
    if (correlation != null) setCausalContext(context, correlation);
    event("RECV", site, fields("transport", transport, "correlation", correlation,
        "port", port));
    return scope;
  }

  public static void regionEnter(String site) {
    Context context = CONTEXT.get();
    String parent = context.frames.isEmpty()
        ? ("root".equals(context.causalContext) ? occurrence(context) : context.causalContext)
        : context.frames.peek().occurrence;
    String key = context.node + "|" + context.epoch + "|" + context.causalContext + "|" + site;
    long count = increment(REGION_COUNTS, key);
    String occurrence = context.node + ":" + context.epoch + ":" + site + ":" +
        context.causalContext + ":" + count;
    context.frames.push(new Frame(site, occurrence));
    event("REGION_ENTER", site, fields("parent_id", parent));
  }

  public static void regionExit(String site) {
    Context context = CONTEXT.get();
    if (context.frames.isEmpty()) return;
    Frame current = context.frames.peek();
    if (!current.site.equals(site)) return;
    event("REGION_EXIT", site, null);
    context.frames.pop();
    if (context.frames.isEmpty()) context.unscopedSegment++;
  }

  public static void method(String site) {
    recordCoverage(site);
  }

  public static void branch(String site, boolean taken, boolean target) {
    String outcome = taken ? "TAKEN" : "FALLTHROUGH";
    recordCoverage(site + ":" + outcome);
    if (target) event("TARGET_CHECK", site, fields("branch", site, "outcome", outcome));
  }

  public static void branchCase(String site, String outcome, boolean target) {
    recordCoverage(site + ":" + outcome);
    if (target) event("TARGET_CHECK", site, fields("branch", site, "outcome", outcome));
  }

  private static void recordCoverage(String coverageId) {
    if (sink == null) return;
    Context context = CONTEXT.get();
    CoverageKey key = new CoverageKey(context.node, context.epoch, occurrence(context));
    Integer ref = COVERAGE_IDS.computeIfAbsent(coverageId, ignored -> {
      int next = COVERAGE_ID_SEQUENCE.incrementAndGet();
      if (next <= 0) throw new IllegalStateException("Coverage reference space exhausted");
      return Integer.valueOf(next);
    });
    COVERAGE.computeIfAbsent(key, ignored -> ConcurrentHashMap.<Integer>newKeySet())
        .add(ref);
  }

  /** Flush compact coverage for every observed occurrence after workload threads finish. */
  static synchronized void flushCoverage() {
    Sink current = sink;
    if (current == null || COVERAGE.isEmpty()) return;
    List<Map.Entry<String, Integer>> definitions =
        new ArrayList<Map.Entry<String, Integer>>(COVERAGE_IDS.entrySet());
    Collections.sort(definitions, (left, right) -> left.getValue().compareTo(right.getValue()));
    for (Map.Entry<String, Integer> definition : definitions) {
      if (!EMITTED_COVERAGE_DEFS.add(definition.getValue())) continue;
      Map<String, Object> row = new LinkedHashMap<String, Object>();
      row.put("type", "COVERAGE_DEF");
      row.put("node", "unknown");
      row.put("epoch", 0);
      row.put("occurrence", "coverage-definition");
      row.put("site", "mallory:coverage-definition");
      row.put("coverage_ref", definition.getValue());
      row.put("coverage_id", definition.getKey());
      row.put("ts", System.nanoTime());
      current.write(row);
    }
    List<CoverageKey> keys = new ArrayList<CoverageKey>(COVERAGE.keySet());
    Collections.sort(keys);
    for (CoverageKey key : keys) {
      Set<Integer> seen = COVERAGE.remove(key);
      if (seen == null || seen.isEmpty()) continue;
      List<Integer> refs = new ArrayList<Integer>(seen);
      Collections.sort(refs);
      Map<String, Object> row = new LinkedHashMap<String, Object>();
      row.put("type", "COVERAGE_SUMMARY");
      row.put("node", key.node);
      row.put("epoch", key.epoch);
      row.put("occurrence", key.occurrence);
      row.put("site", "mallory:coverage-summary");
      row.put("coverage_refs", refs);
      row.put("ts", System.nanoTime());
      current.write(row);
    }
  }

  private static final class CoverageKey implements Comparable<CoverageKey> {
    final String node;
    final int epoch;
    final String occurrence;
    CoverageKey(String node, int epoch, String occurrence) {
      this.node = node;
      this.epoch = epoch;
      this.occurrence = occurrence;
    }
    @Override public boolean equals(Object other) {
      if (!(other instanceof CoverageKey)) return false;
      CoverageKey that = (CoverageKey) other;
      return epoch == that.epoch && node.equals(that.node)
          && occurrence.equals(that.occurrence);
    }
    @Override public int hashCode() {
      int value = node.hashCode();
      value = 31 * value + epoch;
      return 31 * value + occurrence.hashCode();
    }
    @Override public int compareTo(CoverageKey that) {
      int order = node.compareTo(that.node);
      if (order != 0) return order;
      order = Integer.compare(epoch, that.epoch);
      return order != 0 ? order : occurrence.compareTo(that.occurrence);
    }
  }

  public static void targetThrow(Throwable exception, String site) {
    event("TARGET_THROW", site, fields("exception_class", exception == null
        ? "null" : exception.getClass().getName()));
  }

  /** Called immediately before a selected I/O callsite. Throws only on an exact plan match. */
  public static void beforeDoor(String site) {
    beforeDoor(site, "java.io.IOException");
  }

  public static void beforeDoor(String site, String defaultExceptionClass) {
    beforeDoor(site, defaultExceptionClass, null);
  }

  /** Observe the exact ZooKeeper path while preserving the original door selector. */
  public static void beforeDoor(String site, String defaultExceptionClass, String resource) {
    if (defaultExceptionClass == null || defaultExceptionClass.isEmpty())
      defaultExceptionClass = "java.io.IOException";
    Context context = CONTEXT.get();
    String occurrence = occurrence(context);
    long hit = increment(DOOR_HITS, context.node + "|" + context.epoch + "|" + occurrence + "|" + site);
    long doorOrdinal = increment(DOOR_ORDINALS,
        context.node + "|" + context.epoch + "|" + site);
    Solr15ParentSelector selector = SOLR15_PARENT.get();
    String qualifiedPhase = selector.observe(site, context.node, context.epoch,
        occurrence, resource);
    event("DOOR_OBSERVED", site, fields("hit", hit, "door_ordinal", doorOrdinal,
        "fault_type", "EXCEPTION", "resource", resource,
        "exception_class", defaultExceptionClass));
    if (qualifiedPhase != null) {
      event("SOLR15_PARENT_CANDIDATE", site, fields("selector_phase", qualifiedPhase,
          "resource", resource, "bound_resource", selector.boundPath(),
          "door_ordinal", doorOrdinal));
    }
    synchronized (plan) {
      for (FaultPlan.Fault fault : plan.faults) {
        if (!fault.matches(site, context.node, context.epoch, occurrence, hit,
            doorOrdinal, qualifiedPhase, resource, selector.boundPath())) continue;
        String faultType = fault.fault_type == null ? "IO_EXCEPTION" : fault.fault_type;
        if (!"IO_EXCEPTION".equals(faultType) && !"EXCEPTION".equals(faultType)
            && !"RUNTIME_EXCEPTION".equals(faultType)) continue;
        Throwable exception = exceptionFor(fault, defaultExceptionClass);
        if (exception == null) continue;
        fault.markApplied();
        if (fault.point.solr15_parent_lookup != null) selector.markApplied(qualifiedPhase);
        Map<String, Object> details = fields("fault_id", fault.fault_id,
            "fault_type", faultType, "exception_class", exception.getClass().getName(),
            "hit", hit, "door_ordinal", doorOrdinal, "resource", resource,
            "selector_phase", qualifiedPhase, "bound_resource", selector.boundPath());
        event("FAULT_MATCHED", site, details);
        event("FAULT_APPLIED", site, details);
        Probe.<RuntimeException>throwUnchecked(exception);
      }
    }
  }

  @SuppressWarnings("unchecked")
  private static <E extends Throwable> void throwUnchecked(Throwable failure) throws E {
    throw (E) failure;
  }

  private static Throwable exceptionFor(FaultPlan.Fault fault, String defaultExceptionClass) {
    String name = fault.exception_class;
    if (name == null || name.isEmpty()) name = defaultExceptionClass;
    try {
      Class<?> type = Class.forName(name, false, Probe.class.getClassLoader());
      if (!Throwable.class.isAssignableFrom(type)) return null;
      try {
        Constructor<?> ctor = type.getDeclaredConstructor(String.class);
        ctor.setAccessible(true);
        return (Throwable) ctor.newInstance("Mallory fault " + fault.fault_id);
      } catch (NoSuchMethodException noStringConstructor) {
        Constructor<?> ctor = type.getDeclaredConstructor();
        ctor.setAccessible(true);
        return (Throwable) ctor.newInstance();
      }
    } catch (ReflectiveOperationException | LinkageError | SecurityException failure) {
      return null;
    }
  }

  public static void stateRead(Object object, Object key, String site) {
    String objectId;
    String keyText = safeKey(key);
    long version;
    synchronized (STATE_LOCK) {
      objectId = objectId(object);
      Long known = STATE_VERSIONS.get(objectId + "|" + keyText);
      version = known == null ? -1L : known.longValue();
    }
    event("STATE_READ", site, fields("object", objectId, "key", keyText,
        "version", version, "version_confidence", "sampled"));
  }

  public static void stateWrite(Object object, Object key, String site) {
    String objectId;
    String keyText = safeKey(key);
    long version;
    synchronized (STATE_LOCK) {
      objectId = objectId(object);
      String location = objectId + "|" + keyText;
      Long old = STATE_VERSIONS.get(location);
      version = old == null ? 1L : old.longValue() + 1L;
      STATE_VERSIONS.put(location, version);
    }
    event("STATE_WRITE", site, fields("object", objectId, "key", keyText,
        "version", version, "version_confidence", "sampled"));
  }

  private static String objectId(Object object) {
    if (object == null) return "static";
    Long id = OBJECT_IDS.get(object);
    if (id == null) { id = ++nextObjectId; OBJECT_IDS.put(object, id); }
    return "o" + id;
  }

  private static String safeKey(Object key) {
    if (key == null) return "null";
    if (key instanceof String || key instanceof Number || key instanceof Enum<?>) {
      String text = String.valueOf(key);
      return text.length() <= 256 ? text : text.substring(0, 256);
    }
    return key.getClass().getName() + "@" + Integer.toHexString(System.identityHashCode(key));
  }

  private static long increment(ConcurrentHashMap<String, AtomicLong> map, String key) {
    AtomicLong fresh = new AtomicLong();
    AtomicLong counter = map.putIfAbsent(key, fresh);
    return (counter == null ? fresh : counter).incrementAndGet();
  }

  private static Map<String, Object> fields(Object... pairs) {
    Map<String, Object> result = new LinkedHashMap<String, Object>();
    for (int i = 0; i < pairs.length; i += 2) if (pairs[i + 1] != null)
      result.put((String) pairs[i], pairs[i + 1]);
    return result;
  }

  private static String occurrence(Context context) {
    if (!context.frames.isEmpty()) return context.frames.peek().occurrence;
    String base = "unscoped:" + context.node + ":" + context.epoch
        + ":" + context.causalContext;
    return base + ":thread:" + Thread.currentThread().getId()
        + ":segment:" + context.unscopedSegment;
  }

  private static void event(String type, String site, Map<String, Object> details) {
    Sink current = sink;
    if (current == null) return;
    Context context = CONTEXT.get();
    Map<String, Object> row = new LinkedHashMap<String, Object>();
    row.put("type", type);
    row.put("node", context.node);
    row.put("epoch", context.epoch);
    row.put("occurrence", occurrence(context));
    row.put("region", context.frames.isEmpty() ? null : context.frames.peek().site);
    row.put("context", context.causalContext);
    row.put("site", site);
    row.put("thread", Thread.currentThread().getName());
    row.put("thread_id", Thread.currentThread().getId());
    row.put("ts", System.nanoTime());
    if (details != null) row.putAll(details);
    current.write(row);
  }

  private static final class Context {
    String node = "unknown";
    int epoch;
    String causalContext = "root";
    long unscopedSegment;
    final Deque<Frame> frames = new ArrayDeque<Frame>();
    final Deque<NodeIdentity> nodeScopes = new ArrayDeque<NodeIdentity>();
  }

  private static final class NodeIdentity {
    final String node;
    final int epoch;
    NodeIdentity(String node, int epoch) { this.node = node; this.epoch = epoch; }
  }

  private static final class Frame {
    final String site;
    final String occurrence;
    Frame(String site, String occurrence) { this.site = site; this.occurrence = occurrence; }
  }

  private static final class Sink {
    final String runId;
    final BufferedWriter writer;
    final Gson gson = new Gson();
    long sequence;
    long bytes;
    long maxEvents = 1000000L;
    long maxBytes = 100L * 1024L * 1024L;
    boolean truncated;

    Sink(String runId, File path) throws IOException {
      this.runId = runId;
      File parent = path.getAbsoluteFile().getParentFile();
      if (parent != null && !parent.exists() && !parent.mkdirs())
        throw new IOException("Cannot create event directory " + parent);
      writer = new BufferedWriter(new OutputStreamWriter(new FileOutputStream(path, false), StandardCharsets.UTF_8));
    }

    synchronized void setLimits(long events, long bytes) {
      maxEvents = events;
      maxBytes = bytes;
    }

    synchronized void write(Map<String, Object> row) {
      if (truncated) return;
      long seq = sequence + 1;
      row.put("seq", seq);
      row.put("id", runId + ":" + seq);
      try {
        String encoded = gson.toJson(row);
        long rowBytes = encoded.getBytes(StandardCharsets.UTF_8).length + 1L;
        if (sequence >= maxEvents || bytes + rowBytes > maxBytes) {
          sequence = seq;
          Map<String, Object> marker = new LinkedHashMap<String, Object>();
          marker.put("type", "TRACE_TRUNCATED");
          marker.put("id", runId + ":" + seq);
          marker.put("seq", seq);
          marker.put("node", row.get("node"));
          marker.put("epoch", row.get("epoch"));
          marker.put("occurrence", row.get("occurrence"));
          marker.put("site", "mallory:trace-sink");
          marker.put("reason", sequence > maxEvents ? "max_events" : "max_bytes");
          marker.put("max_events", maxEvents);
          marker.put("max_bytes", maxBytes);
          marker.put("dropped_type", row.get("type"));
          writer.write(gson.toJson(marker));
          writer.newLine();
          writer.flush();
          truncated = true;
          return;
        }
        writer.write(encoded);
        writer.newLine();
        writer.flush();
        sequence = seq;
        bytes += rowBytes;
      } catch (IOException failure) {
        throw new IllegalStateException("Mallory event trace is not writable", failure);
      }
    }

    synchronized void close() throws IOException { writer.close(); }
  }
}
