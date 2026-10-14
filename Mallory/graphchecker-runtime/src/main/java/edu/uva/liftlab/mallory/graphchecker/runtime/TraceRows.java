package edu.uva.liftlab.mallory.graphchecker.runtime;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import edu.uva.liftlab.mallory.graphchecker.contract.CausalContext;
import edu.uva.liftlab.mallory.graphchecker.contract.Digest;
import edu.uva.liftlab.mallory.graphchecker.contract.ExecutionIndex;
import edu.uva.liftlab.mallory.graphchecker.contract.Frame;
import edu.uva.liftlab.mallory.graphchecker.contract.NodeId;
import edu.uva.liftlab.mallory.graphchecker.contract.OccurrenceAddress;
import edu.uva.liftlab.mallory.graphchecker.contract.Role;
import edu.uva.liftlab.mallory.graphchecker.contract.Endpoint;

import java.io.BufferedWriter;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.HashSet;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/**
 * GraphChecker identity and row publication adapted for one original JUnit
 * cluster JVM. Source aliases are identity based; an unregistered owner is a
 * gap, never a guessed node. Pool work must install a carried scope explicitly.
 */
final class TraceRows {
    private static final Object LOCK = new Object();
    private static final Map<Object, SourceRef> SOURCES = new IdentityHashMap<>();
    private static final Map<String, AtomicInteger> ROOT_COUNTS =
            new ConcurrentHashMap<>();
    private static final Set<String> EMITTED_ACTIVATIONS = new HashSet<>();
    /** A failed region entry creates no occurrence or graph edge. Keep one diagnostic per thread/site. */
    private static final Map<String, AtomicLong> UNATTRIBUTED_REGION_COUNTS =
            new ConcurrentHashMap<>();
    private static final ThreadLocal<Context> CURRENT =
            ThreadLocal.withInitial(Context::new);
    private static final Gson GSON = new Gson();
    private static final boolean COMPACT_TRACE = Boolean.getBoolean(
            "mallory.graphchecker.trace.compact");
    private static BufferedWriter writer;
    private static long sequence;
    private static boolean closed;
    private static boolean writerFailed;

    private TraceRows() { }

    static void register(Object anchor, SourceRef source) {
        if (anchor == null || source == null) throw new IllegalArgumentException("source");
        synchronized (SOURCES) {
            SourceRef old = SOURCES.get(anchor);
            if (old != null && !old.equals(source)) {
                throw new IllegalStateException("source alias changed without restart");
            }
            SOURCES.put(anchor, source);
        }
    }

    static void alias(Object alias, Object anchor) {
        SourceRef source = source(anchor);
        if (alias == null || source == null) {
            gap("UNREGISTERED_SOURCE", "source alias", "anchor not registered");
            return;
        }
        register(alias, source);
    }

    static void currentAlias(Object alias) {
        SourceRef source = CURRENT.get().source;
        if (alias == null || source == null) {
            gap("UNREGISTERED_SOURCE", "current alias", "no current source");
            return;
        }
        register(alias, source);
    }

    static void restart(Object anchor, SourceRef next) {
        if (anchor == null || next == null) throw new IllegalArgumentException("restart");
        synchronized (SOURCES) {
            SourceRef previous = SOURCES.get(anchor);
            if (previous == null || !previous.kind().equals(next.kind())
                    || !previous.role().equals(next.role())
                    || !previous.id().equals(next.id())
                    || next.epoch() <= previous.epoch()) {
                throw new IllegalArgumentException("restart must advance one source");
            }
            for (Map.Entry<Object, SourceRef> alias : SOURCES.entrySet()) {
                if (alias.getValue() == previous) alias.setValue(next);
            }
        }
    }

    static SourceRef source(Object owner) {
        synchronized (SOURCES) { return SOURCES.get(owner); }
    }

    static String currentSourceKey() {
        SourceRef source = CURRENT.get().source;
        if (source == null) {
            gap("UNREGISTERED_SOURCE", "current source key", "no active source");
            return "";
        }
        return source.key();
    }

    static Context snapshot() { return CURRENT.get().copy(); }

