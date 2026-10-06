package zk10;

import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Queue;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/** Case-local runtime recorder. No GraphChecker classes or static skeleton input. */
public final class Probe {
  private static final Set<String> LINES = Collections.newSetFromMap(new ConcurrentHashMap<String, Boolean>());
  private static final ConcurrentLinkedQueue<String> EVENTS = new ConcurrentLinkedQueue<String>();
  private static final ConcurrentHashMap<String, AtomicInteger> ORDINALS = new ConcurrentHashMap<String, AtomicInteger>();
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final AtomicLong GUARD_COUNT = new AtomicLong();
  private static final AtomicLong NORMAL_COUNT = new AtomicLong();
  private static final AtomicLong THROW_ARM_COUNT = new AtomicLong();
  private static final AtomicInteger APPLIED_COUNT = new AtomicInteger();
  private static final AtomicInteger LAST_GUARD_AFTER_APPLIED = new AtomicInteger();
  private static final String[] PLAN = System.getProperty("zk10.fault.plan", "").isEmpty()
      ? new String[0] : System.getProperty("zk10.fault.plan").split("\\|\\|\\|");
  private static final AtomicInteger NEXT = new AtomicInteger();

  static {
    Runtime.getRuntime().addShutdownHook(new Thread(() -> {
      try {
        event("TARGET_SUMMARY", "total=" + GUARD_COUNT.get() + "\tnormal="
            + NORMAL_COUNT.get() + "\tthrow_arm=" + THROW_ARM_COUNT.get());
        ArrayList<String> lines = new ArrayList<String>(LINES);
        Collections.sort(lines);
        Files.write(Paths.get(System.getProperty("zk10.lines.output")), lines, StandardCharsets.UTF_8);
        Files.write(Paths.get(System.getProperty("zk10.events.output")),
            new ArrayList<String>(EVENTS), StandardCharsets.UTF_8);
      } catch (Throwable problem) {
        problem.printStackTrace();
      }
    }, "zk10-probe-flush"));
  }

  public static void line(String clazz, String method, int number) {
    LINES.add(clazz + "\t" + method + "\t" + number);
  }

  private static void event(String kind, String detail) {
    EVENTS.add(SEQUENCE.incrementAndGet() + "\t" + kind + "\t"
        + Thread.currentThread().getName() + "\t" + detail);
  }

  private static Object field(Object object, String name) {
    if (object == null) return null;
    for (Class<?> c = object.getClass(); c != null; c = c.getSuperclass()) {
      try {
        Field f = c.getDeclaredField(name);
        f.setAccessible(true);
        return f.get(object);
      } catch (Throwable ignored) {
        // Search the owning superclass.
      }
    }
    return null;
  }

  private static String sourceKey(Object actor, Object resource) {
    String peer = "unknown";
    String item = resource == null ? "" : String.valueOf(resource);
    if (actor != null) {
      try {
        Object qp = actor.getClass().getName().equals("org.apache.zookeeper.server.quorum.QuorumPeer")
            ? actor : field(actor, "self");
        if (qp != null) {
          Method id = qp.getClass().getMethod("getMyId");
          peer = String.valueOf(id.invoke(qp));
        } else if (actor.getClass().getSimpleName().equals("LearnerHandler")) {
          peer = String.valueOf(field(actor, "sid"));
        } else if (actor.getClass().getSimpleName().equals("SyncRequestProcessor")) {
          Object server = field(actor, "zks");
          if (server != null) {
            peer = String.valueOf(server.getClass().getMethod("getServerId").invoke(server));
          }
        }
      } catch (Throwable ignored) {
        peer = "unknown";
      }
    }
    return "peer=" + peer + (item.isEmpty() ? "" : "/" + item);
  }

  private static String proposedHead(Object master) {
    try {
      Object queue = field(master, "proposedPkts");
      Object head = ((Queue<?>) queue).peek();
      if (head == null) return "none";
      return "0x" + Long.toHexString((Long) head.getClass().getMethod("getZxid").invoke(head));
    } catch (Throwable ignored) {
      return "unknown";
    }
  }

  public static void guard(int comparison, Object master, long committedZxid) {
    long count = GUARD_COUNT.incrementAndGet();
    if (comparison == 0) NORMAL_COUNT.incrementAndGet();
    else THROW_ARM_COUNT.incrementAndGet();
    int applied = APPLIED_COUNT.get();
    boolean firstAfterFault = false;
    if (applied > LAST_GUARD_AFTER_APPLIED.get()) {
      int before = LAST_GUARD_AFTER_APPLIED.getAndSet(applied);
      firstAfterFault = applied > before;
    }
    if (comparison != 0 || firstAfterFault || count <= 2
        || (count & (count - 1)) == 0 || count % 128 == 0) {
      event("TARGET_GUARD", (comparison != 0 ? "THROW_ARM" : "NORMAL_ARM")
          + "\t" + sourceKey(master, null) + "\tcommit=0x" + Long.toHexString(committedZxid)
          + "\tproposed=" + proposedHead(master) + "\tcomparison=" + comparison);
    }
  }

  public static void targetThrow(Object master) {
    event("TARGET_THROW", "Unexpected proposal packet on commit ack\t" + sourceKey(master, null));
  }

  public static void io(String site, Object actor, Object resource) throws IOException {
    String key = sourceKey(actor, resource);
    String identity = site + "@@" + key;
    AtomicInteger count = ORDINALS.get(identity);
    if (count == null) {
      AtomicInteger created = new AtomicInteger();
      AtomicInteger raced = ORDINALS.putIfAbsent(identity, created);
      count = raced == null ? created : raced;
    }
    int ordinal = count.incrementAndGet();
    String selector = identity + "@@" + ordinal;
    if (ordinal <= 2 || (ordinal & (ordinal - 1)) == 0 || ordinal % 128 == 0) {
      event("IO", site + "\t" + key + "\t" + ordinal);
    }
    int position = NEXT.get();
    if (position < PLAN.length && selector.equals(PLAN[position])
        && NEXT.compareAndSet(position, position + 1)) {
      event("FAULT_MATCHED", site + "\t" + key + "\t" + ordinal + "\t" + position);
      event("FAULT_APPLIED", site + "\t" + key + "\t" + ordinal + "\t" + position);
      APPLIED_COUNT.incrementAndGet();
      throw new IOException("ZOOKEEPER-10 selected I/O fault " + selector);
    }
  }
}
