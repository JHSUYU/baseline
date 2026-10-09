package research.solrreloadv2;

import java.io.BufferedWriter;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.UUID;
import java.util.Properties;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import org.apache.solr.cloud.CloudDescriptor;
import org.apache.solr.common.cloud.Replica;
import org.apache.solr.core.CoreContainer;
import org.apache.solr.core.CoreDescriptor;
import org.apache.zookeeper.KeeperException;
import org.slf4j.MDC;

/** Logical collection/shard/core identity and actual node recorded separately. */
public final class Probe {
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final ConcurrentHashMap<String, AtomicInteger> ORDINALS =
      new ConcurrentHashMap<>();
  private static final AtomicInteger NEXT_STEP = new AtomicInteger(1);
  private static final ThreadLocal<String> RELOAD_CORE = new ThreadLocal<>();
  private static final Map<Object, Binding> CLIENTS =
      Collections.synchronizedMap(new IdentityHashMap<Object, Binding>());
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

  private Probe() {}

  public static synchronized void initialize() {
    if (output != null) return;
    String trace = System.getProperty("solrreload.trace.file");
    if (trace == null || trace.isEmpty())
      throw new IllegalArgumentException("solrreload.trace.file required");
    try {
      Path path = Paths.get(trace);
      Files.createDirectories(path.toAbsolutePath().getParent());
      output = Files.newBufferedWriter(path, StandardCharsets.UTF_8,
          StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
      String plan = System.getProperty("solrreload.fault.plan", "");
      if (!plan.isEmpty()) {
        try (InputStream input = Files.newInputStream(Paths.get(plan))) {
          FAULT.load(input);
        }
        plannedSteps = Integer.parseInt(FAULT.getProperty("count", "1"));
        if (plannedSteps < 1 || plannedSteps > 10)
          throw new IllegalArgumentException("fault plan count must be 1..10");
        for (int step = 1; step <= plannedSteps; step++) {
          String prefix = "step." + step + ".";
          for (String field : new String[]{"marker", "siteId", "sourceKey", "actorKey", "resource", "hitOrdinal"}) {
            if (FAULT.getProperty(prefix + field) == null)
              throw new IllegalArgumentException("missing fault field " + prefix + field);
          }
        }
      }
      Runtime.getRuntime().addShutdownHook(new Thread(Probe::close, "solrreload-probe-close"));
    } catch (IOException failure) {
      throw new IllegalStateException("SOLR reload trace init failed", failure);
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

  public static void bindServerClient(Object client, String nodeName, String solrHome) {
    if (client == null || nodeName == null || solrHome == null)
      throw new IllegalStateException("incomplete server ZK client binding");
    String normalized = solrHome.replace('\\', '/');
    String slot = normalized.substring(normalized.lastIndexOf('/') + 1);
    String actor = "node1".equals(slot) ? "JETTY/node1" : "UNBOUND:SOLR_HOME:" + slot;
    Binding binding = new Binding(actor, nodeName, solrHome);
    synchronized (CLIENTS) {
      Binding prior = CLIENTS.get(client);
      if (prior != null && (!prior.actorKey.equals(actor) || !prior.nodeName.equals(nodeName)))
        throw new IllegalStateException("SolrZkClient rebound to another node");
      CLIENTS.put(client, binding);
    }
    emit("CLIENT_BIND", "SOLRZKCLIENT_ACTOR", "ZkController.<init>", "", actor,
        nodeName, solrHome, 0, false,
        "clientIdentity=" + System.identityHashCode(client));
  }

  private static Binding binding(CoreContainer container) {
    if (container == null || container.getZkController() == null) return null;
    return CLIENTS.get(container.getZkController().getZkClient());
  }

  private static String actor(CoreContainer container) {
    Binding found = binding(container);
    return found == null ? "UNBOUND:CORE_CONTAINER" : found.actorKey;
  }

  private static String coreEvidence(CoreDescriptor descriptor, CoreContainer container) {
    Binding found = binding(container);
    return "coreName=" + (descriptor == null ? "" : descriptor.getName())
        + ";coreNode=" + (descriptor == null || descriptor.getCloudDescriptor() == null ?
            "" : descriptor.getCloudDescriptor().getCoreNodeName())
        + ";clientIdentity=" + (found == null || container == null ? "" :
            System.identityHashCode(container.getZkController().getZkClient()))
        + ";solrHome=" + (container == null ? "" : container.getSolrHome())
        + ";coreRoot=" + (container == null ? "" : container.getCoreRootDirectory());
  }

  private static synchronized void emit(String event, String marker, String site,
                                        String source, String actorKey, String physicalNode,
                                        String resource, int ordinal, boolean applied,
                                        String detail) {
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
        + ",\"detail\":" + quote(detail) + "}";
    try { output.write(row); output.newLine(); }
    catch (IOException failure) { throw new IllegalStateException("trace write failed", failure); }
  }

  private static String source(CoreDescriptor descriptor) {
    if (descriptor == null) return "UNRESOLVED:CORE_DESCRIPTOR";
    CloudDescriptor cloud = descriptor.getCloudDescriptor();
    if (cloud == null || cloud.getCoreNodeName() == null)
      return "UNRESOLVED:CLOUD_DESCRIPTOR";
    return "SOLR/RELOAD/" + descriptor.getCollectionName() + "/"
        + cloud.getShardId() + "/" + cloud.getCoreNodeName();
  }

  private static String physical(CoreContainer container) {
    return container.getZkController() == null ? "" : container.getZkController().getNodeName();
  }

  public static void targetEnter(String core, UUID coreId, CoreContainer container) {
    RELOAD_CORE.set(core);
    emit("TARGET_ENTER", "SOLR21:RELOAD_METHOD", "CoreContainer.reload(String,UUID)",
        "UNRESOLVED:METHOD_ENTRY", actor(container), physical(container), core, 0, false,
        "coreId=" + coreId + ";solrHome=" + container.getSolrHome()
            + ";coreRoot=" + container.getCoreRootDirectory());
  }

  public static void guard(Replica replica, CoreDescriptor descriptor,
                           CoreContainer container) {
    emit("TARGET_CHECK", "SOLR21:REPLICA_NONNULL_GUARD", "CoreContainer.java:1765",
        source(descriptor), actor(container), physical(container), descriptor.getName(), 0, false,
        (replica == null ? "replica=null" : "replica=" + replica.getName()
            + ";state=" + replica.getState() + ";type=" + replica.getType())
            + ";" + coreEvidence(descriptor, container));
  }

  public static void targetThrow(Throwable failure, CoreDescriptor descriptor,
                                 CoreContainer container) {
    if (!(failure instanceof AssertionError)) return;
    emit("TARGET_THROW", "SOLR21:REPLICA_NULL_ASSERTION", "CoreContainer.java:1765",
        source(descriptor), actor(container), physical(container), descriptor.getName(), 0, false,
        failure.toString() + ";" + coreEvidence(descriptor, container));
  }

  private static String collectionSource(String path) {
    if (path.startsWith("/collections/")) {
      String suffix = path.substring("/collections/".length());
      return "SOLR/COLLECTION/" + suffix.split("/", 2)[0];
    }
    return "UNRESOLVED:ZK:" + path;
  }

  private static boolean apply(String marker, String site, String source,
                               String actorKey, String resource, int ordinal) {
    int step = NEXT_STEP.get();
    if (step > plannedSteps) return false;
    String prefix = "step." + step + ".";
    boolean exact = marker.equals(FAULT.getProperty(prefix + "marker"))
        && site.equals(FAULT.getProperty(prefix + "siteId"))
        && source.equals(FAULT.getProperty(prefix + "sourceKey"))
        && actorKey.equals(FAULT.getProperty(prefix + "actorKey"))
        && resource.equals(FAULT.getProperty(prefix + "resource"))
        && ordinal == Integer.parseInt(FAULT.getProperty(prefix + "hitOrdinal"));
    if (exact && (source.startsWith("UNRESOLVED:") || site.startsWith("UNRESOLVED:")
        || actorKey.startsWith("UNBOUND:")))
      throw new IllegalStateException("refuse fault on unresolved I/O identity");
    return exact && NEXT_STEP.compareAndSet(step, step + 1);
  }

  /** Observe a real ZooKeeper operation inside Solr's retry callable. */
  public static void nativeEntry(Object client, String path, String api) throws KeeperException {
    if (path == null) return;
    Binding binding = CLIENTS.get(client);
    String actorKey = binding == null ? "UNBOUND:ZK_CLIENT" : binding.actorKey;
    String physicalNode = binding == null ? "" : binding.nodeName;
    StackTraceElement[] stack = Thread.currentThread().getStackTrace();
    StackTraceElement caller = null;
    boolean inReload = false;
    for (StackTraceElement frame : stack) {
      if (frame.getClassName().equals("org.apache.solr.core.CoreContainer")
          && frame.getMethodName().equals("reload")) inReload = true;
      if (caller == null && frame.getClassName().startsWith("org.apache.solr.")
          && !frame.getClassName().equals("org.apache.solr.common.cloud.SolrZkClient")
          && !frame.getClassName().equals("org.apache.solr.common.cloud.ZkCmdExecutor"))
        caller = frame;
    }
    String source = inReload && RELOAD_CORE.get() != null
        ? "SOLR/RELOAD_CORE/" + RELOAD_CORE.get() : collectionSource(path);
    String site = caller == null ? "UNRESOLVED:CALLER" : caller.getClassName()
        + "." + caller.getMethodName() + "#L" + caller.getLineNumber()
        + "->SolrZkClient." + api;
    int end = api.indexOf('$', "lambda$".length());
    if (!api.startsWith("lambda$") || end < 0)
      throw new IllegalArgumentException("unexpected retry method " + api);
    String marker = "FAULT:ZK_NATIVE:" + api.substring("lambda$".length(), end);
    String key = marker + '\u0000' + site + '\u0000' + source
        + '\u0000' + actorKey + '\u0000' + path;
    int ordinal = ORDINALS.computeIfAbsent(key, unused -> new AtomicInteger())
        .incrementAndGet();
    boolean matched = apply(marker, site, source, actorKey, path, ordinal);
    emit("IO_OBSERVED", marker, site, source, actorKey, physicalNode,
        path, ordinal, matched, "path=" + path
            + ";clientIdentity=" + System.identityHashCode(client)
            + ";solrHome=" + (binding == null ? "" : binding.solrHome)
            + ";mdcNode=" + MDC.get("node_name")
            + ";mdcCore=" + MDC.get("core"));
    if (matched) throw KeeperException.create(KeeperException.Code.CONNECTIONLOSS, path);
  }

  /** Observe the original core.properties read before reloading the descriptor. */
  public static void fileRead(Path path, CoreContainer container) throws IOException {
    String name = path.getParent() == null ? "UNRESOLVED:PARENT"
        : path.getParent().getFileName().toString();
    String marker = "FAULT:FILE:core.properties:read";
    String site = "CorePropertiesLocator.buildCoreDescriptor#L187->Files.newInputStream";
    String source = "SOLR/CORE_PROPERTIES/" + name;
    String resource = name + "/" + path.getFileName();
    Path coreRoot = container == null ? null :
        container.getCoreRootDirectory().toAbsolutePath().normalize();
    Path candidateRoot = path.getParent() == null || path.getParent().getParent() == null ?
        null : path.getParent().getParent().toAbsolutePath().normalize();
    boolean exactRoot = coreRoot != null && coreRoot.equals(candidateRoot);
    Binding binding = exactRoot ? binding(container) : null;
    String actorKey = binding == null ? "UNBOUND:FILE_CORE" : binding.actorKey;
    String key = marker + '\u0000' + site + '\u0000' + source
        + '\u0000' + actorKey + '\u0000' + resource;
    int ordinal = ORDINALS.computeIfAbsent(key, unused -> new AtomicInteger())
        .incrementAndGet();
    boolean matched = apply(marker, site, source, actorKey, resource, ordinal);
    emit("IO_OBSERVED", marker, site, source, actorKey,
        binding == null ? "" : binding.nodeName,
        resource, ordinal, matched, "absolutePath=" + path.toAbsolutePath()
            + ";coreRoot=" + coreRoot + ";exactCoreRoot=" + exactRoot
            + ";clientIdentity=" + (binding == null ? "" :
                System.identityHashCode(container.getZkController().getZkClient()))
            + ";mdcNode=" + MDC.get("node_name")
            + ";mdcCore=" + MDC.get("core"));
    if (matched) throw new IOException("Injected core.properties read failure: " + resource);
  }
}
