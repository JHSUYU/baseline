package edu.uva.liftlab.mallory.graphchecker.runtime;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import edu.uva.liftlab.mallory.graphchecker.contract.CausalContext;
import edu.uva.liftlab.mallory.graphchecker.contract.Endpoint;
import edu.uva.liftlab.mallory.graphchecker.contract.OccurrenceAddress;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * The GraphChecker message-door contract ported into Mallory's JUnit runtime.
 * A prepared message is not a SEND. Its successful transport completion, or
 * the corresponding actual inbound in the same JVM, confirms the SEND.
 * Correlation and attempt are checked against the transported envelope.
 */
public final class MessageDoors {
    public static final String REQUEST = "REQUEST";
    public static final String RESPONSE = "RESPONSE";

    private static final Map<String, Outbound> PREPARED = new ConcurrentHashMap<>();
    private static final Map<String, List<Endpoint>> STORED = new ConcurrentHashMap<>();
    private static final ThreadLocal<Inbound> CURRENT = new ThreadLocal<>();
    private static final ThreadLocal<String> NOTIFIED = new ThreadLocal<>();
    private static final ThreadLocal<ReadHandoff> LAST_NOTIFIED_READ = new ThreadLocal<>();
    private static final AtomicLong EXCHANGES = new AtomicLong();
    private static final Map<String, AtomicLong> DOOR_ORDINALS = new ConcurrentHashMap<>();
    // Coverage feedback is a set of sites per causal occurrence. Repeated
    // execution of one block in a polling loop adds no coverage information.
    private static final Map<String, Boolean> COVERAGE_SEEN = new ConcurrentHashMap<>();

    private MessageDoors() { }

    public static void startRecording() {
        TraceRows.row("WINDOW_OPEN", null, null);
    }

    public static void stopRecording() {
        TraceRows.row("WINDOW_CLOSE", null, null);
    }

    public static void registerSource(Object anchor, String kind, String role,
                                      String sourceId, long epoch) {
        TraceRows.register(anchor, new SourceRef(kind, role, sourceId, epoch));
    }

    public static void registerSourceAlias(Object alias, Object anchor) {
        TraceRows.alias(alias, anchor);
    }

    public static void registerCurrentSourceAlias(Object alias) {
        TraceRows.currentAlias(alias);
    }

    /** Stable logical source identity in the current request/tick scope. */
    public static String currentSourceKey() {
        return TraceRows.currentSourceKey();
    }

    public static void registerNode(Object anchor, String kind, String role,
                                    String sourceId, Object... aliases) {
        registerSource(anchor, kind, role, sourceId, 0L);
        if (aliases != null) for (Object alias : aliases) {
            if (alias != null && alias != anchor) registerSourceAlias(alias, anchor);
        }
    }

    public static void restartSource(Object anchor, String kind, String role,
                                     String sourceId, long epoch) {
        TraceRows.restart(anchor, new SourceRef(kind, role, sourceId, epoch));
    }

    public static long beginRequest(Object source, String api) {
        endInbound();
        return TraceRows.begin(source, api, true);
    }

    public static void endRequest(long request, String api) {
        endInbound();
        TraceRows.end(request);
    }

    public static long beginTick(Object owner, String role) {
        return TraceRows.begin(owner, role, true);
    }

    public static void endTick(long token) { TraceRows.end(token); }

    public static void enterRegion(String regionId, String callSite,
                                   int iteration) {
        TraceRows.enterRegion(regionId, callSite, iteration);
    }

    public static void enterRegion(String regionId, String callSite,
                                   int iteration, Object owner) {
        TraceRows.enterRegion(regionId, callSite, iteration, owner);
    }

    /** Whether an attributed region was actually activated by this call. */
    public static boolean tryEnterRegion(String regionId, String callSite,
                                         int iteration, Object owner) {
        return TraceRows.enterRegion(regionId, callSite, iteration, owner);
    }

    public static void exitRegion(String regionId) {
        TraceRows.exitRegion(regionId);
    }

