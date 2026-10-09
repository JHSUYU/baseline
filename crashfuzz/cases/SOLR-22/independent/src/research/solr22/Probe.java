package research.solr22;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.util.Properties;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.apache.lucene.store.Directory;
import org.apache.lucene.store.IOContext;
import org.apache.lucene.store.IndexInput;
import org.apache.lucene.store.IndexOutput;
import org.apache.solr.core.SolrCore;

/** Direct Directory fault gate and target/window event recorder for SOLR-22. */
public final class Probe {
  private static final Pattern NODE = Pattern.compile("(?:^|[^A-Za-z0-9])node([0-9]+)(?:[^A-Za-z0-9]|$)");
  private static final Pattern RAM_TOKEN = Pattern.compile("RAMDirectory@[0-9a-fA-F]+");
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final ConcurrentHashMap<String, AtomicInteger> ORDINALS = new ConcurrentHashMap<>();
  private static final ConcurrentHashMap<Directory, String> DIRECTORY_SOURCE = new ConcurrentHashMap<>();
  private static final ConcurrentHashMap<Directory, String> DIRECTORY_PATH = new ConcurrentHashMap<>();
  private static final ConcurrentHashMap<String, String> RAM_SOURCE = new ConcurrentHashMap<>();
  private static final ConcurrentHashMap<String, String> RAM_PATH = new ConcurrentHashMap<>();
  private static final ConcurrentHashMap<Object, String> POLICY_SOURCE = new ConcurrentHashMap<>();
  private static final ConcurrentHashMap<Object, String> POLICY_PATH = new ConcurrentHashMap<>();
  private static final ThreadLocal<Boolean> INSIDE = ThreadLocal.withInitial(() -> Boolean.FALSE);
  private static final Properties FAULT = new Properties();
  private static BufferedWriter output;
  private static final AtomicInteger NEXT_STEP = new AtomicInteger(1);
  private static int plannedSteps;

  private Probe() {}

  public static synchronized void initialize() {
    if (output != null) return;
    String outputPath = System.getProperty("solr22.trace.file");
    if (outputPath == null || outputPath.isEmpty())
      throw new IllegalArgumentException("solr22.trace.file is required");
    try {
      Path path = Paths.get(outputPath);
      Files.createDirectories(path.toAbsolutePath().getParent());
      output = Files.newBufferedWriter(path, StandardCharsets.UTF_8,
          StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING);
      String plan = System.getProperty("solr22.fault.plan", "");
      if (!plan.isEmpty()) {
        try (java.io.InputStream input = Files.newInputStream(Paths.get(plan))) {
          FAULT.load(input);
        }
        plannedSteps = Integer.parseInt(FAULT.getProperty("count", "1"));
        if (plannedSteps < 1 || plannedSteps > 10)
          throw new IllegalArgumentException("fault plan count must be 1..10");
        for (int step = 1; step <= plannedSteps; step++) {
          String prefix = FAULT.containsKey("count") ? "step." + step + "." : "";
          for (String field : new String[]{"siteId", "sourceKey", "resource", "hitOrdinal"}) {
            if (FAULT.getProperty(prefix + field) == null)
              throw new IllegalArgumentException("fault plan misses " + prefix + field);
          }
        }
      }
      Runtime.getRuntime().addShutdownHook(new Thread(Probe::close, "solr22-probe-close"));
    } catch (IOException failure) {
      throw new IllegalStateException("cannot initialize SOLR22 probe", failure);
    }
  }

  public static synchronized void close() {
    if (output == null) return;
    emit("FAULT_TRIAL_SUMMARY", "SUMMARY:SOLR22", "", "", "", "",
        0, false, false, "applied=" + (NEXT_STEP.get() - 1) + "/" + plannedSteps, null);
    try { output.flush(); output.close(); }
    catch (IOException failure) { failure.printStackTrace(System.err); }
    output = null;
  }