    /** Read only the live source and cause for a compact task ticket. */
    static Context currentContext() { return CURRENT.get(); }

    static Context install(Context scope) {
        Context prior = CURRENT.get();
        CURRENT.set(scope.copy());
        return prior;
    }

    static void restore(Context prior) { CURRENT.set(prior); }

    static long begin(Object owner, String api, boolean ownRoot) {
        SourceRef source = source(owner);
        if (source == null) {
            gap("UNREGISTERED_SOURCE", api, "request owner not registered");
            return 0L;
        }
        Context context = CURRENT.get();
        long token = ++context.nextToken;
        Saved saved = new Saved(token, context.source, context.cause,
                context.replayCause,
                new ArrayList<>(context.frames), new ArrayDeque<>(context.regions),
                new ArrayDeque<>(context.calls), copyFrameCounts(context.frameCounts),
                new ArrayDeque<>(context.regionSources),
                new ArrayDeque<>(context.activations));
        context.saved.push(saved);
        context.source = source;
        boolean newRoot = ownRoot || context.cause == null;
        saved.enteredRoot = newRoot;
        if (newRoot) {
            Role role = Role.of(source.role());
            String family = api == null || api.isEmpty() ? "request" : api;
            String key = source.key() + "\n" + role.name() + "\n" + family;
            int ordinal = ROOT_COUNTS.computeIfAbsent(key,
                    ignored -> new AtomicInteger()).incrementAndGet();
            context.cause = CausalContext.of(role, family, ordinal);
            context.replayCause = context.cause.render();
            context.resetFrames();
            context.regions.clear();
            context.regionSources.clear();
            context.activations.clear();
            context.calls.clear();
        }
        saved.enteredOccurrence = roleOccurrence(context);
        row("SCOPE_ENTER", saved.enteredOccurrence,
                fields("api", api, "sourceKey", source.key(),
                        "token", token, "newRoot", newRoot));
        return token;
    }

    static void end(long token) {
        if (token == 0L) return;
        Context context = CURRENT.get();
        if (context.saved.isEmpty() || context.saved.peek().token != token) {
            gap("SCOPE_UNBALANCED", String.valueOf(token), "request scope exit");
            return;
        }
        Saved saved = context.saved.pop();
        row("SCOPE_EXIT", saved.enteredOccurrence,
                fields("token", token, "newRoot", saved.enteredRoot));
        context.source = saved.source;
        context.cause = saved.cause;
        context.replayCause = saved.replayCause;
        context.restoreFrames(saved.frames, saved.frameCounts);
        context.regions.clear();
        context.regions.addAll(saved.regions);
        context.regionSources.clear();
        context.regionSources.addAll(saved.regionSources);
        context.activations.clear();
        context.activations.addAll(saved.activations);
        context.calls.clear();
        context.calls.addAll(saved.calls);
    }

    static void enterCall(String callSite, int iteration) {
        openCall(callSite, iteration);
    }

    static Object openCall(String callSite, int iteration) {
        Context context = CURRENT.get();
        if (context.source == null || context.cause == null) return null;
        if (callSite == null || callSite.isEmpty()) {
            gap("CALL_SITE_MISSING", "call", "enter");
            return null;
        }
        Object receipt = new Object();
        Frame frame = Frame.of(callSite, nextFrame(context, "CALL", callSite));
        context.pushFrame(frame);
        context.calls.push(new CallEntry(callSite, receipt, frame));
        return receipt;
    }

    static void exitCall(String callSite) {
        Context context = CURRENT.get();
        if (context.calls.isEmpty()) return;
        closeCall(context.calls.peek().receipt, callSite);
    }