    public static void enterCall(String siteId, int iteration) {
        TraceRows.enterCall(siteId, iteration);
    }

    public static void exitCall(String siteId) {
        TraceRows.exitCall(siteId);
    }

    /** Correlate a call exit with its entry across request-scope restores. */
    public static Object openCall(String siteId, int iteration) {
        return TraceRows.openCall(siteId, iteration);
    }

    public static void closeCall(Object receipt, String siteId) {
        TraceRows.closeCall(receipt, siteId);
    }

    public static void targetCheck(String siteId, Object owner,
                                   String outcome) {
        OccurrenceAddress occurrence = TraceRows.occurrence(owner);
        TraceRows.row("TARGET_CHECK", occurrence,
                TraceRows.fields("siteId", siteId, "outcome", outcome));
    }

    public static void targetThrow(String siteId, Object owner,
                                   Throwable thrown) {
        OccurrenceAddress occurrence = TraceRows.occurrence(owner);
        TraceRows.row("TARGET_THROW", occurrence,
                TraceRows.fields("siteId", siteId, "exceptionClass",
                        thrown == null ? "" : thrown.getClass().getName()));
    }

    public static void coverage(String siteId, Object owner) {
        if (empty(siteId)) {
            gap("COVERAGE_SITE_MISSING", "coverage", "site id is empty");
            return;
        }
        coverageOnce(siteId, owner, TraceRows.fields("siteId", siteId));
    }

    public static void branch(String siteId, Object owner, boolean outcome) {
        if (empty(siteId)) {
            gap("COVERAGE_SITE_MISSING", "branch", "site id is empty");
            return;
        }
        String branchId = "branch:" + siteId + ":" + outcome;
        coverageOnce(branchId, owner,
                TraceRows.fields("siteId", branchId,
                        "branchSiteId", siteId, "outcome", outcome));
    }

    private static void coverageOnce(String siteId, Object owner,
                                     JsonObject values) {
        OccurrenceAddress occurrence = TraceRows.hasAttributedScope(owner)
                ? TraceRows.occurrence(owner) : null;
        String context = occurrence == null ? "UNATTRIBUTED" : occurrence.id();
        if (COVERAGE_SEEN.putIfAbsent(context + "\n" + siteId,
                Boolean.TRUE) != null) return;
        if (occurrence == null) {
            TraceRows.gap("COVERAGE_UNATTRIBUTED", siteId,
                    "no registered source and root scope");
        }
        TraceRows.row("COVERAGE", occurrence, values);
    }

    public static void faultDoor(String siteId, Object owner, long ordinal) {
        if (empty(siteId) || ordinal < 1) {
            gap("FAULT_DOOR_IDENTITY_MISSING", siteId, String.valueOf(ordinal));
            return;
        }
        TraceRows.row("FAULT_DOOR", TraceRows.occurrence(owner),
                TraceRows.fields("siteId", siteId, "doorOrdinal", ordinal));
    }

    public static void faultDoor(String siteId, Object owner) {
        faultDoorHit(siteId, owner);
    }

    /** An exact observed door instance for matching one ordered fault plan. */
    public static final class FaultDoorHit {
        public final String occurrenceId;
        public final String node;
        public final String siteId;
        public final long ordinal;
        private final OccurrenceAddress occurrence;

        private FaultDoorHit(OccurrenceAddress occurrence, String siteId,
                             long ordinal) {
            this.occurrence = occurrence;
            this.occurrenceId = occurrence.id();
            this.node = occurrence.node().render();
            this.siteId = siteId;
            this.ordinal = ordinal;
        }
    }