  private static synchronized void emit(String event, String marker, String site,
                                        String source, String sourceRaw,
                                        String resource, int ordinal,
                                        boolean matched, boolean applied,
                                        String detail, Object policy) {
    if (output == null) return;
    long seq = SEQUENCE.incrementAndGet();
    StringBuilder row = new StringBuilder(380);
    row.append("{\"schemaVersion\":1,\"event\":").append(quote(event));
    row.append(",\"seq\":").append(seq);
    row.append(",\"timeNs\":").append(System.nanoTime());
    row.append(",\"threadId\":").append(Thread.currentThread().getId());
    row.append(",\"marker\":").append(quote(marker));
    row.append(",\"siteId\":").append(quote(site));
    row.append(",\"sourceKey\":").append(quote(source));
    row.append(",\"sourceRaw\":").append(quote(sourceRaw));
    row.append(",\"physicalNode\":").append(quote(nodeFrom(sourceRaw, resource,
        policy == null ? "" : POLICY_PATH.get(policy))));
    row.append(",\"resource\":").append(quote(resource));
    row.append(",\"hitOrdinal\":").append(ordinal);
    row.append(",\"matched\":").append(matched);
    row.append(",\"applied\":").append(applied);
    row.append(",\"detail\":").append(quote(detail));
    row.append(",\"policyId\":").append(policy == null ? "null"
        : quote(Integer.toHexString(System.identityHashCode(policy))));
    row.append('}');
    try { output.write(row.toString()); output.newLine(); }
    catch (IOException failure) { throw new IllegalStateException("SOLR22 trace write failed", failure); }
  }

  private static String quote(String value) {
    if (value == null) return "null";
    StringBuilder result = new StringBuilder(value.length() + 2).append('"');
    for (int i = 0; i < value.length(); i++) {
      char ch = value.charAt(i);
      if (ch == '"' || ch == '\\') result.append('\\').append(ch);
      else if (ch == '\n') result.append("\\n");
      else if (ch == '\r') result.append("\\r");
      else if (ch == '\t') result.append("\\t");
      else if (ch < 0x20) result.append(String.format("\\u%04x", (int) ch));
      else result.append(ch);
    }
    return result.append('"').toString();
  }

  private static String nodeFrom(String... values) {
    for (String value : values) {
      if (value == null) continue;
      Matcher node = NODE.matcher(value);
      if (node.find()) return "node" + node.group(1);
    }
    return null;
  }

  private static void beforeIo(String kind, Directory directory, String file, String site)
      throws IOException {
    if (Boolean.TRUE.equals(INSIDE.get())) return;
    INSIDE.set(Boolean.TRUE);
    try {
      String raw;
      try { raw = String.valueOf(directory); }
      catch (Throwable ignored) { raw = directory.getClass().getName(); }
      if (raw.length() > 500) raw = raw.substring(0, 500);
      String source = DIRECTORY_SOURCE.get(directory);
      String path = DIRECTORY_PATH.get(directory);
      if (source == null) source = stableSource(raw);
      if (source == null) {
        Matcher token = RAM_TOKEN.matcher(raw);
        if (token.find()) {
          source = RAM_SOURCE.get(token.group());
          path = RAM_PATH.get(token.group());
        }
      }
      if (source == null) source = "UNRESOLVED:" + directory.getClass().getName();
      String key = kind + '\u0000' + site + '\u0000' + source + '\u0000' + file;
      int ordinal = ORDINALS.computeIfAbsent(key, k -> new AtomicInteger()).incrementAndGet();
      int step = NEXT_STEP.get();
      String prefix = FAULT.containsKey("count") ? "step." + step + "." : "";
      boolean matches = step <= plannedSteps
          && site.equals(FAULT.getProperty(prefix + "siteId"))
          && source.equals(FAULT.getProperty(prefix + "sourceKey"))
          && file.equals(FAULT.getProperty(prefix + "resource"))
          && ordinal == Integer.parseInt(FAULT.getProperty(prefix + "hitOrdinal"));
      if (matches && source.startsWith("UNRESOLVED:"))
        throw new IllegalStateException("refuse fault on unresolved Directory source identity");
      if (matches) matches = NEXT_STEP.compareAndSet(step, step + 1);
      emit("FAULT_POINT_OBSERVED", "FAULT:LUCENE_DIRECTORY:" + kind,
          site, source, path == null ? raw : path, file, ordinal, matches, matches,
          matches ? "step=" + step : "", null);
      if (matches) throw new IOException("SOLR22 injected Directory " + kind
          + " at " + site + " source=" + source + " file=" + file);
    } finally {
      INSIDE.set(Boolean.FALSE);
    }
  }