    static void closeCall(Object receipt, String callSite) {
        if (receipt == null) return;
        Context context = CURRENT.get();
        CallEntry top = context.calls.peek();
        if (top == null || top.receipt != receipt) {
            // A bridge may end a request inside this instrumented call. The
            // scope restore may move its call frame into a Saved snapshot
            // before the Java call returns. Retire it in every snapshot so
            // later endRequest cannot restore a stale frame.
            for (CallEntry entry : context.calls) {
                if (entry.receipt == receipt) {
                    gap("CALL_UNBALANCED", callSite,
                            "exit; receipt is below active call; topCall="
                                    + (top == null ? "<none>" : top.site));
                    return;
                }
            }
            retireSavedCalls(context, receipt);
            return;
        }
        if (!top.site.equals(callSite)
                || context.frames.isEmpty()
                || context.frames.get(context.frames.size() - 1) != top.frame) {
            gap("CALL_UNBALANCED", callSite,
                    "exit; topCall=" + top.site
                            + "; topFrame=" + (context.frames.isEmpty() ? "<none>"
                            : context.frames.get(context.frames.size() - 1).callSite())
                            + "; topRegion=" + (context.regions.isEmpty() ? "<none>"
                            : context.regions.peek().regionId()));
            return;
        }
        context.calls.pop();
        context.popFrame();
        retireSavedCalls(context, receipt);
    }

    private static void retireSavedCalls(Context context, Object receipt) {
        for (Saved saved : context.saved) {
            for (java.util.Iterator<CallEntry> it = saved.calls.iterator();
                    it.hasNext();) {
                CallEntry entry = it.next();
                if (entry.receipt != receipt) continue;
                it.remove();
                for (int index = saved.frames.size() - 1; index >= 0; index--) {
                    if (saved.frames.get(index) == entry.frame) {
                        saved.frames.remove(index);
                        saved.frameCounts.remove(index + 1);
                        break;
                    }
                }
            }
        }
    }

    static boolean enterRegion(String regionId, String callSite, int iteration) {
        return enterRegion(regionId, callSite, iteration, null);
    }

    static boolean enterRegion(String regionId, String callSite, int iteration,
                               Object owner) {
        Context context = CURRENT.get();
        SourceRef selected = owner == null ? context.source : source(owner);
        if (owner != null && selected == null) {
            gap("UNREGISTERED_SOURCE", regionId, "region receiver not registered");
            return false;
        }
        SourceRef prior = context.source;
        context.source = selected;
        if (context.source == null || context.cause == null) {
            gap("UNATTRIBUTED_REGION", regionId, "no named source or scope");
            context.source = prior;
            return false;
        }
        String site = callSite == null || callSite.isEmpty() ? regionId : callSite;
        boolean sourceChanged = prior != null && !prior.equals(selected);
        OccurrenceAddress parent = context.regions.isEmpty() || sourceChanged
                ? roleOccurrence(context) : context.regions.peek();
        if (sourceChanged) {
            row("SOURCE_SWITCH", parent,
                    fields("sourceKey", selected.key(), "fromSourceKey", prior.key()));
        }
        context.pushFrame(Frame.of(site, nextFrame(context, "REGION", site)));
        OccurrenceAddress occurrence = OccurrenceAddress.of(
                NodeId.of(context.source.id(), (int) context.source.epoch()),
                regionId, context.cause, ExecutionIndex.of(context.frames));
        context.regions.push(occurrence);
        context.regionSources.push(new RegionSource(prior));
        // Keep the exact region address on the thread stack. Materialize its
        // graph node only when a selected observation uses this occurrence;
        // polling/getter regions without I/O, coverage, or target evidence do
        // not change the causal graph and need no million-row trace prefix.
        context.activations.push(new Activation(occurrence, parent));
        return true;
    }

    static void exitRegion(String regionId) {
        Context context = CURRENT.get();
        if (context.regions.isEmpty() || !regionId.equals(
                context.regions.peek().regionId())) {
            gap("REGION_UNBALANCED", regionId, "region exit");
            return;
        }
        if (context.frames.size() != context.regions.peek().index().frames().size()) {
            gap("REGION_UNBALANCED", regionId, "nested call not exited");
            return;
        }
        Activation completed = context.activations.peek();
        // A completed child invocation, including exceptional unwind, can
        // influence the caller's later branch. Record the completion only for
        // a child
        // whose selected I/O, coverage or target observation already caused
        // its activation to be materialized. Unobserved hot getters stay out
        // of the trace; static MAY scope remains responsible for them.
        synchronized (LOCK) {
            if (completed != null && completed.parent != null
                    && EMITTED_ACTIVATIONS.contains(completed.occurrence.id())) {
                row("REGION_COMPLETE", completed.occurrence,
                        fields("parentOccurrenceId", completed.parent.id(),
                                "parentOccurrence", completed.parent.render()));
            }
        }
        context.regions.pop();
        context.activations.pop();
        context.popFrame();
        context.source = context.regionSources.pop().prior;
    }

