package edu.uva.liftlab.mallory.graphchecker.weave;

import edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.ConcurrentHashMap;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;

/** Small verifier-safe methods called by woven application bytecode. */
public final class TraceHooks {
    private static final AtomicLong TOKENS = new AtomicLong();
    private static final ThreadLocal<Deque<Entry>> REGIONS =
            ThreadLocal.withInitial(ArrayDeque::new);
    private static volatile Method oldProbe;
    private static volatile Method nativeDoorContext;
    private static final ConcurrentHashMap<String, Boolean> STATE_GAPS =
            new ConcurrentHashMap<>();
    private static final AtomicInteger STATE_GAP_COUNT = new AtomicInteger();
    private static final int MAX_STATE_GAPS = 256;
    private static final ConcurrentHashMap<String, Boolean> PREINIT_GAPS =
            new ConcurrentHashMap<>();
    private static final AtomicInteger PREINIT_GAP_COUNT = new AtomicInteger();

    private TraceHooks() { }

    public static long regionEnter(String regionId, String method, Object receiver) {
        long token = TOKENS.incrementAndGet();
        boolean active = MessageDoors.tryEnterRegion(regionId, method,
                (int) Math.min(token, Integer.MAX_VALUE), receiver);
        REGIONS.get().push(new Entry(token, regionId, active));
        return token;
    }

    /** Open a region without putting a wide token local in application bytecode. */
    public static void regionOpen(String regionId, String method, Object receiver) {
        regionEnter(regionId, method, receiver);
    }

    /** Close the innermost activation, including recursive activations of this region. */
    public static void regionClose(String regionId) {
        Deque<Entry> open = REGIONS.get();
        if (open.isEmpty() || !open.peek().regionId.equals(regionId)) {
            MessageDoors.gap("REGION_UNBALANCED", regionId,
                    "region exit did not match innermost entry");
            return;
        }
        regionExit(open.peek().token);
    }

    public static void regionExit(long token) {
        if (token == 0) return;
        Deque<Entry> open = REGIONS.get();
        if (open.isEmpty() || open.peek().token != token) {
            MessageDoors.gap("REGION_UNBALANCED", String.valueOf(token),
                    "region exit did not match innermost entry");
            return;
        }
        Entry ended = open.pop();
        if (ended.active) MessageDoors.exitRegion(ended.regionId);
        if (open.isEmpty()) REGIONS.remove();
    }

    public static void coverage(String siteId, Object receiver) {
        MessageDoors.coverage(siteId, receiver);
    }

    public static void branch(String siteId, Object receiver, boolean outcome) {
        MessageDoors.branch(siteId, receiver, outcome);
    }

    public static void stateAccessGap(String siteId, String access, String field) {
        if (STATE_GAPS.putIfAbsent(siteId + "\n" + access + "\n" + field,
                Boolean.TRUE) != null) return;
        int seen = STATE_GAP_COUNT.incrementAndGet();
        if (seen > MAX_STATE_GAPS) {
            if (seen == MAX_STATE_GAPS + 1) {
                MessageDoors.gap("STATE_ACCESS_UNHOOKED_TRUNCATED", "stateCandidates",
                        "more than " + MAX_STATE_GAPS + " distinct sites executed");
            }
            return;
        }
        MessageDoors.gap("STATE_ACCESS_UNHOOKED", siteId, access + " " + field);
    }

    public static void preInitGap(String siteId, String kind) {
        if (PREINIT_GAPS.putIfAbsent(kind + "\n" + siteId, Boolean.TRUE) != null) return;
        int seen = PREINIT_GAP_COUNT.incrementAndGet();
        if (seen == MAX_STATE_GAPS + 1) {
            MessageDoors.gap("PREINIT_HOOK_UNATTRIBUTED_TRUNCATED", "constructors",
                    "more than " + MAX_STATE_GAPS + " distinct selected pre-init sites");
        } else if (seen <= MAX_STATE_GAPS) {
            MessageDoors.gap("PREINIT_HOOK_UNATTRIBUTED", siteId,
                    kind + " runs before this/super constructor completion");
        }
    }

    public static void enterCall(String siteId, int ordinal) {
        MessageDoors.enterCall(siteId, ordinal);
    }

    public static void exitCall(String siteId) {
        MessageDoors.exitCall(siteId);
    }