  public static void registerDirectory(Directory directory, String path) {
    if (directory == null) return;
    String source = stableSource(path);
    if (source == null) source = "UNRESOLVED:factory-path";
    DIRECTORY_SOURCE.put(directory, source);
    DIRECTORY_PATH.put(directory, path);
    String raw = String.valueOf(directory);
    Matcher token = RAM_TOKEN.matcher(raw);
    if (token.find()) {
      RAM_SOURCE.put(token.group(), source);
      RAM_PATH.put(token.group(), path);
    }
    emit("DIRECTORY_REGISTER", "DIRECTORY:REGISTER", "CachingDirectoryFactory.get",
        source, raw, path, 0, false, false, "", null);
  }

  private static String stableSource(String path) {
    Matcher node = NODE.matcher(path);
    if (!node.find()) return null;
    int start = node.start(1) - 4;
    String suffix = path.substring(start).replace('\\', '/');
    int close = suffix.indexOf(')');
    if (close >= 0) suffix = suffix.substring(0, close);
    while (suffix.endsWith("/")) suffix = suffix.substring(0, suffix.length() - 1);
    int slash = suffix.indexOf('/');
    if (slash < 0) return null;
    return suffix.substring(slash + 1).replaceAll("index\\.[0-9]+", "index.backup");
  }

  public static void registerPolicy(Object policy, Object core) {
    if (policy == null || !(core instanceof SolrCore)) return;
    SolrCore solrCore = (SolrCore) core;
    String path = solrCore.getDataDir();
    String source = stableSource(path);
    if (source == null) source = "UNRESOLVED:policy:" + solrCore.getName();
    POLICY_SOURCE.put(policy, source);
    POLICY_PATH.put(policy, path);
    emit("POLICY_REGISTER", "POLICY:REGISTER", "SolrCore.getDeletionPolicy",
        source, path, solrCore.getName(), 0, false, false, "", policy);
  }

  public static void deleteFile(Directory directory, String file, String site) throws IOException {
    beforeIo("DELETE", directory, file, site);
    directory.deleteFile(file);
  }

  public static IndexInput openInput(Directory directory, String file, IOContext context,
                                     String site) throws IOException {
    beforeIo("READ", directory, file, site);
    return directory.openInput(file, context);
  }

  public static IndexOutput createOutput(Directory directory, String file, IOContext context,
                                         String site) throws IOException {
    beforeIo("CREATE", directory, file, site);
    return directory.createOutput(file, context);
  }

  public static void targetEnter(Object policy, Long generation) {
    emit("TARGET_ENTER", "TARGET:SOLR22", "IndexDeletionPolicyWrapper.getAndSaveCommitPoint",
        policySource(policy), policyPath(policy), "", 0, false, false, String.valueOf(generation), policy);
  }

  public static void targetCheck(Object policy, Long generation) {
    emit("TARGET_CHECK", "TARGET:SOLR22", "IndexDeletionPolicyWrapper.java:175",
        policySource(policy), policyPath(policy), "", 0, false, false, String.valueOf(generation), policy);
  }

  public static void targetThrow(Throwable thrown, Object policy) {
    if (thrown instanceof IllegalStateException) {
      emit("TARGET_THROW", "TARGET:SOLR22", "IndexDeletionPolicyWrapper.java:177",
          policySource(policy), policyPath(policy), "", 0, false, false, thrown.toString(), policy);
    }
  }

  public static void onCommitEnter(Object policy) {
    emit("ONCOMMIT_ENTER", "WINDOW:SOLR22", "IndexDeletionPolicyWrapper.onCommit",
        policySource(policy), policyPath(policy), "", 0, false, false, "", policy);
  }

  public static void windowStart(Object policy) {
    emit("ONCOMMIT_WINDOW_START", "WINDOW:SOLR22", "after updateLatestCommit",
        policySource(policy), policyPath(policy), "", 0, false, false, "", policy);
  }

  public static void windowEnd(Object policy) {
    emit("ONCOMMIT_WINDOW_END", "WINDOW:SOLR22", "before updateKnownCommitPoints",
        policySource(policy), policyPath(policy), "", 0, false, false, "", policy);
  }

  public static void onCommitReturn(Object policy) {
    emit("ONCOMMIT_RETURN", "WINDOW:SOLR22", "IndexDeletionPolicyWrapper.onCommit",
        policySource(policy), policyPath(policy), "", 0, false, false, "", policy);
  }

  private static String policySource(Object policy) {
    String source = POLICY_SOURCE.get(policy);
    return source == null ? "UNRESOLVED:policy" : source;
  }

  private static String policyPath(Object policy) {
    String path = POLICY_PATH.get(policy);
    return path == null ? "" : path;
  }
}
