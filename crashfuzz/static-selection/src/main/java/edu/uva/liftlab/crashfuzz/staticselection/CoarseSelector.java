package edu.uva.liftlab.crashfuzz.staticselection;

import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import soot.Body;
import soot.Local;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.Type;
import soot.Unit;
import soot.Value;
import soot.ValueBox;
import soot.jimple.AssignStmt;
import soot.jimple.FieldRef;
import soot.jimple.InstanceInvokeExpr;
import soot.jimple.IfStmt;
import soot.jimple.InvokeExpr;
import soot.jimple.NewExpr;
import soot.jimple.SpecialInvokeExpr;
import soot.jimple.Stmt;
import soot.jimple.CastExpr;
import soot.jimple.ThrowStmt;
import soot.options.Options;
import soot.toolkits.graph.BriefUnitGraph;
import soot.toolkits.graph.ExceptionalUnitGraph;
import soot.toolkits.scalar.SimpleLocalDefs;

import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** A bounded, method-level Soot hint for the CrashFuzz coverage/I/O scheduler. */
public final class CoarseSelector {
    private static final List<String> DEFAULT_IO = Arrays.asList(
            "java.io.", "java.nio.channels.", "java.nio.file.Files",
            "java.net.Socket", "java.net.DatagramSocket", "java.net.URLConnection",
            "org.apache.hadoop.ipc.",
            "org.apache.hadoop.hdfs.protocol.ClientProtocol",
            "org.apache.hadoop.hdfs.protocol.ClientDatanodeProtocol",
            "org.apache.hadoop.hdfs.server.protocol.DatanodeProtocol",
            "org.apache.hadoop.hdfs.server.protocol.NamenodeProtocol",
            "org.apache.hadoop.hdfs.server.protocol.InterDatanodeProtocol",
            "org.apache.hadoop.hdfs.server.protocol.JournalProtocol",
            "org.apache.hadoop.hbase.client.Table",
            "org.apache.hadoop.hbase.client.Admin",
            "org.apache.hadoop.hbase.client.Connection",
            "org.apache.hadoop.hbase.client.ResultScanner",
            "org.apache.solr.client.solrj.SolrClient");

    private static boolean isIoCall(Invocation call, List<String> patterns) {
        if ("<init>".equals(call.name) || "<clinit>".equals(call.name)) return false;
        if (call.owner.startsWith("java.io.")) {
            if (call.owner.contains("ByteArray") || call.owner.endsWith("Exception")
                    || call.owner.endsWith("Error")) return false;
            return Arrays.asList("read", "write", "flush", "close", "sync", "skip",
                    "exists", "createNewFile", "delete", "renameTo", "listFiles",
                    "mkdir", "mkdirs", "getFD", "getChannel").contains(call.name)
                    || call.name.startsWith("read") || call.name.startsWith("write");
        }
        if (call.owner.startsWith("java.nio.channels.")) {
            return Arrays.asList("read", "write", "readv", "writev", "connect",
                    "finishConnect", "accept", "bind", "send", "receive", "transferTo",
                    "transferFrom", "force", "truncate", "lock", "tryLock", "select",
                    "selectNow", "close").contains(call.name);
        }
        if (call.owner.startsWith("java.net.Socket") ||
                call.owner.startsWith("java.net.DatagramSocket")) {
            return Arrays.asList("connect", "bind", "send", "receive", "getInputStream",
                    "getOutputStream", "close", "shutdownInput", "shutdownOutput")
                    .contains(call.name);
        }
        if (call.owner.startsWith("org.apache.hadoop.ipc.")) {
            return Arrays.asList("call", "sendRpcRequest", "receiveRpcResponse",
                    "getProxy", "waitForProxy").contains(call.name);
        }
        // HDFS data-transfer SASL is application-level network I/O. The
        // handshake parses a remote response and can report a typed I/O
        // failure before the block request is sent.
        if (call.owner.startsWith(
                "org.apache.hadoop.hdfs.protocol.datatransfer.sasl.")) {
            return "socketSend".equals(call.name)
                    || call.name.startsWith("readSaslMessage");
        }
        // HDFS DataNode and NameNode code calls the generated client-side
        // translator, rather than the DatanodeProtocol interface directly.
        if (call.owner.startsWith("org.apache.hadoop.hdfs.protocolPB.")
                && call.owner.endsWith("ClientSideTranslatorPB")) return true;
        if (call.owner.startsWith("org.apache.hadoop.hbase.ipc.")) {
            return Arrays.asList("call", "callBlockingMethod", "callMethod",
                    "sendRequest", "writeRequest", "readResponse").contains(call.name);
        }
        if (call.owner.contains("protobuf") && ("callBlockingMethod".equals(call.name)
                || call.owner.endsWith("$BlockingInterface"))) return true;
        if (call.owner.startsWith("org.apache.zookeeper.ZooKeeper")) {
            return Arrays.asList("create", "delete", "exists", "getData", "setData",
                    "getChildren", "multi", "sync", "close", "addWatch",
                    "removeWatches", "getACL", "setACL").contains(call.name);
        }
        if (call.owner.startsWith("org.apache.zookeeper.ClientCnxn")) {
            return Arrays.asList("submitRequest", "submitRequestNow", "queuePacket",
                    "sendPacket", "sendRequest", "readResponse").contains(call.name);
        }
        if (call.owner.startsWith("org.apache.solr.common.cloud.SolrZkClient")) {
            return Arrays.asList("getData", "exists", "setData", "makePath", "create",
                    "delete", "getChildren", "multi", "atomicUpdate", "close").contains(
                            call.name);
        }
        for (String pattern : patterns) {
            if ((pattern.endsWith(".") && call.owner.startsWith(pattern))
                    || call.owner.equals(pattern)
                    || call.owner.startsWith(pattern + "$")) return true;
        }
        return false;
    }