    public static FaultDoorHit faultDoorHit(String siteId, Object owner) {
        if (empty(siteId)) {
            gap("FAULT_DOOR_IDENTITY_MISSING", "fault door", "site id is empty");
            return null;
        }
        if (!TraceRows.hasAttributedScope(owner)) {
            gap("FAULT_DOOR_UNATTRIBUTED", siteId, "no registered source and root scope");
            return null;
        }
        OccurrenceAddress occurrence = TraceRows.occurrence(owner);
        if (occurrence == null) {
            gap("FAULT_DOOR_UNATTRIBUTED", siteId, "occurrence not formed");
            return null;
        }
        String key = occurrence.id() + "\n" + siteId;
        long ordinal = DOOR_ORDINALS.computeIfAbsent(key, ignored -> new AtomicLong())
                .incrementAndGet();
        FaultDoorHit hit = new FaultDoorHit(occurrence, siteId, ordinal);
        TraceRows.row("FAULT_DOOR", occurrence,
                TraceRows.fields("siteId", siteId, "doorOrdinal", ordinal));
        return hit;
    }

    public static void faultApplied(FaultDoorHit hit, String exceptionClass) {
        if (hit == null || empty(exceptionClass)) {
            gap("FAULT_APPLIED_UNATTRIBUTED", exceptionClass,
                    "no exact door hit or exception type");
            return;
        }
        TraceRows.row("FAULT_APPLIED", hit.occurrence,
                TraceRows.fields("siteId", hit.siteId,
                        "doorOrdinal", hit.ordinal,
                        "exceptionClass", exceptionClass));
    }

    public static Object captureScope() { return TraceRows.snapshot(); }

    public static long enterCarriedScope(Object scope, String role,
                                         String api) {
        if (!(scope instanceof TraceRows.Context)) {
            gap("MISSING_CARRIED_SCOPE", api, "task has no captured scope");
            return 0L;
        }
        TraceRows.Context previous = TraceRows.install((TraceRows.Context) scope);
        long token = EXCHANGES.incrementAndGet();
        CARRIED.put(token, previous);
        TraceRows.row("TASK_CLAIM", TraceRows.occurrence(null),
                TraceRows.fields("role", role, "api", api));
        return token;
    }

    private static final Map<Long, TraceRows.Context> CARRIED =
            new ConcurrentHashMap<>();

    public static void exitCarriedScope(long token) {
        if (token == 0L) return;
        TraceRows.Context prior = CARRIED.remove(token);
        if (prior == null) {
            gap("MISSING_CARRIED_SCOPE", String.valueOf(token),
                    "task scope exit");
            return;
        }
        TraceRows.restore(prior);
    }

    public static Outbound prepareOutbound(String transport,
                                           String correlationId,
                                           String attemptId, String half,
                                           Object localOwner, Object scope) {
        if (empty(transport) || empty(correlationId) || empty(attemptId)
                || empty(half)) {
            gap("WIRE_IDENTITY_MISSING", transport, "transport/correlation/attempt/half");
            return Outbound.EMPTY;
        }
        TraceRows.Context previous = null;
        if (scope instanceof TraceRows.Context) {
            previous = TraceRows.install((TraceRows.Context) scope);
        }
        Endpoint endpoint;
        try {
            endpoint = TraceRows.messageEndpoint(localOwner,
                    transport + "." + half, correlationId, attemptId);
        } finally {
            if (previous != null) TraceRows.restore(previous);
        }
        if (endpoint == null) return Outbound.EMPTY;
        JsonObject header = TraceRows.fields("schema", 1,
                "transport", transport, "correlationId", correlationId,
                "attemptId", attemptId, "half", half,
                // The trace already records the full address at the sender.
                // Put stable IDs on the wire: deep execution indices can
                // otherwise exceed an RPC header's bounded decode size.
                "producer", endpoint.id(),
                "producerEndpointId", endpoint.id(),
                "producerOccurrenceId", endpoint.occurrence().id());
        String trace = Base64.getUrlEncoder().withoutPadding().encodeToString(
                header.toString().getBytes(StandardCharsets.UTF_8));
        Outbound result = new Outbound(correlationId, attemptId, trace, "",
                transport, half, endpoint);
        PREPARED.put(trace, result);
        TraceRows.row("WIRE_PREPARED", endpoint.occurrence(),
                TraceRows.fields("producer", endpoint.id(),
                        "producerEndpointId", endpoint.id(),
                        "transport", transport, "correlationId", correlationId,
                        "attemptId", attemptId, "half", half));
        return result;
    }

