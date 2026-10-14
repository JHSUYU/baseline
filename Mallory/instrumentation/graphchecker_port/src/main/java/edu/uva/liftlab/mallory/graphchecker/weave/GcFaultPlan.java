package edu.uva.liftlab.mallory.graphchecker.weave;

import com.google.gson.Gson;
import edu.uva.liftlab.mallory.graphchecker.runtime.MessageDoors;
import java.io.IOException;
import java.io.Reader;
import java.lang.reflect.Constructor;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;

/** One trial's ordered fault sequence, addressed only by observed GC door identity. */
final class GcFaultPlan {
    private static volatile GcFaultPlan current;
    private final List<Fault> faults;
    private int next;

    private GcFaultPlan(List<Fault> faults) { this.faults = faults; }

    static GcFaultPlan current() {
        GcFaultPlan plan = current;
        if (plan != null) return plan;
        synchronized (GcFaultPlan.class) {
            plan = current;
            if (plan == null) current = plan = load();
        }
        return plan;
    }

    private static GcFaultPlan load() {
        String location = System.getProperty("mallory.gc.fault.plan");
        if (location == null || location.isEmpty()) location = System.getenv("MALLORY_GC_FAULT_PLAN");
        if (location == null || location.isEmpty()) {
            throw new IllegalStateException("MALLORY_GC_FAULT_PLAN is required by the native fault controller");
        }
        Path path = Paths.get(location);
        try (Reader reader = Files.newBufferedReader(path, StandardCharsets.UTF_8)) {
            FilePlan parsed = new Gson().fromJson(reader, FilePlan.class);
            if (parsed == null || parsed.faults == null) {
                throw new IllegalArgumentException("fault plan needs a faults array: " + path);
            }
            for (int index = 0; index < parsed.faults.size(); index++) {
                Fault fault = parsed.faults.get(index);
                if (fault == null || empty(fault.siteId) || empty(fault.node)
                        || (empty(fault.occurrenceId) && empty(fault.replayOccurrenceId))
                        || fault.ordinal == null
                        || fault.ordinal < 1 || empty(fault.exceptionClass)) {
                    throw new IllegalArgumentException("incomplete fault " + index + " in " + path);
                }
                if ((fault.messageReplayKey != null || fault.messageParentId != null)
                        && (empty(fault.messageReplayKey) || empty(fault.messageParentId)
                        || !fault.messageReplayKey.matches("[0-9a-f]{64}")
                        || !fault.messageParentId.matches("[0-9a-f]{64}"))) {
                    throw new IllegalArgumentException("invalid message replay identity "
                            + index + " in " + path);
                }
            }
            return new GcFaultPlan(parsed.faults);
        } catch (IOException e) {
            throw new IllegalStateException("cannot read native fault plan " + path, e);
        }
    }

    /** Returns one exception when this hit is exactly the next ordered fault. */
    synchronized Throwable consume(MessageDoors.FaultDoorHit hit, String doorExceptionClass) {
        if (hit == null || next >= faults.size()) return null;
        Fault fault = faults.get(next);
        if (!fault.siteId.equals(hit.siteId)) return null;
        if (!empty(fault.messageReplayKey)) {
            // The post-run verifier rejects a second matching door. The
            // serialized message and structural causal parent are the only
            // permitted cross-actor selector; ordinal is provenance only.
            if (!fault.messageReplayKey.equals(hit.messageReplayKey)
                    || !fault.messageParentId.equals(hit.messageParentId)) return null;
        } else {
            if (!fault.node.equals(hit.node)
                    || fault.ordinal.longValue() != hit.ordinal) return null;
            // Replay selection survives trial-specific RPC correlation IDs.
            if (!empty(fault.replayOccurrenceId)) {
                if (!fault.replayOccurrenceId.equals(hit.replayOccurrenceId)) return null;
            } else if (!fault.occurrenceId.equals(hit.occurrenceId)) return null;
        }
        if (!fault.exceptionClass.equals(doorExceptionClass)) {
            throw new IllegalStateException("fault exception class differs from selected door "
                    + hit.siteId + ": " + fault.exceptionClass + " != " + doorExceptionClass);
        }
        Throwable injected = instantiate(fault.exceptionClass);
        next++;
        return injected;
    }

    private static Throwable instantiate(String className) {
        try {
            ClassLoader loader = Thread.currentThread().getContextClassLoader();
            Class<?> type = Class.forName(className, true, loader);
            if (!Throwable.class.isAssignableFrom(type)) {
                throw new IllegalArgumentException("fault is not Throwable: " + className);
            }
            try {
                Constructor<?> constructor = type.getConstructor(String.class);
                return (Throwable) constructor.newInstance("Mallory injected at GraphChecker fault door");
            } catch (NoSuchMethodException unavailable) {
                Constructor<?> constructor = type.getConstructor();
                return (Throwable) constructor.newInstance();
            }
        } catch (ReflectiveOperationException e) {
            throw new IllegalArgumentException("cannot instantiate fault exception " + className, e);
        }
    }

    private static boolean empty(String value) { return value == null || value.isEmpty(); }

    private static final class FilePlan { List<Fault> faults; }
    private static final class Fault {
        String siteId;
        String node;
        String occurrenceId;
        String replayOccurrenceId;
        String messageReplayKey;
        String messageParentId;
        Long ordinal;
        String exceptionClass;
    }
}