    static OccurrenceAddress occurrence(Object owner) {
        Context context = CURRENT.get();
        SourceRef source = owner == null ? context.source : source(owner);
        if (owner != null && source == null) {
            gap("UNREGISTERED_SOURCE", "occurrence", "explicit owner not registered");
            return null;
        }
        if (source == null) {
            gap("UNREGISTERED_SOURCE", "occurrence", "no owner or active source");
            return null;
        }
        if (!context.regions.isEmpty()) {
            OccurrenceAddress region = context.regions.peek();
            if (!region.node().render().equals(
                    NodeId.of(source.id(), (int) source.epoch()).render())) {
                gap("SOURCE_REGION_MISMATCH", source.key(), region.render());
                return null;
            }
            flushActivations(context);
            return region;
        }
        CausalContext cause = context.cause;
        if (cause == null) {
            gap("UNATTRIBUTED_ROOT", source.key(), "no request or daemon scope");
            cause = CausalContext.of(Role.of(source.role()));
        }
        return OccurrenceAddress.of(NodeId.of(source.id(), (int) source.epoch()),
                OccurrenceAddress.ROLE_REGION + Role.of(source.role()).name(),
                cause, ExecutionIndex.empty());
    }

    /** A replay selector separate from the exact GraphChecker occurrence. */
    static String replayOccurrenceId(OccurrenceAddress occurrence) {
        Context context = CURRENT.get();
        if (occurrence == null || context.cause == null
                || context.replayCause == null || context.replayCause.isEmpty()
                || !context.cause.equals(occurrence.context())) return "";
        return Digest.digest("replay-occurrence-v1\n" + occurrence.node().render()
                + "\n" + occurrence.regionId() + "\n" + context.replayCause
                + "\n" + occurrence.index().render(), 32);
    }

    static boolean hasAttributedScope(Object owner) {
        Context context = CURRENT.get();
        return context.cause != null &&
                (owner == null ? context.source != null : source(owner) != null);
    }

    static boolean hasActiveCause() {
        return CURRENT.get().cause != null;
    }

    static boolean hasSameOwnerCause(Object owner) {
        Context context = CURRENT.get();
        SourceRef selected = source(owner);
        return context.cause != null && context.source != null
                && context.source.equals(selected);
    }

    private static void flushActivations(Context context) {
        synchronized (LOCK) {
            for (java.util.Iterator<Activation> it =
                    context.activations.descendingIterator(); it.hasNext();) {
                Activation activation = it.next();
                if (!EMITTED_ACTIVATIONS.add(activation.occurrence.id())) continue;
                OccurrenceAddress parent = activation.parent;
                JsonObject values = fields("regionId", activation.occurrence.regionId(),
                        "parentOccurrenceId", parent == null ? "" : parent.id());
                String suffix = COMPACT_TRACE && parent != null
                        && EMITTED_ACTIVATIONS.contains(parent.id())
                        ? activationSuffix(parent, activation.occurrence) : null;
                if (suffix != null) {
                    // The parser reconstructs the exact address from the
                    // previously published parent and checks its digest.
                    values.addProperty("indexSuffix", suffix);
                    values.addProperty("parentIndexHash", parent.index().hash());
                } else {
                    values.addProperty("parentOccurrence",
                            parent == null ? "" : parent.render());
                }
                row("ACTIVATION", activation.occurrence, values);
            }
        }
    }

    private static String activationSuffix(OccurrenceAddress parent,
                                           OccurrenceAddress child) {
        if (!parent.node().equals(child.node())
                || !parent.context().equals(child.context())) return null;
        List<Frame> before = parent.index().frames();
        List<Frame> after = child.index().frames();
        if (after.size() <= before.size()) return null;
        for (int i = 0; i < before.size(); i++) {
            if (!before.get(i).equals(after.get(i))) return null;
        }
        StringBuilder suffix = new StringBuilder();
        for (int i = before.size(); i < after.size(); i++) {
            if (suffix.length() > 0) suffix.append('/');
            suffix.append(after.get(i).render());
        }
        return suffix.toString();
    }