    /** Compatibility name; still only prepares, so it cannot invent a SEND. */
    public static Outbound outbound(String transport, String correlationId,
                                    String attemptId, String half,
                                    Object localOwner, Object scope) {
        return prepareOutbound(transport, correlationId, attemptId, half,
                localOwner, scope);
    }

    public static Outbound outbound(String transport, String correlationId,
                                    String attemptId, String half,
                                    Object localOwner, Object scope,
                                    Object payload) {
        return prepareOutbound(transport, correlationId, attemptId, half,
                localOwner, scope);
    }

    /** Called at a successful write boundary; repeated confirmation is safe. */
    public static void sent(Outbound outbound) {
        if (outbound == null || !outbound.active()) return;
        synchronized (outbound) {
            if (outbound.sent) return;
            outbound.sent = true;
            Endpoint endpoint = outbound.endpoint;
            TraceRows.row("EXPORT", endpoint.occurrence(),
                    TraceRows.fields("producer", endpoint.id(),
                            "producerEndpointId", endpoint.id(),
                            "transport", outbound.transport,
                            "correlationId", outbound.correlationId,
                            "attemptId", outbound.attemptId,
                            "half", outbound.half));
        }
    }

    public static Inbound inbound(String trace, String symbolic,
                                  String transport, String correlationId,
                                  String attemptId, String half,
                                  Object localOwner, boolean keepSymbolic) {
        if (empty(trace)) {
            gap("WIRE_HEADER_MISSING", transport, "inbound has no trace header");
            return Inbound.EMPTY;
        }
        JsonObject header;
        try {
            byte[] raw = Base64.getUrlDecoder().decode(trace);
            if (raw.length > 16384) throw new IllegalArgumentException("large header");
            header = new JsonParser().parse(new String(raw,
                    StandardCharsets.UTF_8)).getAsJsonObject();
        } catch (RuntimeException invalid) {
            gap("WIRE_HEADER_INVALID", transport, invalid.toString());
            return Inbound.EMPTY;
        }
        if (!same(header, "transport", transport)
                || !same(header, "correlationId", correlationId)
                || !same(header, "attemptId", attemptId)
                || !same(header, "half", half)
                || empty(value(header, "producerEndpointId"))
                || empty(value(header, "producerOccurrenceId"))
                || empty(value(header, "producer"))) {
            gap("WIRE_HEADER_MISMATCH", transport, correlationId + "/" + attemptId);
            return Inbound.EMPTY;
        }
        Outbound prepared = PREPARED.get(trace);
        if (prepared != null) sent(prepared); // an actual receipt proves the send
        else gap("WIRE_PRODUCER_UNOBSERVED", transport,
                "producer not in this JVM trace");
        SourceRef owner = TraceRows.source(localOwner);
        if (owner == null) {
            gap("UNREGISTERED_SOURCE", transport, "inbound owner not registered");
            return Inbound.EMPTY;
        }
        endInbound();
        // An inbound may be decoded inside an already active, woven region.
        // Attach the message to that exact occurrence. Replacing its context
        // here would discard its stack and misattribute later target checks.
        // The WIRE edge records the newly received influence on the region.
        boolean activeRegion = TraceRows.hasActiveRegion(localOwner);
        if (!activeRegion && TraceRows.hasAnyActiveRegion()) {
            gap("INBOUND_ACTIVE_REGION_SOURCE_MISMATCH", transport,
                    "message owner differs from the active woven region");
        }
        TraceRows.Context prior = null;
        if (!activeRegion) {
            prior = TraceRows.snapshot();
            TraceRows.Context received = new TraceRows.Context();
            received.source = owner;
            received.cause = CausalContext.of(
                    header.get("producerEndpointId").getAsString(),
                    transport + "." + half);
            TraceRows.install(received);
        }
        Endpoint consumer = TraceRows.endpoint(localOwner,
                transport + "." + half, 0);
        TraceRows.row("ATTACH", consumer == null ? null : consumer.occurrence(),
                TraceRows.fields("producer", header.get("producer").getAsString(),
                        "producerEndpointId", header.get("producerEndpointId").getAsString(),
                        "producerOccurrenceId", header.get("producerOccurrenceId").getAsString(),
                        "consumer", consumer == null ? "" : consumer.render(),
                        "consumerEndpointId", consumer == null ? "" : consumer.id(),
                        "transport", transport, "correlationId", correlationId,
                        "attemptId", attemptId, "half", half,
                        "pairedBy", prepared == null ? "EXTERNAL_ENVELOPE" : "ENVELOPE"));
        Inbound result = new Inbound(prior, correlationId, attemptId, half);
        CURRENT.set(result);
        return result;
    }

