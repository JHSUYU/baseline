package zk05;

import java.io.IOException;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
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

/** Case-local runtime recorder. No GraphChecker classes or static skeleton input. */
public final class Probe {
  private static final Set<String> LINES = Collections.newSetFromMap(new ConcurrentHashMap<String, Boolean>());
  private static final ConcurrentLinkedQueue<String> EVENTS = new ConcurrentLinkedQueue<String>();
  private static final ConcurrentHashMap<String, AtomicInteger> ORDINALS = new ConcurrentHashMap<String, AtomicInteger>();
  private static final AtomicLong SEQUENCE = new AtomicLong();
  private static final String[] PLAN = System.getProperty("zk05.fault.plan", "").isEmpty()
      ? new String[0] : System.getProperty("zk05.fault.plan").split("\\|\\|\\|");
  private static final AtomicInteger NEXT = new AtomicInteger();

  static {
    Runtime.getRuntime().addShutdownHook(new Thread(() -> {
      try {
        ArrayList<String> lines = new ArrayList<String>(LINES);
        Collections.sort(lines);
        Files.write(Paths.get(System.getProperty("zk05.lines.output")), lines, StandardCharsets.UTF_8);
        Files.write(Paths.get(System.getProperty("zk05.events.output")),
            new ArrayList<String>(EVENTS), StandardCharsets.UTF_8);
      } catch (Throwable problem) {
        problem.printStackTrace();
      }
    }, "zk05-probe-flush"));
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
    if (actor != null) {
      try {
        Object qp = actor.getClass().getName().equals("org.apache.zookeeper.server.quorum.QuorumPeer")
            ? actor : field(actor, "self");
        if (qp != null) {
          Method id = qp.getClass().getMethod("getMyId");
          peer = String.valueOf(id.invoke(qp));
        } else if (actor.getClass().getSimpleName().equals("LearnerHandler")) {
          peer = String.valueOf(field(actor, "sid"));
        }
      } catch (Throwable ignored) {
        peer = "unknown";
      }
    }
    String item = resource == null ? "" : String.valueOf(resource);
    return "peer=" + peer + (item.isEmpty() ? "" : "/" + item);
  }

  public static void guard(int comparison, Object follower) {
    event("TARGET_GUARD", (comparison < 0 ? "THROW_ARM" : "NORMAL_ARM")
        + "\t" + sourceKey(follower, null));
  }

  public static void targetThrow(Object follower) {
    event("TARGET_THROW", "Error: Epoch of leader is lower\t" + sourceKey(follower, null));
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
    event("IO", site + "\t" + key + "\t" + ordinal);
    int position = NEXT.get();
    if (position < PLAN.length && selector.equals(PLAN[position])
        && NEXT.compareAndSet(position, position + 1)) {
      event("FAULT_MATCHED", site + "\t" + key + "\t" + ordinal + "\t" + position);
      event("FAULT_APPLIED", site + "\t" + key + "\t" + ordinal + "\t" + position);
      throw new IOException("ZOOKEEPER-05 selected I/O fault " + selector);
    }
  }
}