    static boolean hasActiveRegion(Object owner) {
        Context context = CURRENT.get();
        if (context.regions.isEmpty()) return false;
        SourceRef source = source(owner);
        return source != null && context.regions.peek().node().render().equals(
                NodeId.of(source.id(), (int) source.epoch()).render());
    }

    static boolean hasAnyActiveRegion() {
        return !CURRENT.get().regions.isEmpty();
    }

    private static OccurrenceAddress roleOccurrence(Context context) {
        if (context.source == null || context.cause == null) return null;
        return OccurrenceAddress.of(NodeId.of(context.source.id(),
                        (int) context.source.epoch()),
                OccurrenceAddress.ROLE_REGION + Role.of(context.source.role()).name(),
                context.cause, ExecutionIndex.empty());
    }

    static Endpoint endpoint(Object owner, String site, int attempt) {
        OccurrenceAddress occurrence = occurrence(owner);
        return occurrence == null ? null : Endpoint.of(occurrence,
                site == null || site.isEmpty() ? "UNSTATED_SITE" : site,
                ExecutionIndex.empty(), Math.max(0, attempt));
    }

    static Endpoint messageEndpoint(Object owner, String site,
                                    String correlationId, String attemptId) {
        OccurrenceAddress occurrence = occurrence(owner);
        if (occurrence == null) return null;
        // Several messages can leave the same role occurrence and port. The
        // transported correlation and retry are part of the message instance;
        // place their digest in the site index to keep Endpoint.site the
        // declared port while preserving one-to-one wire pairing.
        String identity = edu.uva.liftlab.mallory.graphchecker.contract.Digest
                .digest(correlationId + "\n" + attemptId, 24);
        return Endpoint.of(occurrence, site,
                ExecutionIndex.of(java.util.Collections.singletonList(
                        Frame.of("transport.message." + identity, 0))), 0);
    }

    static Endpoint stateEndpoint(Object owner, String site,
                                  String locationVersion, int attempt) {
        OccurrenceAddress occurrence = occurrence(owner);
        if (occurrence == null) return null;
        // A single occurrence may persist or fetch several versions through
        // the same port. Keep the declared READ/WRITE port in Endpoint.site,
        // and distinguish the exact versions in its site index. Otherwise the
        // graph coalesces their edges and can lose a read before the target.
        String identity = Digest.digest(locationVersion, 24);
        return Endpoint.of(occurrence, site,
                ExecutionIndex.of(java.util.Collections.singletonList(
                        Frame.of("state.version." + identity, 0))),
                Math.max(0, attempt));
    }

    private static int nextFrame(Context context, String kind, String site) {
        // A frame's child counts are needed only while that exact frame is
        // active. Its iteration makes the next invocation a distinct parent,
        // so discarding the child map on return preserves occurrence identity
        // without retaining all historical call paths for a long JUnit run.
        Map<String, Integer> children = context.frameCounts.get(
                context.frameCounts.size() - 1);
        String key = kind + "\n" + site;
        int next = children.getOrDefault(key, 0);
        children.put(key, next + 1);
        return next;
    }

    private static List<Map<String, Integer>> copyFrameCounts(
            List<Map<String, Integer>> counts) {
        List<Map<String, Integer>> copied = new ArrayList<>(counts.size());
        for (Map<String, Integer> level : counts) copied.add(new HashMap<>(level));
        return copied;
    }