    public static void endInbound(Inbound scope) {
        if (scope != null && scope != Inbound.EMPTY && CURRENT.get() == scope) {
            CURRENT.remove();
            if (scope.prior != null) TraceRows.restore(scope.prior);
        }
    }

    public static void endInbound() { endInbound(CURRENT.get()); }

    public static Inbound current() { return CURRENT.get(); }

    public static void stored(String transport, String key, Object owner) {
        stored(transport, key, owner, null);
    }

    /** Key must include the store's actual version, observed after success. */
    public static void stored(String transport, String key, Object owner,
                              byte[] data) {
        Endpoint writer = TraceRows.endpoint(owner, transport + ".WRITE", 0);
        if (writer == null || empty(key)) {
            gap("STATE_WRITE_UNNAMED", transport, key);
            return;
        }
        String location = transport + "\n" + key;
        STORED.computeIfAbsent(location, ignored ->
                java.util.Collections.synchronizedList(new ArrayList<>())).add(writer);
        TraceRows.row("WRITE", writer.occurrence(), TraceRows.fields(
                "locationVersion", location, "writer", writer.render(),
                "writerEndpointId", writer.id()));
    }

    public static void fetched(String transport, String key, Object owner) {
        fetched(transport, key, owner, null);
    }

    public static void fetched(String transport, String key, Object owner,
                               byte[] data) {
        int attempt = NOTIFIED.get() == null ? 0 :
                (int) EXCHANGES.incrementAndGet();
        Endpoint reader = TraceRows.endpoint(owner, transport + ".READ", attempt);
        if (reader == null || empty(key)) {
            gap("STATE_READ_UNNAMED", transport, key);
            return;
        }
        String location = transport + "\n" + key;
        List<Endpoint> writers = STORED.get(location);
        Endpoint exact = null;
        if (writers != null) synchronized (writers) {
            if (writers.size() == 1) exact = writers.get(0);
        }
        if (exact == null) gap("STATE_WRITER_UNRESOLVED", transport, key);
        TraceRows.row("READ", reader.occurrence(), TraceRows.fields(
                "locationVersion", location, "reader", reader.render(),
                "readerEndpointId", reader.id(), "writer", exact == null ? "" : exact.render(),
                "writerEndpointId", exact == null ? "" : exact.id(),
                "writerOccurrenceId", exact == null ? "" : exact.occurrence().id()));
        if (exact != null && NOTIFIED.get() != null) {
            LAST_NOTIFIED_READ.set(new ReadHandoff(transport, key, location,
                    reader, exact));
            TraceRows.Context current = TraceRows.snapshot();
            current.cause = CausalContext.of(exact.id(), transport + ".WATCH");
            TraceRows.install(current);
            NOTIFIED.remove();
        }
    }

    public static void notified(String kind, Runnable callback) {
        if (callback == null) return;
        LAST_NOTIFIED_READ.remove();
        NOTIFIED.set(kind);
        try { callback.run(); }
        finally { NOTIFIED.remove(); endInbound(); }
    }

