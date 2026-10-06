package research.solrcoord;

import java.io.BufferedWriter;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.Properties;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import org.apache.solr.common.SolrException;
import org.apache.solr.common.cloud.DocCollection;
import org.apache.zookeeper.KeeperException;
import org.slf4j.MDC;

/** Logical coordinator request identity and actual Jetty node recorded separately. */
public final class Probe {
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final ConcurrentHashMap<String, AtomicInteger> ORDINALS =
      new ConcurrentHashMap<>();
  private static final AtomicInteger NEXT_STEP = new AtomicInteger(1);
  private static final ThreadLocal<String> REQUEST_COLLECTION = new ThreadLocal<>();
  private static final ThreadLocal<String> COORD_NODE = new ThreadLocal<>();
  private static final Properties FAULT = new Properties();
  private static BufferedWriter output;
  private static int plannedSteps;

  private Probe() {}

  public static synchronized void initialize() {
    if (output != null) return;
    String trace = System.getProperty("solrcoord.trace.file");
    if (trace == null || trace.isEmpty())
      throw new IllegalArgumentException("solrcoord.trace.file required");
    try {
      Path path = Paths.get(trace);
      Files.createDirectories(path.toAbsolutePath().getParent());
      output = Files.newBufferedWriter(path, StandardCharsets.UTF_8,
          StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
      String plan = System.getProperty("solrcoord.fault.plan", "");
      if (!plan.isEmpty()) {
        try (InputStream input = Files.newInputStream(Paths.get(plan))) {
          FAULT.load(input);
        }
        plannedSteps = Integer.parseInt(FAULT.getProperty("count", "1"));
        if (plannedSteps < 1 || plannedSteps > 10)
          throw new IllegalArgumentException("fault plan count must be 1..10");
        for (int step = 1; step <= plannedSteps; step++) {
          String prefix = "step." + step + ".";
          for (String field : new String[]{"marker", "siteId", "sourceKey", "resource", "hitOrdinal"}) {
            if (FAULT.getProperty(prefix + field) == null)
              throw new IllegalArgumentException("missing fault field " + prefix + field);
          }
        }
      }
      Runtime.getRuntime().addShutdownHook(new Thread(Probe::close, "solrcoord-probe-close"));
    } catch (IOException failure) {
      throw new IllegalStateException("SOLR reload trace init failed", failure);
    }
  }

  public static synchronized void close() {
    if (output == null) return;
    emit("SUMMARY", "", "", "", "", "", 0, false,
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

  private static synchronized void emit(String event, String marker, String site,
                                        String source, String physicalNode,
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
        + ",\"physicalNode\":" + quote(physicalNode)
        + ",\"resource\":" + quote(resource)
        + ",\"hitOrdinal\":" + ordinal
        + ",\"applied\":" + applied
        + ",\"detail\":" + quote(detail) + "}";
    try { output.write(row); output.newLine(); }
    catch (IOException failure) { throw new IllegalStateException("trace write failed", failure); }
  }

  private static String source(String collection) {
    return collection == null ? "UNRESOLVED:COLLECTION" :
        "SOLR/COORD_REQUEST/" + collection;
  }

  public static void targetEnter(String collection, String physicalNode) {
    REQUEST_COLLECTION.set(collection);
    COORD_NODE.set(physicalNode);
    emit("TARGET_ENTER", "SOLR34:COORDINATOR_GET_CORE",
        "CoordinatorHttpSolrCall.getCore", source(collection), physicalNode,
        collection, 0, false, "");
  }

  public static void guard(DocCollection syntheticCollection, String collection) {
    emit("TARGET_CHECK", "SOLR34:SYNTHETIC_COLLECTION_NONNULL_GUARD",
        "CoordinatorHttpSolrCall.java:138", source(collection), COORD_NODE.get(),
        collection, 0, false,
        syntheticCollection == null ? "syntheticCollection=null" :
            "syntheticCollection=" + syntheticCollection.getName());
  }

  public static void targetThrow(Throwable failure, String collection, int line) {
    if (!(failure instanceof SolrException)) return;
    String message = failure.getMessage();
    if (line == 143 && (message == null ||
        !message.startsWith("Could not locate synthetic collection ["))) return;
    String marker = line == 143 ? "SOLR34:SYNTHETIC_COLLECTION_MISSING" :
        "SOLR34:CREATE_EXCEPTION_RETHROWN";
    emit("TARGET_THROW", marker, "CoordinatorHttpSolrCall.java:" + line,
        source(collection), COORD_NODE.get(), collection, 0, false,
        failure.getClass().getName() + ": " + message);
  }

  private static String collectionSource(String path) {
    if (path.startsWith("/collections/")) {
      String suffix = path.substring("/collections/".length());
      return "SOLR/COLLECTION/" + suffix.split("/", 2)[0];
    }
    return "UNRESOLVED:ZK:" + path;
  }

  private static boolean apply(String marker, String site, String source,
                               String resource, int ordinal) {
    int step = NEXT_STEP.get();
    if (step > plannedSteps) return false;
    String prefix = "step." + step + ".";
    boolean exact = marker.equals(FAULT.getProperty(prefix + "marker"))
        && site.equals(FAULT.getProperty(prefix + "siteId"))
        && source.equals(FAULT.getProperty(prefix + "sourceKey"))
        && resource.equals(FAULT.getProperty(prefix + "resource"))
        && ordinal == Integer.parseInt(FAULT.getProperty(prefix + "hitOrdinal"));
    if (exact && (source.startsWith("UNRESOLVED:") || site.startsWith("UNRESOLVED:")))
      throw new IllegalStateException("refuse fault on unresolved I/O identity");
    return exact && NEXT_STEP.compareAndSet(step, step + 1);
  }

  /** Observe a real ZooKeeper operation inside Solr's retry callable. */
  public static void nativeEntry(String path, String api) throws KeeperException {
    if (path == null) return;
    StackTraceElement[] stack = Thread.currentThread().getStackTrace();
    StackTraceElement caller = null;
    boolean inCoordinator = false;
    for (StackTraceElement frame : stack) {
      if (frame.getClassName().equals("org.apache.solr.servlet.CoordinatorHttpSolrCall")
          && frame.getMethodName().equals("getCore")) inCoordinator = true;
      if (caller == null && frame.getClassName().startsWith("org.apache.solr.")
          && !frame.getClassName().equals("org.apache.solr.common.cloud.SolrZkClient")
          && !frame.getClassName().equals("org.apache.solr.common.cloud.ZkCmdExecutor"))
        caller = frame;
    }
    String source = inCoordinator && REQUEST_COLLECTION.get() != null
        ? source(REQUEST_COLLECTION.get()) : collectionSource(path);
    String site = caller == null ? "UNRESOLVED:CALLER" : caller.getClassName()
        + "." + caller.getMethodName() + "#L" + caller.getLineNumber()
        + "->SolrZkClient." + api;
    int end = api.indexOf('$', "lambda$".length());
    if (!api.startsWith("lambda$") || end < 0)
      throw new IllegalArgumentException("unexpected retry method " + api);
    String marker = "FAULT:ZK_NATIVE:" + api.substring("lambda$".length(), end);
    String key = marker + '\u0000' + site + '\u0000' + source + '\u0000' + path;
    int ordinal = ORDINALS.computeIfAbsent(key, unused -> new AtomicInteger())
        .incrementAndGet();
    boolean matched = apply(marker, site, source, path, ordinal);
    String node = inCoordinator ? COORD_NODE.get() : MDC.get("node_name");
    emit("IO_OBSERVED", marker, site, source, node == null ? "" : node,
        path, ordinal, matched, "path=" + path + ";mdcCore=" + MDC.get("core"));
    if (matched) throw KeeperException.create(KeeperException.Code.CONNECTIONLOSS, path);
  }
}