    static void row(String kind, OccurrenceAddress occurrence, JsonObject values) {
        JsonObject row = values == null ? new JsonObject() : values;
        row.addProperty("kind", kind);
        if (occurrence != null) {
            row.addProperty("occurrenceId", occurrence.id());
            row.addProperty("regionId", occurrence.regionId());
            row.addProperty("node", occurrence.node().render());
        }
        row.addProperty("threadKey", String.valueOf(Thread.currentThread().getId()));
        synchronized (LOCK) {
            if (closed || writerFailed) return;
            try {
                open();
                if (writer == null) return;
                // A materialized ACTIVATION already carries this exact path.
                // Keep the legacy encoding by default, and retain full paths
                // for role occurrences without an activation in this trace.
                if (occurrence != null && COMPACT_TRACE
                        && ("COVERAGE".equals(kind) || "FAULT_DOOR".equals(kind)
                                || "REGION_COMPLETE".equals(kind))
                        && EMITTED_ACTIVATIONS.contains(occurrence.id())) {
                    row.addProperty("occurrenceRef", "ACTIVATION");
                } else if (occurrence != null
                        && !(COMPACT_TRACE && "ACTIVATION".equals(kind)
                                && row.has("indexSuffix"))) {
                    row.addProperty("occurrence", occurrence.render());
                }
                if (COMPACT_TRACE && ("ACTIVATION".equals(kind)
                        || "REGION_COMPLETE".equals(kind))
                        && row.has("parentOccurrenceId")
                        && EMITTED_ACTIVATIONS.contains(
                                row.get("parentOccurrenceId").getAsString())) {
                    // The exact full parent path was already emitted once.
                    // The parser checks and restores that prior activation.
                    row.remove("parentOccurrence");
                    row.addProperty("parentOccurrenceRef", "ACTIVATION");
                }
                row.addProperty("seq", ++sequence);
                writer.write(GSON.toJson(row));
                writer.newLine();
                writer.flush();
            } catch (IOException failure) {
                writerFailed = true;
                try { if (writer != null) writer.close(); }
                catch (IOException ignored) { }
                writer = null;
                System.err.println("Mallory GraphChecker trace unavailable: " + failure);
            }
        }
    }

    static JsonObject fields(Object... pairs) {
        JsonObject row = new JsonObject();
        for (int index = 0; index < pairs.length; index += 2) {
            Object value = pairs[index + 1];
            if (value != null) row.add(String.valueOf(pairs[index]),
                    GSON.toJsonTree(value));
        }
        return row;
    }

    static void gap(String kind, String subject, String detail) {
        if ("UNATTRIBUTED_REGION".equals(kind)) {
            String key = Thread.currentThread().getId() + "\n" + subject;
            if (UNATTRIBUTED_REGION_COUNTS.computeIfAbsent(key,
                    ignored -> new AtomicLong()).incrementAndGet() > 1) return;
        }
        row("GAP", null, fields("gapKind", kind, "subject", subject,
                "detail", detail));
    }

    static void beginGapWindow() {
        UNATTRIBUTED_REGION_COUNTS.clear();
    }

    static void flushSuppressedRegionGaps() {
        for (Map.Entry<String, AtomicLong> entry : UNATTRIBUTED_REGION_COUNTS.entrySet()) {
            long suppressed = entry.getValue().get() - 1;
            if (suppressed <= 0) continue;
            String[] key = entry.getKey().split("\n", 2);
            row("GAP", null, fields("gapKind", "UNATTRIBUTED_REGION_COALESCED",
                    "subject", key[1], "sourceThreadKey", key[0],
                    "suppressedCount", suppressed));
        }
        UNATTRIBUTED_REGION_COUNTS.clear();
    }

    static void close() {
        synchronized (LOCK) {
            closed = true;
            if (writer == null) return;
            try { writer.close(); }
            catch (IOException failure) {
                System.err.println("Mallory GraphChecker trace close failed: " + failure);
            }
            writer = null;
        }
    }

    private static void open() throws IOException {
        if (writer != null) return;
        String path = System.getProperty("mallory.graphchecker.trace.file",
                System.getenv("MALLORY_GC_TRACE"));
        if (path == null || path.isEmpty()) return;
        Path file = Paths.get(path);
        Path parent = file.toAbsolutePath().getParent();
        if (parent != null) Files.createDirectories(parent);
        // A NIO FileChannel is interruptible. Cluster JUnits routinely
        // interrupt worker threads during shutdown; that must not close the
        // shared recorder or change the system's own failure behavior.
        writer = new BufferedWriter(new OutputStreamWriter(
                new FileOutputStream(file.toFile(), false), StandardCharsets.UTF_8));
        Runtime.getRuntime().addShutdownHook(new Thread(TraceRows::close,
                "mallory-graphchecker-trace-close"));
    }