    public static void consumed(String transport, String key) {
        ReadHandoff read = LAST_NOTIFIED_READ.get();
        LAST_NOTIFIED_READ.remove();
        CausalContext cause = TraceRows.snapshot().cause;
        boolean anchored = cause instanceof CausalContext.Anchor
                && ((CausalContext.Anchor) cause).producerEndpointId()
                        .equals(read == null ? "" : read.writer.id())
                && ((CausalContext.Anchor) cause).rpcSite()
                        .equals(transport + ".WATCH");
        if (read == null || !read.transport.equals(transport)
                || !read.key.equals(key) || !anchored) {
            gap("QUEUE_READ_UNPROVEN", transport, key);
            TraceRows.row("QUEUE_CONSUMED", TraceRows.occurrence(null),
                    TraceRows.fields("transport", transport, "key", key));
            return;
        }
        Endpoint consumer = TraceRows.endpoint(null, transport + ".QUEUE", 0);
        TraceRows.row("QUEUE_CONSUMED", consumer == null ? null : consumer.occurrence(),
                TraceRows.fields("transport", transport, "key", key,
                        "locationVersion", read.locationVersion,
                        "readEndpointId", read.reader.id(),
                        "readOccurrenceId", read.reader.occurrence().id(),
                        "writerEndpointId", read.writer.id(),
                        "writerOccurrenceId", read.writer.occurrence().id(),
                        "consumerEndpointId", consumer == null ? "" : consumer.id()));
    }

    private static final class ReadHandoff {
        final String transport;
        final String key;
        final String locationVersion;
        final Endpoint reader;
        final Endpoint writer;

        ReadHandoff(String transport, String key, String locationVersion,
                    Endpoint reader, Endpoint writer) {
            this.transport = transport;
            this.key = key;
            this.locationVersion = locationVersion;
            this.reader = reader;
            this.writer = writer;
        }
    }

    public static long beginExchange(String transport) {
        return EXCHANGES.incrementAndGet();
    }

    public static void endExchange(long token) { }

    public static void payloadUnread(String transport, String detail) {
        gap("PAYLOAD_UNREAD", transport, detail);
    }

    public static void gap(String kind, String subject, String detail) {
        TraceRows.gap(kind, subject, detail);
    }

    public static Outbound outboundNone() { return Outbound.EMPTY; }

    private static boolean empty(String value) {
        return value == null || value.isEmpty();
    }

    private static boolean same(JsonObject row, String key, String expected) {
        return row.has(key) && expected != null
                && expected.equals(row.get(key).getAsString());
    }

    private static String value(JsonObject row, String key) {
        try { return row.get(key).getAsString(); }
        catch (RuntimeException missing) { return ""; }
    }

    public static final class Outbound {
        static final Outbound EMPTY = new Outbound("", "", "", "", "", "", null);
        public final String correlationId;
        public final String attemptId;
        public final String trace;
        public final String symbolic;
        private final String transport;
        private final String half;
        private final Endpoint endpoint;
        private boolean sent;

        private Outbound(String correlationId, String attemptId, String trace,
                         String symbolic, String transport, String half,
                         Endpoint endpoint) {
            this.correlationId = correlationId;
            this.attemptId = attemptId;
            this.trace = trace;
            this.symbolic = symbolic;
            this.transport = transport;
            this.half = half;
            this.endpoint = endpoint;
        }

        public boolean active() { return endpoint != null; }
    }

    public static final class Inbound {
        static final Inbound EMPTY = new Inbound(null, "", "", "");
        private final TraceRows.Context prior;
        public final String correlationId;
        public final String attemptId;
        public final String half;

        private Inbound(TraceRows.Context prior, String correlationId,
                        String attemptId, String half) {
            this.prior = prior;
            this.correlationId = correlationId;
            this.attemptId = attemptId;
            this.half = half;
        }
    }
}
