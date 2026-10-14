package edu.uva.liftlab.mallory.graphchecker.runtime;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import edu.uva.liftlab.mallory.graphchecker.contract.CausalContext;
import edu.uva.liftlab.mallory.graphchecker.contract.Digest;
import edu.uva.liftlab.mallory.graphchecker.contract.Endpoint;
import edu.uva.liftlab.mallory.graphchecker.contract.OccurrenceAddress;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicBoolean;

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
    private static final Map<String, List<StoredWrite>> STORED = new ConcurrentHashMap<>();
    private static final ThreadLocal<Inbound> CURRENT = new ThreadLocal<>();
    private static final ThreadLocal<String> NOTIFIED = new ThreadLocal<>();
    private static final ThreadLocal<ReadHandoff> LAST_NOTIFIED_READ = new ThreadLocal<>();
    private static final ThreadLocal<OperationHint> CURRENT_OPERATION = new ThreadLocal<>();
    private static final ThreadLocal<MessagePayloadScope> MESSAGE_PAYLOAD = new ThreadLocal<>();
    private static final AtomicLong EXCHANGES = new AtomicLong();
    private static final Map<String, AtomicLong> DOOR_ORDINALS = new ConcurrentHashMap<>();
    private static final Map<String, AtomicLong> REPLAY_SEND_ORDINALS =
            new ConcurrentHashMap<>();
    private static final Map<String, AtomicLong> TASK_ORDINALS =
            new ConcurrentHashMap<>();
    private static final Map<Long, TaskRestore> TASK_CLAIMS =
            new ConcurrentHashMap<>();
    // Coverage feedback is a set of sites per causal occurrence. Repeated
    // execution of one block in a polling loop adds no coverage information.
    private static final Map<String, Boolean> COVERAGE_SEEN = new ConcurrentHashMap<>();

    private MessageDoors() { }

    /** Optional, bounded request metadata for trace review; never part of replay identity. */
    public static OperationScope operationScope(String method, String path, String action) {
        OperationHint prior = CURRENT_OPERATION.get();
        CURRENT_OPERATION.set(new OperationHint(method, path, action));
        return new OperationScope(prior);
    }

    public static final class OperationScope implements AutoCloseable {
        private final OperationHint prior;
        private boolean closed;

        private OperationScope(OperationHint prior) { this.prior = prior; }

        @Override public void close() {
            if (closed) return;
            closed = true;
            if (prior == null) CURRENT_OPERATION.remove();
            else CURRENT_OPERATION.set(prior);
        }
    }

    private static final class OperationHint {
        final String method;
        final String path;
        final String action;

        OperationHint(String method, String path, String action) {
            this.method = boundedToken(method, 16);
            this.path = boundedPath(path);
            this.action = boundedToken(action, 32);
        }

        JsonObject addTo(JsonObject fields) {
            if (!method.isEmpty()) fields.addProperty("operationMethod", method);
            if (!path.isEmpty()) fields.addProperty("operationPath", path);
            if (!action.isEmpty()) fields.addProperty("operationAction", action);
            return fields;
        }
    }

    private static String boundedToken(String value, int max) {
        if (value == null || value.isEmpty() || value.length() > max) return "";
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z')
                    || (c >= '0' && c <= '9') || c == '_' || c == '-')) return "";
        }
        return value;
    }

    private static String boundedPath(String value) {
        if (value == null || !value.startsWith("/") || value.startsWith("//")) return "";
        int end = value.length();
        int query = value.indexOf('?');
        int fragment = value.indexOf('#');
        if (query >= 0) end = Math.min(end, query);
        if (fragment >= 0) end = Math.min(end, fragment);
        if (end > 128) return "";
        for (int i = 0; i < end; i++) {
            char c = value.charAt(i);
            if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z')
                    || (c >= '0' && c <= '9') || c == '/' || c == '_'
                    || c == '-' || c == '.' || c == '~' || c == '%')) return "";
        }
        return value.substring(0, end);
    }

    private static JsonObject withOperation(JsonObject fields, OperationHint hint) {
        return hint == null ? fields : hint.addTo(fields);
    }

    public static void startRecording() {
        TraceRows.beginGapWindow();
        TraceRows.row("WINDOW_OPEN", null, null);
    }

    public static void stopRecording() {
        TraceRows.flushSuppressedRegionGaps();
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

    /** Keep an observed same-owner inbound/request cause for a nested turn. */
    public static long beginContinuation(Object owner, String role) {
        boolean sameOwner = TraceRows.hasSameOwnerCause(owner);
        if (!sameOwner && TraceRows.hasActiveCause()) {
            gap("CONTINUATION_SOURCE_MISMATCH", role,
                    "active cause belongs to another source; start a separate root");
        }
        return TraceRows.begin(owner, role, !sameOwner);
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
        JsonObject values = TraceRows.fields("siteId", siteId, "exceptionClass",
                thrown == null ? "" : thrown.getClass().getName());
        JsonObject fingerprint = TargetThrowFingerprint.fields(
                siteId, occurrence, owner, thrown);
        for (Map.Entry<String, com.google.gson.JsonElement> entry :
                fingerprint.entrySet()) values.add(entry.getKey(), entry.getValue());
        TraceRows.row("TARGET_THROW", occurrence, values);
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
        OccurrenceAddress occurrence = TraceRows.occurrence(owner);
        String replayOccurrenceId = TraceRows.replayOccurrenceId(occurrence);
        MessagePayloadScope payload = MESSAGE_PAYLOAD.get();
        JsonObject values = TraceRows.fields("siteId", siteId, "doorOrdinal", ordinal,
                "replayOccurrenceId", replayOccurrenceId);
        if (payload != null && occurrence != null) {
            values.addProperty("messageReplayKey", payload.key);
            values.addProperty("messageParentId", messageParent(occurrence));
        }
        TraceRows.row("FAULT_DOOR", occurrence,
                withOperation(values, CURRENT_OPERATION.get()));
    }

    public static void faultDoor(String siteId, Object owner) {
        faultDoorHit(siteId, owner);
    }

    /** An exact observed door instance for matching one ordered fault plan. */
    public static final class FaultDoorHit {
        public final String occurrenceId;
        public final String replayOccurrenceId;
        public final String node;
        public final String siteId;
        public final long ordinal;
        public final String messageReplayKey;
        public final String messageParentId;
        private final OccurrenceAddress occurrence;
        private final OperationHint operation;

        private FaultDoorHit(OccurrenceAddress occurrence, String replayOccurrenceId,
                             String siteId, long ordinal, String messageReplayKey,
                             String messageParentId, OperationHint operation) {
            this.occurrence = occurrence;
            this.occurrenceId = occurrence.id();
            this.replayOccurrenceId = replayOccurrenceId;
            this.node = occurrence.node().render();
            this.siteId = siteId;
            this.ordinal = ordinal;
            this.messageReplayKey = messageReplayKey;
            this.messageParentId = messageParentId;
            this.operation = operation;
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
        String replayOccurrenceId = TraceRows.replayOccurrenceId(occurrence);
        MessagePayloadScope payload = MESSAGE_PAYLOAD.get();
        String messageReplayKey = payload == null ? "" : payload.key;
        String messageParentId = payload == null ? "" : messageParent(occurrence);
        if (empty(replayOccurrenceId)) {
            gap("REPLAY_LINEAGE_MISSING", siteId,
                    "fault door has no stable replay cause");
        }
        OperationHint operation = CURRENT_OPERATION.get();
        FaultDoorHit hit = new FaultDoorHit(occurrence, replayOccurrenceId,
                siteId, ordinal, messageReplayKey, messageParentId, operation);
        JsonObject values = TraceRows.fields("siteId", siteId, "doorOrdinal", ordinal,
                "replayOccurrenceId", replayOccurrenceId);
        if (!empty(messageReplayKey)) {
            values.addProperty("messageReplayKey", messageReplayKey);
            values.addProperty("messageParentId", messageParentId);
        }
        TraceRows.row("FAULT_DOOR", occurrence, withOperation(values, operation));
        return hit;
    }

    public static void faultApplied(FaultDoorHit hit, String exceptionClass) {
        if (hit == null || empty(exceptionClass)) {
            gap("FAULT_APPLIED_UNATTRIBUTED", exceptionClass,
                    "no exact door hit or exception type");
            return;
        }
        JsonObject values = TraceRows.fields("siteId", hit.siteId,
                "doorOrdinal", hit.ordinal,
                "replayOccurrenceId", hit.replayOccurrenceId,
                "exceptionClass", exceptionClass);
        if (!empty(hit.messageReplayKey)) {
            values.addProperty("messageReplayKey", hit.messageReplayKey);
            values.addProperty("messageParentId", hit.messageParentId);
        }
        TraceRows.row("FAULT_APPLIED", hit.occurrence,
                withOperation(values, hit.operation));
    }

    private static String messageParent(OccurrenceAddress occurrence) {
        return Digest.digest("message-parent-v1\n" + occurrence.context().render()
                + "\n" + occurrence.regionId() + "\n" + occurrence.index().render(), 0);
    }

    /** Scope a real serialized message to the calls it directly causes. */
    public static MessagePayloadScope beginMessagePayload(String transport,
                                                            String route, byte[] data) {
        if (empty(transport) || empty(route) || data == null) {
            gap("MESSAGE_PAYLOAD_UNAVAILABLE", transport, route);
            return MessagePayloadScope.EMPTY;
        }
        String key = Digest.digest("message-payload-v1\n" + transport + "\n"
                + route + "\n" + Digest.payload(data), 0);
        MessagePayloadScope scope = new MessagePayloadScope(key, MESSAGE_PAYLOAD.get());
        MESSAGE_PAYLOAD.set(scope);
        return scope;
    }

    public static final class MessagePayloadScope implements AutoCloseable {
        private static final MessagePayloadScope EMPTY = new MessagePayloadScope("", null);
        private final String key;
        private final MessagePayloadScope prior;
        private boolean closed;

        private MessagePayloadScope(String key, MessagePayloadScope prior) {
            this.key = key;
            this.prior = prior;
        }

        @Override public void close() {
            if (this == EMPTY) return;
            if (closed || MESSAGE_PAYLOAD.get() != this) {
                throw new IllegalStateException("message payload scopes must close once in order");
            }
            closed = true;
            if (prior == null) MESSAGE_PAYLOAD.remove();
            else MESSAGE_PAYLOAD.set(prior);
        }
    }

    public static Object captureScope() { return TraceRows.snapshot(); }

    /**
     * Capture one executor submission without copying its caller's regions,
     * frames, or saved request stack. An unrooted task has no causal ticket.
     * A rejected task leaves an unclaimed submission and therefore no edge.
     */
    public static Object prepareTask(String siteId, Object carrier) {
        if (empty(siteId) || carrier == null) {
            gap("TASK_IDENTITY_MISSING", siteId, "site or carrier missing");
            return null;
        }
        if (!TraceRows.hasAttributedScope(null)) return null;
        OccurrenceAddress parent = TraceRows.occurrence(null);
        if (parent == null) return null;
        TraceRows.Context live = TraceRows.currentContext();
        String key = parent.id() + "\n" + siteId;
        long ordinal = TASK_ORDINALS.computeIfAbsent(key,
                ignored -> new AtomicLong()).incrementAndGet();
        String endpoint = Digest.digest("task-submit-v1\n" + key + "\n" + ordinal, 32);
        String replayParent = TraceRows.replayOccurrenceId(parent);
        String replay = empty(replayParent) ? "" : Digest.digest(
                "task-replay-v1\n" + replayParent + "\n" + siteId
                        + "\n" + ordinal, 32);
        TaskTicket ticket = new TaskTicket(siteId, ordinal, endpoint,
                parent.id(), live.source, replay);
        TraceRows.row("TASK_SUBMIT", parent,
                TraceRows.fields("siteId", siteId, "taskOrdinal", ordinal,
                        "producerEndpointId", endpoint,
                        "sourceKey", live.source.key()));
        return ticket;
    }

    /** One exact task may be claimed once; the worker starts with a fresh path. */
    public static long claimTask(Object prepared, String role, String api) {
        if (prepared == null) return 0L;
        if (!(prepared instanceof TaskTicket)) {
            gap("TASK_TICKET_INVALID", api, "unrecognized task ticket");
            return 0L;
        }
        TaskTicket ticket = (TaskTicket) prepared;
        if (!ticket.claimed.compareAndSet(false, true)) {
            gap("TASK_TICKET_REUSED", ticket.siteId, "task claimed more than once");
            return 0L;
        }
        TraceRows.Context fresh = new TraceRows.Context();
        fresh.source = ticket.source;
        fresh.cause = CausalContext.of(ticket.endpoint, ticket.siteId);
        fresh.replayCause = ticket.replay;
        TraceRows.Context prior = TraceRows.install(fresh);
        long token = EXCHANGES.incrementAndGet();
        TASK_CLAIMS.put(token, new TaskRestore(prior, Thread.currentThread()));
        OccurrenceAddress child = TraceRows.occurrence(null);
        String claimEndpoint = Digest.digest("task-claim-v1\n"
                + ticket.endpoint + "\n" + child.id(), 32);
        TraceRows.row("TASK_CLAIM", child,
                TraceRows.fields("role", role, "api", api,
                        "siteId", ticket.siteId,
                        "taskOrdinal", ticket.ordinal,
                        "producerEndpointId", ticket.endpoint,
                        "producerOccurrenceId", ticket.parentOccurrence,
                        "consumerEndpointId", claimEndpoint,
                        "sourceKey", ticket.source.key()));
        return token;
    }

    public static void endTask(long token) {
        if (token == 0L) return;
        TaskRestore restore = TASK_CLAIMS.get(token);
        if (restore == null || restore.thread != Thread.currentThread()) {
            gap("TASK_CLAIM_UNBALANCED", String.valueOf(token),
                    "missing claim or different worker thread");
            return;
        }
        TASK_CLAIMS.remove(token);
        TraceRows.restore(restore.prior);
    }

    private static final class TaskTicket {
        final String siteId;
        final long ordinal;
        final String endpoint;
        final String parentOccurrence;
        final SourceRef source;
        final String replay;
        final AtomicBoolean claimed = new AtomicBoolean();

        TaskTicket(String siteId, long ordinal, String endpoint,
                   String parentOccurrence, SourceRef source, String replay) {
            this.siteId = siteId;
            this.ordinal = ordinal;
            this.endpoint = endpoint;
            this.parentOccurrence = parentOccurrence;
            this.source = source;
            this.replay = replay;
        }
    }

    private static final class TaskRestore {
        final TraceRows.Context prior;
        final Thread thread;

        TaskRestore(TraceRows.Context prior, Thread thread) {
            this.prior = prior;
            this.thread = thread;
        }
    }

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
        String replayEndpointId;
        try {
            endpoint = TraceRows.messageEndpoint(localOwner,
                    transport + "." + half, correlationId, attemptId);
            String replayOccurrenceId = endpoint == null ? ""
                    : TraceRows.replayOccurrenceId(endpoint.occurrence());
            if (empty(replayOccurrenceId)) {
                replayEndpointId = "";
                gap("REPLAY_LINEAGE_MISSING", transport,
                        "outbound has no stable replay cause");
            } else {
                String key = replayOccurrenceId + "\n" + transport + "\n" + half;
                long ordinal = REPLAY_SEND_ORDINALS.computeIfAbsent(key,
                        ignored -> new AtomicLong()).incrementAndGet();
                replayEndpointId = Digest.digest("replay-endpoint-v1\n" + key
                        + "\n" + ordinal, 32);
            }
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
        if (!empty(replayEndpointId)) {
            header.addProperty("producerReplayEndpointId", replayEndpointId);
        }
        String trace = Base64.getUrlEncoder().withoutPadding().encodeToString(
                header.toString().getBytes(StandardCharsets.UTF_8));
        OperationHint operation = CURRENT_OPERATION.get();
        Outbound result = new Outbound(correlationId, attemptId, trace, "",
                transport, half, endpoint, operation);
        PREPARED.put(trace, result);
        TraceRows.row("WIRE_PREPARED", endpoint.occurrence(),
                withOperation(TraceRows.fields("producer", endpoint.id(),
                        "producerEndpointId", endpoint.id(),
                        "transport", transport, "correlationId", correlationId,
                        "attemptId", attemptId, "half", half), operation));
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
                    withOperation(TraceRows.fields("producer", endpoint.id(),
                            "producerEndpointId", endpoint.id(),
                            "transport", outbound.transport,
                            "correlationId", outbound.correlationId,
                            "attemptId", outbound.attemptId,
                            "half", outbound.half), outbound.operation));
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
        String replayEndpointId = value(header, "producerReplayEndpointId");
        if (!replayEndpointId.matches("[0-9a-f]{32}")) {
            gap("REPLAY_HEADER_MISSING", transport,
                    "inbound exact wire is valid but replay lineage is unavailable");
            replayEndpointId = "";
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
            if (!empty(replayEndpointId)) {
                received.replayCause = "AnchorReplay:" + replayEndpointId
                        + "@" + transport + "." + half;
            }
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

    /** File a successful write under the exact version returned by its API. */
    public static void storedVersionedValue(String transport, String key,
                                            Object owner) {
        stored(transport, key, owner);
    }

    /** Key must include the store's actual version, observed after success. */
    public static void stored(String transport, String key, Object owner,
                              byte[] data) {
        if (empty(key)) {
            gap("STATE_WRITE_UNNAMED", transport, key);
            return;
        }
        String location = transport + "\n" + key;
        Endpoint writer = TraceRows.stateEndpoint(owner, transport + ".WRITE",
                location, 0);
        if (writer == null) {
            gap("STATE_WRITE_UNNAMED", transport, key);
            return;
        }
        String payloadSha256 = data == null ? "" : Digest.payload(data);
        STORED.computeIfAbsent(location, ignored ->
                java.util.Collections.synchronizedList(new ArrayList<>()))
                .add(new StoredWrite(writer, payloadSha256));
        TraceRows.row("WRITE", writer.occurrence(), TraceRows.fields(
                "locationVersion", location, "writer", writer.render(),
                "writerEndpointId", writer.id(),
                "payloadSha256", payloadSha256));
    }

    public static void fetched(String transport, String key, Object owner) {
        fetched(transport, key, owner, null);
    }

    public static void fetched(String transport, String key, Object owner,
                               byte[] data) {
        if (empty(key)) {
            gap("STATE_READ_UNNAMED", transport, key);
            return;
        }
        int attempt = NOTIFIED.get() == null ? 0 :
                (int) EXCHANGES.incrementAndGet();
        String location = transport + "\n" + key;
        Endpoint reader = TraceRows.stateEndpoint(owner, transport + ".READ",
                location, attempt);
        if (reader == null) {
            gap("STATE_READ_UNNAMED", transport, key);
            return;
        }
        String payloadSha256 = data == null ? "" : Digest.payload(data);
        List<StoredWrite> writers = STORED.get(location);
        StoredWrite stored = null;
        if (writers != null) synchronized (writers) {
            if (writers.size() == 1) stored = writers.get(0);
        }
        if (stored != null && !payloadSha256.isEmpty()
                && !stored.payloadSha256.isEmpty()
                && !payloadSha256.equals(stored.payloadSha256)) {
            gap("STATE_PAYLOAD_MISMATCH", transport, key);
            stored = null;
        }
        Endpoint exact = stored == null ? null : stored.endpoint;
        if (exact == null) gap("STATE_WRITER_UNRESOLVED", transport, key);
        TraceRows.row("READ", reader.occurrence(), TraceRows.fields(
                "locationVersion", location, "reader", reader.render(),
                "readerEndpointId", reader.id(), "writer", exact == null ? "" : exact.render(),
                "writerEndpointId", exact == null ? "" : exact.id(),
                "writerOccurrenceId", exact == null ? "" : exact.occurrence().id(),
                "payloadSha256", payloadSha256));
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

    private static final class StoredWrite {
        final Endpoint endpoint;
        final String payloadSha256;

        StoredWrite(Endpoint endpoint, String payloadSha256) {
            this.endpoint = endpoint;
            this.payloadSha256 = payloadSha256;
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
        static final Outbound EMPTY = new Outbound("", "", "", "", "", "", null, null);
        public final String correlationId;
        public final String attemptId;
        public final String trace;
        public final String symbolic;
        private final String transport;
        private final String half;
        private final Endpoint endpoint;
        private final OperationHint operation;
        private boolean sent;

        private Outbound(String correlationId, String attemptId, String trace,
                         String symbolic, String transport, String half,
                         Endpoint endpoint, OperationHint operation) {
            this.correlationId = correlationId;
            this.attemptId = attemptId;
            this.trace = trace;
            this.symbolic = symbolic;
            this.transport = transport;
            this.half = half;
            this.endpoint = endpoint;
            this.operation = operation;
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