    static final class Context {
        SourceRef source;
        CausalContext cause;
        String replayCause;
        final List<Frame> frames = new ArrayList<>();
        final Deque<OccurrenceAddress> regions = new ArrayDeque<>();
        final Deque<RegionSource> regionSources = new ArrayDeque<>();
        final Deque<Activation> activations = new ArrayDeque<>();
        final Deque<CallEntry> calls = new ArrayDeque<>();
        final List<Map<String, Integer>> frameCounts = new ArrayList<>();
        final Deque<Saved> saved = new ArrayDeque<>();
        long nextToken;

        Context() { frameCounts.add(new HashMap<String, Integer>()); }

        void pushFrame(Frame frame) {
            frames.add(frame);
            frameCounts.add(new HashMap<String, Integer>());
        }

        void popFrame() {
            frames.remove(frames.size() - 1);
            frameCounts.remove(frameCounts.size() - 1);
        }

        void resetFrames() {
            frames.clear();
            frameCounts.clear();
            frameCounts.add(new HashMap<String, Integer>());
        }

        void restoreFrames(List<Frame> restored,
                           List<Map<String, Integer>> counts) {
            if (counts.size() != restored.size() + 1) {
                throw new IllegalArgumentException("frame count depth mismatch");
            }
            frames.clear();
            frames.addAll(restored);
            frameCounts.clear();
            frameCounts.addAll(copyFrameCounts(counts));
        }

        Context copy() {
            Context result = new Context();
            result.source = source;
            result.cause = cause;
            result.replayCause = replayCause;
            result.restoreFrames(frames, frameCounts);
            result.regions.addAll(regions);
            result.regionSources.addAll(regionSources);
            result.activations.addAll(activations);
            result.calls.addAll(calls);
            for (Saved snapshot : saved) result.saved.addLast(snapshot.copy());
            result.nextToken = nextToken;
            return result;
        }
    }

    private static final class Saved {
        final long token;
        OccurrenceAddress enteredOccurrence;
        boolean enteredRoot;
        final SourceRef source;
        final CausalContext cause;
        final String replayCause;
        final List<Frame> frames;
        final Deque<OccurrenceAddress> regions;
        final Deque<RegionSource> regionSources;
        final Deque<Activation> activations;
        final Deque<CallEntry> calls;
        final List<Map<String, Integer>> frameCounts;

        Saved(long token, SourceRef source, CausalContext cause,
              String replayCause,
              List<Frame> frames, Deque<OccurrenceAddress> regions,
              Deque<CallEntry> calls, List<Map<String, Integer>> frameCounts,
              Deque<RegionSource> regionSources, Deque<Activation> activations) {
            this.token = token;
            this.source = source;
            this.cause = cause;
            this.replayCause = replayCause;
            this.frames = frames;
            this.regions = regions;
            this.regionSources = regionSources;
            this.activations = activations;
            this.calls = calls;
            this.frameCounts = frameCounts;
        }

        Saved copy() {
            Saved result = new Saved(token, source, cause, replayCause,
                    new ArrayList<>(frames),
                    new ArrayDeque<>(regions), new ArrayDeque<>(calls),
                    copyFrameCounts(frameCounts), new ArrayDeque<>(regionSources),
                    new ArrayDeque<>(activations));
            result.enteredOccurrence = enteredOccurrence;
            result.enteredRoot = enteredRoot;
            return result;
        }
    }

    private static final class RegionSource {
        final SourceRef prior;
        RegionSource(SourceRef prior) { this.prior = prior; }
    }

    private static final class Activation {
        final OccurrenceAddress occurrence;
        final OccurrenceAddress parent;

        Activation(OccurrenceAddress occurrence, OccurrenceAddress parent) {
            this.occurrence = occurrence;
            this.parent = parent;
        }
    }

    private static final class CallEntry {
        final String site;
        final Object receipt;
        final Frame frame;

        CallEntry(String site, Object receipt, Frame frame) {
            this.site = site;
            this.receipt = receipt;
            this.frame = frame;
        }
    }
}
