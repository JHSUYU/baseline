package edu.uva.liftlab.graphchecker.runtime;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import edu.uva.liftlab.graphchecker.contract.GapClass;
import edu.uva.liftlab.graphchecker.contract.GapKind;
import edu.uva.liftlab.graphchecker.contract.Endpoint;
import edu.uva.liftlab.graphchecker.contract.OccurrenceAddress;

import java.io.IOException;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.lang.reflect.Constructor;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Fault receipts at actual selected bytecode calls, using GraphChecker identity. */
public final class NativeFaultHooks {
    private static final Object LOCK = new Object();
    private static final Map<String, Integer> ORDINALS = new HashMap<>();
    private static final Map<String, Integer> TARGET_ORDINALS = new HashMap<>();
    private static final List<Fault> PLAN = new ArrayList<>();
    private static boolean initialized;
    private static boolean enabled;
    private static Path events;
    private static long seq;
    private static int nextFault;

    private NativeFaultHooks() { }

    /** Inserted immediately before a statically selected RPC or file I/O call. */
    public static void beforeDoor(String siteId, String exceptionClass) {
        beforeDoor(siteId, exceptionClass, null);
    }

    /** Receives the woven method's owner for an exact recorder call join. */
    public static void beforeDoor(String siteId, String exceptionClass, Object owner) {
        synchronized (LOCK) {
            initialize();
            if (!enabled) return;
            SourceRef source = Attribution.resolve(null);
            if (source == null) {
                RowRuntime.gap(GapKind.LINEAGE_LOST, GapClass.DIAGNOSTIC,
                        siteId, "selected fault door has no physical actor");
                return;
            }
            OccurrenceAddress occurrence = Identity.currentOccurrence(source.key());
            if (occurrence == null || occurrence.lineageLost()
                    || !occurrence.node().render().equals(source.key())) {
                RowRuntime.gap(GapKind.LINEAGE_LOST, GapClass.DIAGNOSTIC,
                        siteId, "selected fault door has no exact current occurrence");
                return;
            }
            String key = siteId + '\n' + source.id() + '\n' + source.epoch();
            int ordinal = ORDINALS.containsKey(key) ? ORDINALS.get(key) + 1 : 1;
            ORDINALS.put(key, ordinal);
            JsonObject fields = identity(siteId, source, occurrence, ordinal,
                    exceptionClass);
            String messageKey = MessageDoors.currentMessagePayloadKey();
            String parentKey = messageKey.isEmpty() ? ""
                    : MessageDoors.messageParentKey(occurrence);
            if (!messageKey.isEmpty()) {
                fields.addProperty("messageReplayKey", messageKey);
                fields.addProperty("messageParentId", parentKey);
            }
            emit("FAULT_DOOR", fields);
            if (Boolean.getBoolean("mallory.gc.nativeFaultDoorContext")) {
                CausynthTraceRecorder.recordNativeFaultDoor(siteId,
                        source.key(), occurrence.id(), ordinal,
                        exceptionClass, owner);
            }
            if (nextFault >= PLAN.size()) return;
            Fault fault = PLAN.get(nextFault);
            if (!fault.matches(siteId, source, ordinal, exceptionClass,
                    messageKey, parentKey)) return;
            Throwable injected = makeException(exceptionClass);
            emit("FAULT_APPLIED", fields);
            nextFault++;
            NativeFaultHooks.<RuntimeException>raise(injected);
        }
    }

    /** Immediately before a statically selected target branch in the same event clock. */
    public static void targetCheck(String siteId) {
        synchronized (LOCK) {
            initialize();
            if (!enabled) return;
            SourceRef source = Attribution.resolve(null);
            if (source == null) {
                RowRuntime.gap(GapKind.LINEAGE_LOST, GapClass.DIAGNOSTIC,
                        siteId, "selected target check has no physical actor");
                return;
            }
            OccurrenceAddress occurrence = Identity.currentOccurrence(source.key());
            if (occurrence == null || occurrence.lineageLost()
                    || !occurrence.node().render().equals(source.key())) {
                RowRuntime.gap(GapKind.LINEAGE_LOST, GapClass.DIAGNOSTIC,
                        siteId, "selected target check has no exact current occurrence");
                return;
            }
            String key = siteId + '\n' + occurrence.id();
            int ordinal = TARGET_ORDINALS.containsKey(key)
                    ? TARGET_ORDINALS.get(key) + 1 : 1;
            TARGET_ORDINALS.put(key, ordinal);
            JsonObject row = new JsonObject();
            row.addProperty("siteId", siteId);
            row.addProperty("targetAnchorSiteId", siteId + "#" + ordinal);
            row.addProperty("node", source.id());
            row.addProperty("actorEpochOrdinal", source.epoch());
            row.addProperty("occurrenceId", occurrence.id());
            row.addProperty("ordinal", ordinal);
            emit("TARGET_CHECK", row);
        }
    }

