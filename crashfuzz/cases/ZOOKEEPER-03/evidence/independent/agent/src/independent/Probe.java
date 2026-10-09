package independent;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

public final class Probe {
  private static final Set<String> HITS = Collections.newSetFromMap(new ConcurrentHashMap<String, Boolean>());
  private static final ConcurrentLinkedQueue<String> EVENTS = new ConcurrentLinkedQueue<String>();
  private static final ConcurrentHashMap<String, AtomicInteger> ORDINALS = new ConcurrentHashMap<String, AtomicInteger>();
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final ThreadLocal<Long> SESSION = new ThreadLocal<Long>();
  private static final String[] PLAN = System.getProperty("research.fault.plan", "").isEmpty()
      ? new String[0] : System.getProperty("research.fault.plan").split("\\|\\|\\|");
  private static final AtomicInteger NEXT = new AtomicInteger();
  static {
    Runtime.getRuntime().addShutdownHook(new Thread(new Runnable() {
      @Override public void run() {
        try {
          ArrayList<String> lines = new ArrayList<String>(HITS);
          Collections.sort(lines);
          Files.write(Paths.get(System.getProperty("research.coverage.output")), lines, StandardCharsets.UTF_8);
          Files.write(Paths.get(System.getProperty("research.events.output")),
              new ArrayList<String>(EVENTS), StandardCharsets.UTF_8);
        } catch (Throwable error) {
          error.printStackTrace();
        }
      }
    }));
  }
  private static void event(String kind, String detail) {
    EVENTS.add(SEQUENCE.incrementAndGet() + "\t" + kind + "\t"
        + Thread.currentThread().getName() + "\t" + detail);
  }
  private static String session() {
    Long value = SESSION.get();
    return value == null ? "unknown" : Long.toHexString(value.longValue());
  }
  public static void hit(String clazz, String method, int line) {
    HITS.add(clazz + "\t" + method + "\t" + line);
  }
  public static void entry(long id) {
    SESSION.set(id);
    event("TARGET_ENTRY", Long.toHexString(id));
  }
  public static void guard() {
    event("TARGET_GUARD", session());
  }
  public static void targetThrow(Throwable exception) {
    event("TARGET_THROW", session() + "\t" + exception.getClass().getName());
  }
  public static void io(String site) throws IOException {
    AtomicInteger counter = ORDINALS.get(site);
    if (counter == null) {
      AtomicInteger created = new AtomicInteger();
      AtomicInteger previous = ORDINALS.putIfAbsent(site, created);
      counter = previous == null ? created : previous;
    }
    int ordinal = counter.incrementAndGet();
    event("IO", site + "\t" + ordinal);
    int next = NEXT.get();
    if (next < PLAN.length && PLAN[next].equals(site + "@@" + ordinal)
        && NEXT.compareAndSet(next, next + 1)) {
      event("FAULT_MATCHED", site + "\t" + ordinal);
      event("FAULT_APPLIED", site + "\t" + ordinal);
      throw new IOException("selected independent I/O fault " + site + " ordinal " + ordinal);
    }
  }
}
