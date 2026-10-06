package zk13;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.io.IOException;
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
  private static final ConcurrentHashMap<String, AtomicInteger> ORDINALS =
      new ConcurrentHashMap<String, AtomicInteger>();
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final String FAULT_SITE = System.getProperty("zk13.fault.site", "");
  private static final int FAULT_ORDINAL = Integer.getInteger("zk13.fault.ordinal", -1);
  private static final String[] FAULT_PLAN = System.getProperty("zk13.fault.plan", "").isEmpty()
      ? new String[0] : System.getProperty("zk13.fault.plan").split("\\|\\|\\|");
  private static final AtomicInteger NEXT_PLAN = new AtomicInteger();
  static {
    Runtime.getRuntime().addShutdownHook(new Thread(new Runnable() {
      @Override public void run() {
        try {
          ArrayList<String> lines = new ArrayList<String>(HITS);
          Collections.sort(lines);
          String file = System.getProperty("coverage.output", "/tmp/zk-coverage-hits.txt");
          Files.write(Paths.get(file), lines, StandardCharsets.UTF_8);
          ArrayList<String> events = new ArrayList<String>(EVENTS);
          String eventFile = System.getProperty("zk13.events.output", "/tmp/zk13-events.tsv");
          Files.write(Paths.get(eventFile), events, StandardCharsets.UTF_8);
        } catch (Throwable error) {
          error.printStackTrace();
        }
      }
    }));
  }
  public static void hit(String clazz, String method, int line) {
    HITS.add(clazz + "\t" + method + "\t" + line);
  }
  private static void event(String kind, String detail) {
    EVENTS.add(SEQUENCE.incrementAndGet() + "\t" + kind + "\t"
        + Thread.currentThread().getName() + "\t" + detail);
  }
  public static void guard(int comparison) {
    event("TARGET_GUARD", comparison != 0 ? "THROW_ARM" : "NORMAL_ARM");
  }
  public static void targetEntry(Object cnxn, long sessionId) {
    String remote;
    try {
      remote = String.valueOf(cnxn.getClass().getMethod("getRemoteSocketAddress").invoke(cnxn));
    } catch (Throwable error) {
      remote = "unavailable:" + error.getClass().getSimpleName();
    }
    event("TARGET_ENTRY", Long.toHexString(sessionId) + "\t" + remote);
  }
  public static void targetThrow(Throwable error) {
    String observedReason;
    try {
      observedReason = String.valueOf(error.getClass().getMethod("getReason").invoke(error));
    } catch (Throwable reflectionError) {
      observedReason = "unavailable:" + reflectionError.getClass().getSimpleName();
    }
    event("TARGET_THROW", "RENEW_GLOBAL_SESSION_IN_RO_MODE\t"
        + error.getClass().getName() + "\t" + observedReason + "\t" + error.getMessage());
  }
  public static void io(String site) throws IOException {
    AtomicInteger counter = ORDINALS.get(site);
    if (counter == null) {
      AtomicInteger created = new AtomicInteger();
      AtomicInteger raced = ORDINALS.putIfAbsent(site, created);
      counter = raced == null ? created : raced;
    }
    int ordinal = counter.incrementAndGet();
    event("IO", site + "\t" + ordinal);
    boolean selected = false;
    if (FAULT_PLAN.length > 0) {
      int next = NEXT_PLAN.get();
      selected = next < FAULT_PLAN.length
          && FAULT_PLAN[next].equals(site + "@@" + ordinal)
          && NEXT_PLAN.compareAndSet(next, next + 1);
    } else {
      selected = site.equals(FAULT_SITE) && ordinal == FAULT_ORDINAL;
    }
    if (selected) {
      event("FAULT_MATCHED", site + "\t" + ordinal);
      event("FAULT_APPLIED", site + "\t" + ordinal);
      throw new IOException("ZOOKEEPER-13 selected I/O fault " + site + " ordinal " + ordinal);
    }
  }
}