    /** Opaque receipt survives a request/tick scope change inside the call. */
    public static Object openCall(String siteId, int ordinal) {
        return MessageDoors.openCall(siteId, ordinal);
    }

    public static void closeCall(Object receipt, String siteId) {
        MessageDoors.closeCall(receipt, siteId);
    }

    public static void faultDoor(String siteId, Object owner, String exceptionClass,
                                 int controller) {
        MessageDoors.FaultDoorHit hit = MessageDoors.faultDoorHit(siteId, owner);
        if (hit != null && Boolean.getBoolean("mallory.gc.nativeFaultDoorContext")) {
            recordNativeDoorContext(hit, exceptionClass, owner);
        }
        if (controller == 0) return;
        if (controller == 2) {
            Throwable injected = GcFaultPlan.current().consume(hit, exceptionClass);
            if (injected != null) {
                MessageDoors.faultApplied(hit, exceptionClass);
                sneakyThrow(injected);
            }
            return;
        }
        if (controller != 1) throw new IllegalArgumentException("unknown fault controller " + controller);
        try {
            Method method = oldProbe;
            if (method == null) {
                synchronized (TraceHooks.class) {
                    method = oldProbe;
                    if (method == null) {
                        Class<?> probe = Class.forName(
                                "edu.uva.liftlab.mallory.instrumentation.Probe");
                        method = probe.getMethod("beforeDoor", String.class, String.class);
                        oldProbe = method;
                    }
                }
            }
            method.invoke(null, siteId, exceptionClass);
        } catch (InvocationTargetException invoked) {
            sneakyThrow(invoked.getCause());
        } catch (ReflectiveOperationException missing) {
            throw new IllegalStateException("MALLORY_PROBE controller is unavailable", missing);
        }
    }

    /**
     * Opt-in identity bridge between the native GraphChecker door receipt and
     * the original recorder's active call.  The recorder checks receiver
     * identity itself; an unrelated enclosing call is never attributed to a
     * door.  Reflection keeps the weave runtime usable without the original
     * recorder on its classpath, while the opt-in fails closed if it is absent.
     */
    private static void recordNativeDoorContext(MessageDoors.FaultDoorHit hit,
                                                String exceptionClass, Object owner) {
        try {
            Method method = nativeDoorContext;
            if (method == null) {
                synchronized (TraceHooks.class) {
                    method = nativeDoorContext;
                    if (method == null) {
                        Class<?> recorder = Class.forName(
                                "edu.uva.liftlab.graphchecker.runtime.CausynthTraceRecorder");
                        method = recorder.getMethod("recordNativeFaultDoor",
                                String.class, String.class, String.class,
                                long.class, String.class, Object.class);
                        nativeDoorContext = method;
                    }
                }
            }
            method.invoke(null, hit.siteId, hit.node, hit.occurrenceId,
                    hit.ordinal, exceptionClass, owner);
        } catch (InvocationTargetException failed) {
            throw new IllegalStateException("original recorder rejected native fault door context",
                    failed.getCause());
        } catch (ReflectiveOperationException missing) {
            throw new IllegalStateException("native fault door context bridge is unavailable",
                    missing);
        }
    }

    @SuppressWarnings("unchecked")
    private static <E extends Throwable> void sneakyThrow(Throwable failure) throws E {
        throw (E) failure;
    }

    public static void targetCheck(String siteId, Object receiver, String outcome) {
        MessageDoors.targetCheck(siteId, receiver, outcome);
    }

    public static void targetThrow(String siteId, Object receiver,
                                   String expectedClass, Throwable thrown) {
        if (thrown == null) return;
        if (expectedClass != null && !expectedClass.isEmpty()
                && !isType(thrown, expectedClass)) return;
        MessageDoors.targetThrow(siteId, receiver, thrown);
    }

    private static boolean isType(Throwable thrown, String className) {
        for (Class<?> type = thrown.getClass(); type != null; type = type.getSuperclass()) {
            if (type.getName().equals(className)) return true;
        }
        return false;
    }

    private static final class Entry {
        final long token;
        final String regionId;
        final boolean active;
        Entry(long token, String regionId, boolean active) {
            this.token = token;
            this.regionId = regionId;
            this.active = active;
        }
    }
}