    private CoarseSelector() {}

    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            throw new IllegalArgumentException("usage: CoarseSelector input.json output.json");
        }
        JsonObject input = JsonParser.parseString(new String(
                Files.readAllBytes(Paths.get(args[0])), StandardCharsets.UTF_8)).getAsJsonObject();
        JsonObject result = analyze(input);
        Files.write(Paths.get(args[1]), new GsonBuilder().setPrettyPrinting().create()
                .toJson(result).getBytes(StandardCharsets.UTF_8));
    }

    public static JsonObject analyze(JsonObject input) {
        String target = required(input, "target_method");
        JsonObject analysis = input.getAsJsonObject("analysis");
        if (analysis == null) throw new IllegalArgumentException("analysis object is required");
        List<String> processDirs = strings(analysis, "process_dirs");
        List<String> classpath = strings(analysis, "classpath");
        if (processDirs.isEmpty()) throw new IllegalArgumentException("analysis.process_dirs is required");
        for (String path : processDirs) {
            if (!new File(path).exists()) throw new IllegalArgumentException("missing process_dir: " + path);
        }
        int callerDepth = number(analysis, "max_caller_depth", 2);
        int calleeDepth = number(analysis, "max_callee_depth", 2);
        int jumpDepth = number(analysis, "max_jump_depth", 3);
        int maxMethods = number(analysis, "max_methods", 400);
        if (callerDepth < 0 || calleeDepth < 0 || jumpDepth < 0 || maxMethods < 1) {
            throw new IllegalArgumentException("analysis depths must be nonnegative; max_methods must be positive");
        }
        List<String> ioPatterns = strings(analysis, "io_patterns");
        if (ioPatterns.isEmpty()) ioPatterns = DEFAULT_IO;

        soot.G.reset();
        Options.v().set_prepend_classpath(true);
        Options.v().set_allow_phantom_refs(true);
        Options.v().set_whole_program(false);
        Options.v().set_output_format(Options.output_format_none);
        Options.v().set_keep_line_number(true);
        Options.v().set_process_dir(processDirs);
        Options.v().set_soot_classpath(String.join(File.pathSeparator, classpath));
        Scene.v().loadNecessaryClasses();

        Map<String, MethodInfo> methods = new LinkedHashMap<>();
        Set<String> gaps = new LinkedHashSet<>();
        List<SootClass> classes = new ArrayList<>();
        for (SootClass owner : Scene.v().getApplicationClasses()) classes.add(owner);
        classes.sort((left, right) -> left.getName().compareTo(right.getName()));
        for (SootClass owner : classes) {
            for (SootMethod method : owner.getMethods()) {
                if (!method.isConcrete()) continue;
                try {
                    MethodInfo info = new MethodInfo(method, method.retrieveActiveBody(), ioPatterns);
                    methods.put(info.signature, info);
                } catch (RuntimeException error) {
                    gaps.add("body_unavailable:" + method.getSignature());
                }
            }
        }
        if (!methods.containsKey(target)) {
            throw new IllegalArgumentException("target method not found in process_dirs: " + target);
        }

        Map<String, Set<String>> callers = new HashMap<>();
        Map<String, Set<String>> writers = new HashMap<>();
        Map<String, Set<String>> callTargets = new HashMap<>();
        Set<String> directIoMethods = new HashSet<>();
        Map<String, List<MethodInfo>> bySubSignature = new HashMap<>();
        for (MethodInfo info : methods.values()) {
            bySubSignature.computeIfAbsent(info.method.getSubSignature(),
                    ignored -> new ArrayList<>()).add(info);
        }
        for (MethodInfo info : methods.values()) {
            if (!info.ioCalls.isEmpty()) directIoMethods.add(info.signature);
            Set<String> resolved = new LinkedHashSet<>();
            for (Invocation invocation : info.invocations) {
                if (methods.containsKey(invocation.signature)) resolved.add(invocation.signature);
                if (invocation.dynamic) {
                    for (MethodInfo candidate : bySubSignature.getOrDefault(
                            invocation.subSignature, Collections.emptyList())) {
                        if (subtype(candidate.method.getDeclaringClass(), invocation.owner)) {
                            resolved.add(candidate.signature);
                        }
                    }
                }
            }
            callTargets.put(info.signature, resolved);
            for (String callee : resolved) {
                callers.computeIfAbsent(callee, ignored -> new LinkedHashSet<>()).add(info.signature);
            }
            for (String field : info.writes) {
                writers.computeIfAbsent(field, ignored -> new LinkedHashSet<>()).add(info.signature);
            }
        }

        Map<String, Set<String>> wireProducers = wireProducers(analysis, methods, gaps);
        deriveProtobufPorts(methods, wireProducers, gaps);
        Map<String, Set<String>> taskLaunchers = taskLaunchers(methods, gaps);

        LinkedHashMap<String, String> selected = new LinkedHashMap<>();
        add(selected, target, "target", maxMethods, gaps);
        int shortCallLimit = Math.max(1, maxMethods / 4);
        int fieldWriterLimit = Math.max(shortCallLimit, maxMethods / 2);
        int writerCallerLimit = Math.max(fieldWriterLimit, maxMethods * 3 / 4);
        // Reserve the short value path from the check before broad caller,
        // thread, and wire jumps consume the instrumentation budget. A cached
        // value commonly flows through two getters, a field writer, and the
        // writer's asynchronous callback (for example a ZooKeeper watch).
        Set<String> near = new LinkedHashSet<>();
        near.add(target);
        Set<String> frontier = new LinkedHashSet<>(near);
        for (int depth = 0; depth < 2; depth++) {
            Set<String> next = new LinkedHashSet<>();
            for (String method : sorted(frontier)) {
                MethodInfo info = methods.get(method);
                if (info == null) continue;
                for (Invocation invocation : info.invocations) {
                    if (methods.containsKey(invocation.signature))
                        next.add(invocation.signature);
                }
                next.addAll(sorted(callTargets.getOrDefault(method,
                        Collections.emptySet())));
            }
            Set<String> accepted = new LinkedHashSet<>();
            for (String method : next) {
                if (methods.containsKey(method)) {
                    add(selected, method, "target_short_call_path", shortCallLimit, gaps);
                    if (selected.containsKey(method)) {
                        near.add(method);
                        accepted.add(method);
                    }
                }
            }
            frontier = accepted;
        }
        // A mapped wire value is produced on the sending actor. Follow the
        // producer's callers far enough to reach the actual send boundary:
        // helper -> encoder -> transport -> RPC handler is commonly longer
        // than the general two-caller walk. Reserve a bounded slice before
        // field-writer expansion consumes the method budget.
        extendWireSenderCallers(selected, near, wireProducers, callers,
                directIoMethods, Math.min(maxMethods, Math.max(selected.size(),
                        maxMethods * 3 / 8)), gaps);
        Set<String> directWriters = new LinkedHashSet<>();
        MethodInfo targetInfo = methods.get(target);
        for (String field : sorted(targetInfo.reads)) {
            for (String writer : sorted(writers.getOrDefault(field,
                    Collections.emptySet()))) {
                add(selected, writer, "target_direct_field_writer:" + field,
                        fieldWriterLimit, gaps);
                if (selected.containsKey(writer)) directWriters.add(writer);
            }
        }
        Set<String> nearWriters = new LinkedHashSet<>();
        for (String method : sorted(near)) {
            MethodInfo info = methods.get(method);
            if (info == null) continue;
            for (String field : sorted(info.reads)) {
                for (String writer : sorted(writers.getOrDefault(field,
                        Collections.emptySet()))) {
                    add(selected, writer, "target_short_field_writer:" + field,
                            fieldWriterLimit, gaps);
                    if (selected.containsKey(writer)) nearWriters.add(writer);
                }
            }
        }
        // The value read by a check may be refreshed by a callback nested in
        // the same actor as a selected getter or field writer. Callback
        // dispatch is often invisible to the ordinary call graph, so reserve
        // a small part of the scope for I/O methods in those actor families.
        // This runs before broad caller traversal can consume the budget.
        Set<String> actorRoots = new LinkedHashSet<>(near);
        actorRoots.addAll(directWriters);
        actorRoots.addAll(nearWriters);
        extendActorIoMethods(selected, actorRoots, methods,
                Math.min(maxMethods, Math.max(fieldWriterLimit, maxMethods * 3 / 4)),
                Math.max(1, maxMethods / 8), gaps);
        // Prefer the check's directly read fields. Their writers may be
        // wrapped by several local calls before the RPC/async handler that
        // installs a value, so follow that chain farther than other fields.
        Set<String> writerAncestors = extendWriterCallers(selected, directWriters,
                callers, directIoMethods, 5, 8,
                new int[] {maxMethods / 2, maxMethods * 5 / 8,
                        writerCallerLimit, maxMethods * 7 / 8,
                        maxMethods * 15 / 16}, maxMethods, gaps);
        // A field writer can be reached through a message handler whose
        // enclosing actor performs the actual RPC in a sibling method. Follow
        // local calls from the writer's higher callers before the broad walk.
        Set<String> writerNeighborhood = new LinkedHashSet<>(directWriters);
        writerNeighborhood.addAll(nearWriters);
        writerNeighborhood.addAll(writerAncestors);
        for (Map.Entry<String, String> entry : selected.entrySet()) {
            if (entry.getValue().startsWith("target_short_writer_caller")) {
                writerNeighborhood.add(entry.getKey());
            }
        }
        extendLocalCallees(selected, writerNeighborhood, callTargets, methods,
                2, 8, maxMethods, gaps);
        nearWriters.removeAll(directWriters);
        extendWriterCallers(selected, nearWriters, callers, directIoMethods, 2, 8,
                new int[] {maxMethods * 15 / 16, maxMethods * 15 / 16},
                maxMethods, gaps);
        Deque<Step> pending = new ArrayDeque<>();
        pending.add(new Step(target, 0, 0, 0, false));
        Set<String> seen = new HashSet<>();
        while (!pending.isEmpty()) {
            Step step = pending.removeFirst();
            if (!seen.add(step.key())) continue;
            MethodInfo info = methods.get(step.method);
            if (!step.callsPhase) {
                pending.addFirst(new Step(step.method, step.callerDepth,
                        step.calleeDepth, step.jumpDepth, true));
            }
            if (!step.callsPhase && step.jumpDepth < jumpDepth) {
                for (String field : sorted(info.reads)) {
                    for (String writer : sorted(writers.getOrDefault(field, Collections.emptySet()))) {
                        visit(selected, pending, writer, "field_may_writer:" + field,
                                new Step(writer, 0, 0, step.jumpDepth + 1, false),
                                true, maxMethods, gaps);
                    }
                }
                for (String producer : sorted(wireProducers.getOrDefault(
                        step.method, Collections.emptySet()))) {
                    visit(selected, pending, producer, "rpc_wire_may_producer",
                            new Step(producer, 0, 0, step.jumpDepth + 1, false),
                            true, maxMethods, gaps);
                }
                for (String launcher : sorted(taskLaunchers.getOrDefault(
                        step.method, Collections.emptySet()))) {
                    visit(selected, pending, launcher, "thread_handoff_may_launcher",
                            new Step(launcher, 0, 0, step.jumpDepth + 1, false),
                            true, maxMethods, gaps);
                }
            }
            if (!step.callsPhase) continue;
            if (step.callerDepth < callerDepth) {
                for (String caller : sorted(callers.getOrDefault(step.method, Collections.emptySet()))) {
                    visit(selected, pending, caller, "caller_may_dispatch",
                            new Step(caller, step.callerDepth + 1, step.calleeDepth,
                                    step.jumpDepth, false), false, maxMethods, gaps);
                }
            }
            if (step.calleeDepth < calleeDepth) {
                for (String callee : sorted(callTargets.getOrDefault(
                        step.method, Collections.emptySet()))) {
                    visit(selected, pending, callee, "callee_may_dispatch",
                            new Step(callee, step.callerDepth, step.calleeDepth + 1,
                                    step.jumpDepth, false), false, maxMethods, gaps);
                }
            }
        }

        JsonArray coverage = new JsonArray();
        JsonArray ioMethods = new JsonArray();
        JsonArray ioCalls = new JsonArray();
        JsonArray methodSpecs = new JsonArray();
        JsonArray branches = new JsonArray();
        JsonArray targetThrowSites = new JsonArray();
        JsonObject reasons = new JsonObject();
        for (String signature : sorted(selected.keySet())) {
            coverage.add(signature);
            reasons.addProperty(signature, selected.get(signature));
            MethodInfo info = methods.get(signature);
            JsonObject methodSpec = new JsonObject();
            methodSpec.addProperty("signature", signature);
            methodSpec.addProperty("owner", info.method.getDeclaringClass().getName()
                    .replace('.', '/'));
            methodSpec.addProperty("name", info.method.getName());
            methodSpec.addProperty("descriptor", descriptor(info.method));
            methodSpecs.add(methodSpec);
            if (!info.ioCalls.isEmpty()) ioMethods.add(signature);
            for (IoCall call : info.ioCalls) {
                JsonObject row = new JsonObject();
                row.addProperty("method", signature);
                row.addProperty("callee", call.callee);
                row.addProperty("line", call.line);
                row.addProperty("unit_index", call.unitIndex);
                row.addProperty("site_id", signature + "#u" + call.unitIndex);
                row.addProperty("call_owner", call.owner.replace('.', '/'));
                row.addProperty("call_name", call.name);
                row.addProperty("call_descriptor", call.descriptor);
                row.addProperty("line_ordinal", call.lineOrdinal);
                row.addProperty("selection_reason", selected.get(signature));
                row.add("exception_candidates", exceptionCandidates(
                        call.callee, methods, callTargets));
                ioCalls.add(row);
            }
            for (Branch branch : info.branches) {
                JsonObject row = new JsonObject();
                row.addProperty("method", signature);
                row.addProperty("site_id", signature + "#u" + branch.unitIndex);
                row.addProperty("line", branch.line);
                row.addProperty("line_ordinal", branch.lineOrdinal);
                branches.add(row);
            }
            if (signature.equals(target)) {
                for (ThrowSite site : info.throwSites) {
                    JsonObject row = new JsonObject();
                    row.addProperty("method", signature);
                    row.addProperty("soot_site_id", signature + "#u" + site.unitIndex);
                    row.addProperty("line", site.line);
                    row.addProperty("unit_index", site.unitIndex);
                    row.addProperty("thrown_type", site.thrownType);
                    JsonArray controls = new JsonArray();
                    for (String branch : site.controlledBy) controls.add(branch);
                    row.add("controlled_by", controls);
                    targetThrowSites.add(row);
                }
            }
        }
        if (ioMethods.size() == 0) gaps.add("no_static_io_call_in_selected_methods");
        JsonObject result = new JsonObject();
        result.addProperty("schema_version", 1);
        result.addProperty("analysis_kind", "crashfuzz_coarse_soot_selection");
        result.addProperty("target_method", target);
        result.add("coverage_methods", coverage);
        result.add("io_methods", ioMethods);
        result.add("io_calls", ioCalls);
        result.add("method_specs", methodSpecs);
        result.add("branches", branches);
        result.add("target_throw_sites", targetThrowSites);
        result.add("selection_reasons", reasons);
        JsonArray gapRows = new JsonArray();
        for (String gap : gaps) gapRows.add(gap);
        result.add("gaps", gapRows);
        return result;
    }

    private static void visit(Map<String, String> selected, Deque<Step> pending,
                              String method, String reason, Step next,
                              boolean front, int limit, Set<String> gaps) {
        add(selected, method, reason, limit, gaps);
        if (selected.containsKey(method)) {
            if (front) pending.addFirst(next);
            else pending.addLast(next);
        }
    }

    private static Set<String> extendWriterCallers(Map<String, String> selected,
            Set<String> roots, Map<String, Set<String>> callers,
            Set<String> directIoMethods, int depthLimit,
            int fanout, int[] limits, int maxMethods, Set<String> gaps) {
        Set<String> frontier = roots;
        Set<String> higherCallers = new LinkedHashSet<>();
        for (int depth = 1; depth <= depthLimit && !frontier.isEmpty(); depth++) {
            Set<String> next = new LinkedHashSet<>();
            for (String writer : sorted(frontier)) {
                List<String> nearCallers = prioritizedCallers(writer, callers,
                        directIoMethods);
                for (int i = 0; i < Math.min(fanout, nearCallers.size()); i++) {
                    String caller = nearCallers.get(i);
                    add(selected, caller, "target_short_writer_caller_depth_" + depth,
                            Math.min(maxMethods, Math.max(1, limits[depth - 1])), gaps);
                    if (selected.containsKey(caller)) {
                        next.add(caller);
                        if (depth >= 3) higherCallers.add(caller);
                    }
                }
            }
            frontier = next;
        }
        return higherCallers;
    }

    private static List<String> prioritizedCallers(String callee,
            Map<String, Set<String>> callers, Set<String> directIoMethods) {
        List<String> result = sorted(callers.getOrDefault(callee,
                Collections.emptySet()));
        String owner = callee.substring(0, callee.indexOf(':'));
        result.sort((left, right) -> {
            // A direct I/O caller is itself an injectable boundary, including
            // one reached after dispatch into another actor.
            int byIo = Boolean.compare(directIoMethods.contains(right),
                    directIoMethods.contains(left));
            if (byIo != 0) return byIo;
            boolean leftLocal = left.startsWith(owner + ":");
            boolean rightLocal = right.startsWith(owner + ":");
            int byLocal = Boolean.compare(rightLocal, leftLocal);
            return byLocal != 0 ? byLocal : left.compareTo(right);
        });
        return result;
    }

    private static void extendWireSenderCallers(Map<String, String> selected,
            Set<String> consumers, Map<String, Set<String>> wireProducers,
            Map<String, Set<String>> callers, Set<String> directIoMethods,
            int limit, Set<String> gaps) {
        for (String consumer : consumers) {
            for (String producer : sorted(wireProducers.getOrDefault(consumer,
                    Collections.emptySet()))) {
                add(selected, producer, "rpc_wire_may_producer", limit, gaps);
                if (!selected.containsKey(producer)) continue;
                Set<String> frontier = Collections.singleton(producer);
                for (int depth = 1; depth <= 5 && !frontier.isEmpty(); depth++) {
                    Set<String> next = new LinkedHashSet<>();
                    for (String method : sorted(frontier)) {
                        List<String> nearCallers = prioritizedCallers(method,
                                callers, directIoMethods);
                        for (int i = 0; i < Math.min(4, nearCallers.size()); i++) {
                            String caller = nearCallers.get(i);
                            add(selected, caller,
                                    "rpc_wire_sender_caller_depth_" + depth,
                                    limit, gaps);
                            if (selected.containsKey(caller)) next.add(caller);
                        }
                    }
                    frontier = next;
                }
            }
        }
    }

    private static void extendLocalCallees(Map<String, String> selected,
            Set<String> roots, Map<String, Set<String>> callTargets,
            Map<String, MethodInfo> methods, int depthLimit, int fanout,
            int maxMethods, Set<String> gaps) {
        for (String root : sorted(roots)) {
            Set<String> frontier = Collections.singleton(root);
            for (int depth = 1; depth <= depthLimit && !frontier.isEmpty(); depth++) {
                Set<String> next = new LinkedHashSet<>();
                for (String method : sorted(frontier)) {
                    String owner = method.substring(0, method.indexOf(':'));
                    List<String> local = new ArrayList<>();
                    for (String callee : callTargets.getOrDefault(method,
                            Collections.emptySet())) {
                        String calleeOwner = callee.substring(0, callee.indexOf(':'));
                        if (calleeOwner.equals(owner)
                                || calleeOwner.startsWith(owner + "$")
                                || owner.startsWith(calleeOwner + "$")) local.add(callee);
                    }
                    local.sort((left, right) -> {
                        boolean leftIo = !methods.get(left).ioCalls.isEmpty();
                        boolean rightIo = !methods.get(right).ioCalls.isEmpty();
                        int byIo = Boolean.compare(rightIo, leftIo);
                        return byIo != 0 ? byIo : left.compareTo(right);
                    });
                    for (int i = 0; i < Math.min(fanout, local.size()); i++) {
                        String callee = local.get(i);
                        add(selected, callee,
                                "target_writer_actor_callee_depth_" + depth,
                                maxMethods, gaps);
                        if (selected.containsKey(callee)) next.add(callee);
                    }
                }
                frontier = next;
            }
        }
    }

    private static void extendActorIoMethods(Map<String, String> selected,
            Set<String> roots, Map<String, MethodInfo> methods, int limit,
            int reserve, Set<String> gaps) {
        Set<String> families = new LinkedHashSet<>();
        for (String root : roots) {
            String owner = root.substring(1, root.indexOf(':'));
            int nesting = owner.lastIndexOf('$');
            families.add(nesting >= 0 ? owner.substring(0, nesting) : owner);
        }
        int added = 0;
        for (String family : families) {
            for (String method : sorted(methods.keySet())) {
                if (added >= reserve || selected.size() >= limit) return;
                String owner = method.substring(1, method.indexOf(':'));
                if (!(owner.equals(family) || owner.startsWith(family + "$"))
                        || methods.get(method).ioCalls.isEmpty()
                        || selected.containsKey(method)) continue;
                add(selected, method, "target_actor_io_family", limit, gaps);
                if (selected.containsKey(method)) added++;
            }
        }
    }

    private static JsonArray exceptionCandidates(String callee,
            Map<String, MethodInfo> methods, Map<String, Set<String>> callTargets) {
        JsonArray result = new JsonArray();
        String owner = callee.substring(0, callee.indexOf(':'));
        String packageName = owner.substring(0, owner.lastIndexOf('.') + 1);
        Deque<String> pending = new ArrayDeque<>();
        Deque<Integer> depths = new ArrayDeque<>();
        Set<String> seen = new HashSet<>();
        Set<String> candidates = new LinkedHashSet<>();
        pending.add(callee);
        depths.add(0);
        while (!pending.isEmpty() && seen.size() < 64) {
            String method = pending.removeFirst();
            int depth = depths.removeFirst();
            if (!seen.add(method) || !methods.containsKey(method)) continue;
            for (String type : methods.get(method).newTypes) {
                if (Scene.v().containsClass(type)
                        && subtype(Scene.v().getSootClass(type),
                                "java.io.IOException")
                        && !"java.io.IOException".equals(type)) candidates.add(type);
            }
            if (depth >= 8) continue;
            for (String next : sorted(callTargets.getOrDefault(method,
                    Collections.emptySet()))) {
                if (next.startsWith(packageName)) {
                    pending.addLast(next);
                    depths.addLast(depth + 1);
                }
            }
        }
        int count = 0;
        for (String type : sorted(candidates)) {
            if (count++ >= 4) break;
            result.add(type);
        }
        return result;
    }

    /** A GraphChecker-style field jump is by field signature, not object identity. */
    private static boolean subtype(SootClass child, String parent) {
        Deque<SootClass> pending = new ArrayDeque<>();
        Set<String> seen = new HashSet<>();
        pending.add(child);
        while (!pending.isEmpty()) {
            SootClass current = pending.removeFirst();
            if (!seen.add(current.getName())) continue;
            if (current.getName().equals(parent)) return true;
            if (current.hasSuperclass()) pending.add(current.getSuperclass());
            pending.addAll(current.getInterfaces());
        }
        return false;
    }

    private static Map<String, Set<String>> wireProducers(JsonObject analysis,
            Map<String, MethodInfo> methods, Set<String> gaps) {
        Map<String, Set<String>> result = new HashMap<>();
        for (String path : strings(analysis, "rpc_mapping_files")) {
            try {
                int lineNumber = 0;
                for (String line : Files.readAllLines(Paths.get(path), StandardCharsets.UTF_8)) {
                    lineNumber++;
                    if (line.trim().isEmpty()) continue;
                    JsonObject row = JsonParser.parseString(line).getAsJsonObject();
                    if (!row.has("schemaVersion") || row.get("schemaVersion").getAsInt() != 2
                            || !"WIRE_FLOW".equals(required(row, "kind"))) {
                        throw new IllegalArgumentException(path + ":" + lineNumber
                                + ": expected GraphChecker schema v2 WIRE_FLOW");
                    }
                    String producer = required(row.getAsJsonObject("producer"), "method");
                    String consumer = required(row.getAsJsonObject("consumer"), "method");
                    if (methods.containsKey(producer) && methods.containsKey(consumer)) {
                        result.computeIfAbsent(consumer, ignored -> new LinkedHashSet<>())
                                .add(producer);
                    }
                }
            } catch (java.io.IOException error) {
                throw new IllegalArgumentException("cannot read RPC mapping: " + path, error);
            }
        }
        return result;
    }

    /** GraphChecker protobuf rule: a demanded RPC-carried getF() may read any setF(T). */
    private static void deriveProtobufPorts(Map<String, MethodInfo> methods,
            Map<String, Set<String>> wireProducers, Set<String> gaps) {
        Map<String, SootClass> classes = new HashMap<>();
        for (SootClass owner : Scene.v().getClasses()) classes.put(owner.getName(), owner);
        Set<String> rpcMessages = new HashSet<>();
        Deque<String> pending = new ArrayDeque<>();
        for (SootClass owner : classes.values()) {
            if (owner.resolvingLevel() < SootClass.SIGNATURES) continue;
            for (SootMethod method : owner.getMethods()) {
                if (method.getParameterCount() > 1 && method.getParameterType(0).toString()
                        .endsWith(".protobuf.RpcController")) {
                    pending.add(method.getParameterType(1).toString());
                    pending.add(method.getReturnType().toString());
                }
            }
        }
        while (!pending.isEmpty()) {
            String name = pending.removeFirst();
            SootClass message = classes.get(name);
            if (message == null || !protobufMessage(message) || !rpcMessages.add(name)) continue;
            for (SootMethod method : message.getMethods()) {
                if (!method.isStatic()) pending.add(method.getReturnType().toString());
            }
        }
        Map<String, Set<String>> setters = new HashMap<>();
        for (MethodInfo info : methods.values()) {
            for (Invocation invocation : info.invocations) {
                setters.computeIfAbsent(invocation.signature, ignored -> new LinkedHashSet<>())
                        .add(info.signature);
            }
        }
        for (MethodInfo info : methods.values()) {
            for (Invocation invocation : info.invocations) {
                if (!rpcMessages.contains(invocation.owner)
                        || !invocation.name.startsWith("get")
                        || invocation.name.length() <= 3
                        || !invocation.parameterTypes.isEmpty()
                        || !wireLeaf(invocation.returnType)) continue;
                String builder = invocation.owner + "$Builder";
                String setter = "<" + builder + ": " + builder + " set"
                        + invocation.name.substring(3) + "(" + invocation.returnType + ")>";
                for (String producer : setters.getOrDefault(setter, Collections.emptySet())) {
                    wireProducers.computeIfAbsent(info.signature, ignored -> new LinkedHashSet<>())
                            .add(producer);
                }
            }
        }
    }

    private static boolean protobufMessage(SootClass owner) {
        Deque<SootClass> pending = new ArrayDeque<>();
        Set<String> seen = new HashSet<>();
        pending.add(owner);
        while (!pending.isEmpty()) {
            SootClass current = pending.removeFirst();
            if (!seen.add(current.getName())) continue;
            if (current.getName().endsWith(".protobuf.GeneratedMessage")
                    || current.getName().endsWith(".protobuf.GeneratedMessageV3")) return true;
            if (current.hasSuperclass()) pending.add(current.getSuperclass());
        }
        return false;
    }

    private static boolean wireLeaf(String type) {
        return Arrays.asList("boolean", "byte", "char", "short", "int", "long",
                "float", "double", "java.lang.String").contains(type);
    }

    private static String descriptor(SootMethod method) {
        StringBuilder result = new StringBuilder("(");
        for (Type type : method.getParameterTypes()) result.append(descriptor(type.toString()));
        return result.append(')').append(descriptor(method.getReturnType().toString()))
                .toString();
    }

    private static String descriptor(String type) {
        int dimensions = 0;
        while (type.endsWith("[]")) {
            dimensions++;
            type = type.substring(0, type.length() - 2);
        }
        String base;
        switch (type) {
            case "void": base = "V"; break;
            case "boolean": base = "Z"; break;
            case "byte": base = "B"; break;
            case "char": base = "C"; break;
            case "short": base = "S"; break;
            case "int": base = "I"; break;
            case "long": base = "J"; break;
            case "float": base = "F"; break;
            case "double": base = "D"; break;
            default: base = "L" + type.replace('.', '/') + ";";
        }
        StringBuilder result = new StringBuilder();
        for (int i = 0; i < dimensions; i++) result.append('[');
        return result.append(base).toString();
    }

    private static final Set<String> CONTAINER_MUTATORS = new HashSet<>(Arrays.asList(
            "put", "putIfAbsent", "putAll", "remove", "clear", "replace",
            "replaceAll", "compute", "computeIfAbsent", "computeIfPresent",
            "merge", "add", "addAll", "set", "retainAll", "removeAll"));

    private static Set<String> originFields(Value value, Unit at, SimpleLocalDefs defs,
                                            Set<String> seen) {
        Set<String> result = new LinkedHashSet<>();
        if (value instanceof FieldRef) {
            result.add(((FieldRef) value).getFieldRef().getSignature());
        } else if (value instanceof CastExpr) {
            result.addAll(originFields(((CastExpr) value).getOp(), at, defs, seen));
        } else if (value instanceof Local) {
            String key = value + "@" + System.identityHashCode(at);
            if (!seen.add(key)) return result;
            for (Unit definition : defs.getDefsOfAt((Local) value, at)) {
                if (definition instanceof AssignStmt) {
                    result.addAll(originFields(((AssignStmt) definition).getRightOp(),
                            definition, defs, seen));
                }
            }
        }
        return result;
    }

    /** Map task entry methods to may-launchers at Thread.start/Executor.submit/execute. */
    private static Map<String, Set<String>> taskLaunchers(Map<String, MethodInfo> methods,
            Set<String> gaps) {
        Map<String, Set<String>> result = new HashMap<>();
        List<MethodInfo> launchers = new ArrayList<>();
        for (MethodInfo info : methods.values()) {
            if (info.launchesTask) launchers.add(info);
        }
        for (MethodInfo task : methods.values()) {
            String name = task.method.getName();
            SootClass owner = task.method.getDeclaringClass();
            boolean entry = ("run".equals(name) && task.method.getParameterCount() == 0
                    && subtype(owner, "java.lang.Runnable"))
                    || ("call".equals(name) && task.method.getParameterCount() == 0
                    && subtype(owner, "java.util.concurrent.Callable"))
                    || (("compute".equals(name) || "exec".equals(name))
                    && task.method.getParameterCount() == 0
                    && subtype(owner, "java.util.concurrent.ForkJoinTask"));
            if (!entry) continue;
            for (MethodInfo launcher : launchers) {
                if (launcher.newTypes.contains(owner.getName())
                        || launcher.launchTypes.contains(owner.getName())
                        || anyLaunchSupertype(owner, launcher.launchTypes)) {
                    result.computeIfAbsent(task.signature, ignored -> new LinkedHashSet<>())
                            .add(launcher.signature);
                }
            }
        }
        return result;
    }

    private static boolean anyLaunchSupertype(SootClass task, Set<String> launchTypes) {
        for (String type : launchTypes) {
            if (subtype(task, type)) return true;
        }
        return false;
    }

    private static void add(Map<String, String> selected, String method, String reason,
                            int limit, Set<String> gaps) {
        if (selected.containsKey(method)) return;
        if (selected.size() >= limit) {
            gaps.add("method_budget_cut:" + limit);
            return;
        }
        selected.put(method, reason);
    }

    private static List<String> sorted(Set<String> input) {
        List<String> result = new ArrayList<>(input);
        Collections.sort(result);
        return result;
    }

    private static String required(JsonObject object, String key) {
        if (!object.has(key) || object.get(key).isJsonNull())
            throw new IllegalArgumentException(key + " is required");
        String value = object.get(key).getAsString();
        if (value.isEmpty()) throw new IllegalArgumentException(key + " is required");
        return value;
    }

    private static int number(JsonObject object, String key, int fallback) {
        return object.has(key) ? object.get(key).getAsInt() : fallback;
    }

    private static List<String> strings(JsonObject object, String key) {
        List<String> result = new ArrayList<>();
        if (!object.has(key)) return result;
        for (com.google.gson.JsonElement element : object.getAsJsonArray(key)) {
            String value = element.getAsString();
            if (value.isEmpty()) throw new IllegalArgumentException(key + " contains an empty string");
            result.add(value);
        }
        return result;
    }

    private static final class Step {
        final String method;
        final int callerDepth;
        final int calleeDepth;
        final int jumpDepth;
        final boolean callsPhase;
        Step(String method, int callerDepth, int calleeDepth, int jumpDepth,
             boolean callsPhase) {
            this.method = method;
            this.callerDepth = callerDepth;
            this.calleeDepth = calleeDepth;
            this.jumpDepth = jumpDepth;
            this.callsPhase = callsPhase;
        }
        String key() { return method + ":" + callerDepth + ":" + calleeDepth + ":"
                + jumpDepth + ":" + callsPhase; }
    }

    private static final class Invocation {
        final String signature;
        final String owner;
        final String name;
        final String subSignature;
        final String returnType;
        final String descriptor;
        final List<String> parameterTypes = new ArrayList<>();
        final boolean dynamic;

        Invocation(InvokeExpr call) {
            signature = call.getMethodRef().getSignature();
            owner = call.getMethodRef().declaringClass().getName();
            name = call.getMethodRef().name();
            subSignature = call.getMethodRef().getSubSignature().toString();
            returnType = call.getMethodRef().returnType().toString();
            for (Type type : call.getMethodRef().parameterTypes()) parameterTypes.add(type.toString());
            StringBuilder encoded = new StringBuilder("(");
            for (String type : parameterTypes) encoded.append(CoarseSelector.descriptor(type));
            descriptor = encoded.append(')').append(CoarseSelector.descriptor(returnType))
                    .toString();
            dynamic = call instanceof InstanceInvokeExpr && !(call instanceof SpecialInvokeExpr);
        }
    }

    private static final class IoCall {
        final String callee;
        final String owner;
        final String name;
        final String descriptor;
        final int line;
        final int unitIndex;
        final int lineOrdinal;
        IoCall(Invocation call, int line, int unitIndex, int lineOrdinal) {
            this.callee = call.signature;
            this.owner = call.owner;
            this.name = call.name;
            this.descriptor = call.descriptor;
            this.line = line;
            this.unitIndex = unitIndex;
            this.lineOrdinal = lineOrdinal;
        }
    }

    private static final class Branch {
        final Unit unit;
        final int line;
        final int unitIndex;
        final int lineOrdinal;
        Branch(Unit unit, int line, int unitIndex, int lineOrdinal) {
            this.unit = unit;
            this.line = line;
            this.unitIndex = unitIndex;
            this.lineOrdinal = lineOrdinal;
        }
    }

    private static final class ThrowSite {
        final Unit unit;
        final int line;
        final int unitIndex;
        final String thrownType;
        final List<String> controlledBy = new ArrayList<>();

        ThrowSite(Unit unit, int line, int unitIndex, String thrownType) {
            this.unit = unit;
            this.line = line;
            this.unitIndex = unitIndex;
            this.thrownType = thrownType;
        }
    }

    /** Normal-path reachability, stopping at a revisit of the deciding branch. */
    private static boolean reachesThrow(BriefUnitGraph graph, Unit start,
                                        Unit target, Unit decidingBranch) {
        Deque<Unit> pending = new ArrayDeque<>();
        Set<Unit> seen = new HashSet<>();
        pending.add(start);
        while (!pending.isEmpty()) {
            Unit unit = pending.removeFirst();
            if (unit.equals(target)) return true;
            if (unit.equals(decidingBranch) || !seen.add(unit)) continue;
            pending.addAll(graph.getSuccsOf(unit));
        }
        return false;
    }

    private static final class MethodInfo {
        final SootMethod method;
        final String signature;
        final List<Invocation> invocations = new ArrayList<>();
        final Set<String> reads = new LinkedHashSet<>();
        final Set<String> writes = new LinkedHashSet<>();
        final Set<String> newTypes = new LinkedHashSet<>();
        final Set<String> launchTypes = new LinkedHashSet<>();
        boolean launchesTask;
        final List<IoCall> ioCalls = new ArrayList<>();
        final List<Branch> branches = new ArrayList<>();
        final List<ThrowSite> throwSites = new ArrayList<>();

        MethodInfo(SootMethod method, Body body, List<String> ioPatterns) {
            this.method = method;
            signature = method.getSignature();
            SimpleLocalDefs defs = null;
            Map<String, Integer> ioOrdinals = new HashMap<>();
            Map<Integer, Integer> branchOrdinals = new HashMap<>();
            int unitIndex = 0;
            for (Unit unit : body.getUnits()) {
                unitIndex++;
                if (!(unit instanceof Stmt)) continue;
                Stmt stmt = (Stmt) unit;
                if (stmt instanceof IfStmt) {
                    int line = unit.getJavaSourceStartLineNumber();
                    int ordinal = branchOrdinals.getOrDefault(line, 0);
                    branchOrdinals.put(line, ordinal + 1);
                    branches.add(new Branch(unit, line, unitIndex - 1, ordinal));
                }
                if (stmt instanceof ThrowStmt) {
                    int line = unit.getJavaSourceStartLineNumber();
                    throwSites.add(new ThrowSite(unit, line, unitIndex - 1,
                            ((ThrowStmt) stmt).getOp().getType().toString()));
                }
                if (stmt instanceof AssignStmt && ((AssignStmt) stmt).getRightOp() instanceof NewExpr) {
                    newTypes.add(((NewExpr) ((AssignStmt) stmt).getRightOp())
                            .getBaseType().toString());
                }
                if (stmt.containsInvokeExpr()) {
                    InvokeExpr call = stmt.getInvokeExpr();
                    Invocation invocation = new Invocation(call);
                    invocations.add(invocation);
                    if (call instanceof InstanceInvokeExpr
                            && CONTAINER_MUTATORS.contains(invocation.name)) {
                        if (defs == null) defs = new SimpleLocalDefs(
                                new ExceptionalUnitGraph(body));
                        writes.addAll(originFields(((InstanceInvokeExpr) call).getBase(),
                                unit, defs, new HashSet<>()));
                    }
                    if (("start".equals(invocation.name) && "java.lang.Thread".equals(
                            invocation.owner)) || (Arrays.asList("execute", "submit", "fork")
                            .contains(invocation.name) && (invocation.owner.contains("Executor")
                            || invocation.owner.contains("ForkJoinTask")))) {
                        launchesTask = true;
                        if (call instanceof InstanceInvokeExpr) launchTypes.add(
                                ((InstanceInvokeExpr) call).getBase().getType().toString());
                        for (Value argument : call.getArgs()) {
                            launchTypes.add(argument.getType().toString());
                        }
                    }
                    if (isIoCall(invocation, ioPatterns)) {
                            int line = unit.getJavaSourceStartLineNumber();
                            String key = line + ":" + invocation.owner + ":"
                                    + invocation.name + invocation.descriptor;
                            int ordinal = ioOrdinals.getOrDefault(key, 0);
                            ioOrdinals.put(key, ordinal + 1);
                            ioCalls.add(new IoCall(invocation, line, unitIndex - 1, ordinal));
                    }
                }
                if (stmt instanceof AssignStmt && ((AssignStmt) stmt).getLeftOp() instanceof FieldRef) {
                    writes.add(((FieldRef) ((AssignStmt) stmt).getLeftOp()).getFieldRef().getSignature());
                }
                if (stmt instanceof AssignStmt && ((AssignStmt) stmt).getRightOp() instanceof FieldRef) {
                    reads.add(((FieldRef) ((AssignStmt) stmt).getRightOp()).getFieldRef().getSignature());
                }
                for (ValueBox box : stmt.getUseBoxes()) {
                    if (box.getValue() instanceof FieldRef) {
                        reads.add(((FieldRef) box.getValue()).getFieldRef().getSignature());
                    }
                }
            }
            if (!throwSites.isEmpty() && !branches.isEmpty()) {
                BriefUnitGraph graph = new BriefUnitGraph(body);
                for (ThrowSite site : throwSites) {
                    for (Branch branch : branches) {
                        List<Unit> successors = graph.getSuccsOf(branch.unit);
                        if (successors.size() != 2) continue;
                        boolean first = reachesThrow(graph, successors.get(0),
                                site.unit, branch.unit);
                        boolean second = reachesThrow(graph, successors.get(1),
                                site.unit, branch.unit);
                        if (first != second) controlledBy(site, branch);
                    }
                }
            }
        }

        private void controlledBy(ThrowSite site, Branch branch) {
            site.controlledBy.add(signature + "#u" + branch.unitIndex);
        }
    }
}