    /** Observes an explicit ATHROW or the caught exception of one selected call. */
    public static void targetThrow(String siteId, String expectedClass,
                                   Throwable thrown) {
        if (thrown == null || !isType(thrown, expectedClass)) return;
        synchronized (LOCK) {
            initialize();
            if (!enabled) return;
            SourceRef source = Attribution.resolve(null);
            if (source == null) {
                RowRuntime.gap(GapKind.LINEAGE_LOST, GapClass.DIAGNOSTIC,
                        siteId, "selected target throw has no physical actor");
                return;
            }
            OccurrenceAddress occurrence = Identity.currentOccurrence(source.key());
            if (occurrence == null || occurrence.lineageLost()
                    || !occurrence.node().render().equals(source.key())) {
                RowRuntime.gap(GapKind.LINEAGE_LOST, GapClass.DIAGNOSTIC,
                        siteId, "selected target throw has no exact current occurrence");
                return;
            }
            JsonObject row = new JsonObject();
            row.addProperty("siteId", siteId);
            row.addProperty("node", source.id());
            row.addProperty("actorEpochOrdinal", source.epoch());
            row.addProperty("occurrenceId", occurrence.id());
            row.addProperty("exceptionClass", expectedClass);
            row.addProperty("actualExceptionClass", thrown.getClass().getName());
            emit("TARGET_THROW", row);
        }
    }

    /** Called only after the original session accepts an export or attach row. */
    private static void endpointPublished(String kind, String sessionId,
                                          Endpoint endpoint, Endpoint producer,
                                          long nativeVmEventId) {
        synchronized (LOCK) {
            initialize();
            if (!enabled || endpoint == null) return;
            SourceRef source = Attribution.resolve(null);
            OccurrenceAddress occurrence = source == null ? null
                    : Identity.currentOccurrence(source.key());
            if (source == null || occurrence == null || occurrence.lineageLost()
                    || !source.key().equals(endpoint.occurrence().node().render())
                    || !occurrence.id().equals(endpoint.occurrence().id())) {
                RowRuntime.gap(GapKind.LINEAGE_LOST, GapClass.DIAGNOSTIC,
                        endpoint.id(), "accepted endpoint lacks matching physical actor"
                                + " and exact current occurrence for fault receipt");
                return;
            }
            JsonObject row = new JsonObject();
            row.addProperty("sessionId", sessionId);
            row.addProperty("endpointId", endpoint.id());
            row.addProperty("producerEndpointId", producer == null ? ""
                    : producer.id());
            row.addProperty("node", source.id());
            row.addProperty("actorEpochOrdinal", source.epoch());
            row.addProperty("occurrenceId", occurrence.id());
            row.addProperty("nativeVmEventId", nativeVmEventId);
            emit(kind, row);
        }
    }

    private static boolean isType(Throwable thrown, String expectedClass) {
        for (Class<?> type = thrown.getClass(); type != null;
                type = type.getSuperclass()) {
            if (type.getName().equals(expectedClass)) return true;
        }
        return false;
    }

    private static JsonObject identity(String siteId, SourceRef source,
                                       OccurrenceAddress occurrence, int ordinal,
                                       String exceptionClass) {
        JsonObject row = new JsonObject();
        row.addProperty("siteId", siteId);
        row.addProperty("node", source.id());
        row.addProperty("actorEpochOrdinal", source.epoch());
        row.addProperty("occurrenceId", occurrence.id());
        row.addProperty("ordinal", ordinal);
        row.addProperty("exceptionClass", exceptionClass);
        return row;
    }

    private static void initialize() {
        if (initialized) return;
        initialized = true;
        String planName = System.getenv("MALLORY_NATIVE_FAULT_PLAN");
        String eventName = System.getenv("MALLORY_NATIVE_FAULT_EVENTS");
        if ((planName == null || planName.isEmpty())
                && (eventName == null || eventName.isEmpty())) return;
        if (planName == null || planName.isEmpty()
                || eventName == null || eventName.isEmpty()) {
            throw new IllegalStateException("native fault plan and events must be paired");
        }
        events = Paths.get(eventName).toAbsolutePath();
        try {
            JsonObject input = new JsonParser().parse(new String(Files.readAllBytes(
                    Paths.get(planName)), StandardCharsets.UTF_8)).getAsJsonObject();
            JsonArray faults = input.getAsJsonArray("faults");
            if (faults == null) throw new IllegalArgumentException("missing faults array");
            for (JsonElement item : faults) PLAN.add(Fault.from(item.getAsJsonObject()));
            Path parent = events.getParent();
            if (parent != null) Files.createDirectories(parent);
            enabled = true;
            RowRuntime.setEndpointObserver(new RowRuntime.EndpointObserver() {
                @Override public void afterExport(String sessionId,
                                                  Endpoint endpoint,
                                                  long nativeVmEventId) {
                    endpointPublished("ENDPOINT_EXPORT", sessionId, endpoint,
                            null, nativeVmEventId);
                }

                @Override public void afterAttach(String sessionId,
                                                  Endpoint endpoint,
                                                  Endpoint producer,
                                                  long nativeVmEventId) {
                    endpointPublished("ENDPOINT_ATTACH", sessionId, endpoint,
                            producer, nativeVmEventId);
                }
            });
        } catch (IOException | RuntimeException failure) {
            throw new IllegalStateException("invalid native fault plan", failure);
        }
    }

