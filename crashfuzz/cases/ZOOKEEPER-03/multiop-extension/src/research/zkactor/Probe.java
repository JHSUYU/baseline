package research.zkactor;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/** Ordered checked-I/O injection and exact target events with actor-aware keys. */
public final class Probe {
  private static final class Event {
    final long sequence;
    final String line;
    Event(long sequence, String line) { this.sequence = sequence; this.line = line; }
  }

  private static final String[] PLAN = System.getProperty("zk.actor.plan", "").isEmpty()
      ? new String[0] : System.getProperty("zk.actor.plan").split("\\|\\|\\|");
  private static final AtomicInteger NEXT = new AtomicInteger();
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final ConcurrentHashMap<String, AtomicInteger> ORDINALS = new ConcurrentHashMap<>();
  private static final ConcurrentLinkedQueue<Event> EVENTS = new ConcurrentLinkedQueue<>();
  private static final ConcurrentHashMap<String, Boolean> COVERAGE = new ConcurrentHashMap<>();

  static {
    String output = System.getProperty("zk.actor.events.output", "");
    if (!output.isEmpty()) {
      Runtime.getRuntime().addShutdownHook(new Thread(() -> {
        try { write(Paths.get(output)); }
        catch (IOException error) { error.printStackTrace(); }
      }, "zk-actor-v2-flush"));
    }
    String coverageOutput = System.getProperty("zk.actor.coverage.output", "");
    if (!coverageOutput.isEmpty()) {
      Runtime.getRuntime().addShutdownHook(new Thread(() -> {
        try {
          List<String> lines = new ArrayList<>(COVERAGE.keySet());
          lines.sort(String::compareTo);
          Files.write(Paths.get(coverageOutput), lines, StandardCharsets.UTF_8);
        } catch (IOException error) { error.printStackTrace(); }
      }, "zk-actor-v2-coverage-flush"));
    }
  }

  private Probe() {}

  private static String clean(String value) {
    return value == null ? "" : value.replace('\t', '_').replace('\n', '_').replace('\r', '_');
  }

  private static void event(String kind, String... fields) {
    long sequence = SEQUENCE.incrementAndGet();
    StringBuilder line = new StringBuilder().append(sequence).append('\t').append(kind);
    for (String field : fields) line.append('\t').append(clean(field));
    line.append('\t').append(clean(Thread.currentThread().getName()));
    EVENTS.add(new Event(sequence, line.toString()));
  }

  public static void diagnostic(String kind, String... fields) {
    event(kind, fields);
  }

  public static void coverage(String owner, String method, int line) {
    COVERAGE.put(owner + "#" + method + ":" + line, Boolean.TRUE);
  }

  private static String selector(String site, ActorRegistry.IoIdentity identity, int ordinal) {
    return site + "@@" + identity.actor + "@@" + identity.resource + "@@" + ordinal;
  }

  private static String[] fields(String site, ActorRegistry.IoIdentity identity, int ordinal) {
    return new String[] {site, identity.actor, identity.resource, Integer.toString(ordinal),
        identity.localPeer, identity.counterpartyPeer, identity.sessionTag};
  }

  public static void io(String site, ActorRegistry.IoIdentity identity) throws IOException {
    if (site == null || site.isEmpty() || site.contains("@@") || site.contains("|||")) {
      throw new IllegalArgumentException("invalid static I/O site");
    }
    if (identity == null || !identity.bound()) {
      event("UNBOUND_IO", site, identity == null ? "no-identity" : identity.unboundReason);
      return;
    }
    String family = site + "@@" + identity.actor + "@@" + identity.resource;
    int ordinal = ORDINALS.computeIfAbsent(family, key -> new AtomicInteger()).incrementAndGet();
    String[] details = fields(site, identity, ordinal);
    event("IO", details);
    int next = NEXT.get();
    if (next < PLAN.length && PLAN[next].equals(selector(site, identity, ordinal))
        && NEXT.compareAndSet(next, next + 1)) {
      event("FAULT_MATCHED", details);
      event("FAULT_APPLIED", details);
      throw new IOException("selected actor-aware I/O fault " + PLAN[next]);
    }
  }

  public static void targetGuard(String check, ActorRegistry.TargetIdentity identity,
      String branch) {
    if (identity == null || !identity.bound()) {
      event("UNBOUND_TARGET", check,
          identity == null ? "no-identity" : identity.unboundReason);
      return;
    }
    event("TARGET_GUARD", check, identity.actor, identity.role, identity.peer,
        identity.sessionTag, branch);
  }

  public static void targetThrow(String check, ActorRegistry.TargetIdentity identity,
      String exceptionName) {
    if (identity == null || !identity.bound()) {
      event("UNBOUND_TARGET", check,
          identity == null ? "no-identity" : identity.unboundReason);
      return;
    }
    event("TARGET_THROW", check, identity.actor, identity.role, identity.peer,
        identity.sessionTag, exceptionName);
  }

  public static void write(Path output) throws IOException {
    List<Event> sorted = new ArrayList<>(EVENTS);
    sorted.sort(Comparator.comparingLong(event -> event.sequence));
    List<String> lines = new ArrayList<>(sorted.size());
    for (Event event : sorted) lines.add(event.line);
    Files.write(output, lines, StandardCharsets.UTF_8);
  }
}