    private static void emit(String kind, JsonObject fields) {
        JsonObject row = new JsonObject();
        row.addProperty("kind", kind);
        row.addProperty("seq", ++seq);
        for (Map.Entry<String, JsonElement> entry : fields.entrySet()) {
            row.add(entry.getKey(), entry.getValue());
        }
        // Workload shutdown may interrupt a thread while it emits a door.
        // A channel opened by Files.write closes on interrupt and can turn
        // that harmless teardown event into a workload exception. The
        // receipt lock already serializes writers in this JVM.
        try (OutputStream out = new FileOutputStream(events.toFile(), true)) {
            out.write((row.toString() + "\n").getBytes(StandardCharsets.UTF_8));
        } catch (IOException failure) {
            throw new IllegalStateException("cannot publish native fault receipt", failure);
        }
    }

    private static Throwable makeException(String name) {
        try {
            Class<?> type = Class.forName(name);
            if (!Throwable.class.isAssignableFrom(type)) {
                throw new IllegalArgumentException("fault type is not Throwable: " + name);
            }
            try {
                Constructor<?> ctor = type.getDeclaredConstructor(String.class);
                ctor.setAccessible(true);
                return (Throwable) ctor.newInstance("Mallory injected at native fault door");
            } catch (NoSuchMethodException absent) {
                Constructor<?> ctor = type.getDeclaredConstructor();
                ctor.setAccessible(true);
                return (Throwable) ctor.newInstance();
            }
        } catch (ReflectiveOperationException failure) {
            throw new IllegalArgumentException("cannot instantiate fault type " + name, failure);
        }
    }

    @SuppressWarnings("unchecked")
    private static <E extends Throwable> void raise(Throwable failure) throws E {
        throw (E) failure;
    }

    private static final class Fault {
        private final String siteId;
        private final String node;
        private final long epoch;
        private final int ordinal;
        private final String exceptionClass;
        private final String messageReplayKey;
        private final String messageParentId;

        private Fault(String siteId, String node, long epoch, int ordinal,
                      String exceptionClass, String messageReplayKey,
                      String messageParentId) {
            this.siteId = siteId;
            this.node = node;
            this.epoch = epoch;
            this.ordinal = ordinal;
            this.exceptionClass = exceptionClass;
            this.messageReplayKey = messageReplayKey;
            this.messageParentId = messageParentId;
        }

        private static Fault from(JsonObject row) {
            String site = required(row, "siteId");
            String node = required(row, "node");
            String exception = required(row, "exceptionClass");
            long epoch = row.get("actorEpochOrdinal").getAsLong();
            int ordinal = row.get("ordinal").getAsInt();
            if (epoch < 0 || ordinal < 1) throw new IllegalArgumentException(
                    "invalid native fault epoch or ordinal");
            String messageKey = optionalDigest(row, "messageReplayKey");
            String parentKey = optionalDigest(row, "messageParentId");
            if (messageKey.isEmpty() != parentKey.isEmpty()) {
                throw new IllegalArgumentException("native payload key and parent must pair");
            }
            return new Fault(site, node, epoch, ordinal, exception,
                    messageKey, parentKey);
        }

        private static String optionalDigest(JsonObject row, String field) {
            if (!row.has(field)) return "";
            String value = required(row, field);
            if (!value.matches("[0-9a-f]{64}")) {
                throw new IllegalArgumentException("invalid native " + field);
            }
            return value;
        }

        private static String required(JsonObject row, String field) {
            if (!row.has(field) || !row.get(field).isJsonPrimitive()) {
                throw new IllegalArgumentException("missing native fault " + field);
            }
            String value = row.get(field).getAsString();
            if (value.isEmpty()) throw new IllegalArgumentException(
                    "empty native fault " + field);
            return value;
        }

        private boolean matches(String site, SourceRef source, int eventOrdinal,
                                String exception, String messageKey,
                                String parentKey) {
            if (!siteId.equals(site) || !exceptionClass.equals(exception)) return false;
            if (!messageReplayKey.isEmpty()) {
                return messageReplayKey.equals(messageKey)
                        && messageParentId.equals(parentKey);
            }
            return node.equals(source.id()) && epoch == source.epoch()
                    && ordinal == eventOrdinal;
        }
    }
}
