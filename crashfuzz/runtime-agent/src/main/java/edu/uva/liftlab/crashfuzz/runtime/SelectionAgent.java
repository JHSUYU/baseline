package edu.uva.liftlab.crashfuzz.runtime;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.Type;
import org.objectweb.asm.commons.AdviceAdapter;

import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.ProtectionDomain;
import java.security.MessageDigest;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Instruments only methods and callsites chosen by the preceding Soot pass. */
public final class SelectionAgent {
    private static final String PROBE = Type.getInternalName(SelectionProbe.class);
    private static final String NO_CALL = "(Ljava/lang/String;)V";

    private SelectionAgent() {}

    public static void premain(String ignored, Instrumentation instrumentation) throws Exception {
        String path = System.getenv("CRASHFUZZ_STATIC_SELECTION");
        if (path == null || path.isEmpty()) {
            throw new IllegalArgumentException("CRASHFUZZ_STATIC_SELECTION is required");
        }
        JsonObject selection = JsonParser.parseString(new String(Files.readAllBytes(
                Paths.get(path)), StandardCharsets.UTF_8)).getAsJsonObject();
        if (!"crashfuzz_coarse_soot_selection".equals(text(selection, "analysis_kind"))) {
            throw new IllegalArgumentException("invalid static selection: " + path);
        }
        Map<String, Map<String, MethodPlan>> classes = parse(selection);
        if (classes.isEmpty()) throw new IllegalArgumentException("empty static selection");
        String digest;
        if (selection.has("input_digest")) digest = text(selection, "input_digest");
        else {
            byte[] bytes = MessageDigest.getInstance("SHA-256").digest(
                    Files.readAllBytes(Paths.get(path)));
            StringBuilder hex = new StringBuilder();
            for (byte part : bytes) hex.append(String.format("%02x", part & 0xff));
            digest = hex.toString();
        }
        SelectionProbe.setTargetMethod(text(selection, "target_method"));
        SelectionProbe.selectionApplied(digest);
        instrumentation.addTransformer(new Transformer(classes), false);
    }

    private static String text(JsonObject object, String key) {
        return object.get(key).getAsString();
    }

    private static String methodKey(String name, String descriptor) {
        return name + descriptor;
    }

    private static String ioKey(int line, String owner, String name,
                                String descriptor, int ordinal) {
        return line + ":" + owner + ":" + name + descriptor + ":" + ordinal;
    }

    /** Calls where a completed remote operation can lose its reply at the caller. */
    static boolean supportsPostCallFault(String owner, String name,
                                         String descriptor) {
        if ("<init>".equals(name) || "<clinit>".equals(name)
                || "close".equals(name) || "getProxy".equals(name)
                || "waitForProxy".equals(name)
                || name.startsWith("getUnderlying")) return false;
        // A callback/future-returning API has only submitted a request when it
        // returns. Throwing there would not model loss of a completed reply.
        if (descriptor.contains("AsyncCallback")
                || descriptor.contains("RpcCallback")
                || descriptor.endsWith("Ljava/util/concurrent/Future;")
                || descriptor.endsWith("Ljava/util/concurrent/CompletableFuture;")) {
            return false;
        }
        if (owner.endsWith("ClientSideTranslatorPB")) return true;
        if (owner.endsWith("/SaslDataTransferClient")
                && "socketSend".equals(name)) return true;
        if (owner.contains("/ipc/") || owner.contains("/protobuf/")) {
            return "call".equals(name) || "callBlockingMethod".equals(name)
                    || "callMethod".equals(name)
                    || "readResponse".equals(name);
        }
        if (owner.endsWith("/ZooKeeper") || owner.endsWith("/SolrZkClient")) {
            return "create".equals(name) || "delete".equals(name)
                    || "exists".equals(name) || "getData".equals(name)
                    || "setData".equals(name) || "getChildren".equals(name)
                    || "multi".equals(name) || "sync".equals(name)
                    || "makePath".equals(name) || "atomicUpdate".equals(name);
        }
        if (owner.startsWith("org/apache/hadoop/hbase/client/")
                && (owner.endsWith("/Table") || owner.endsWith("/Admin"))) {
            return "get".equals(name) || "put".equals(name)
                    || "delete".equals(name) || "append".equals(name)
                    || "increment".equals(name) || "mutateRow".equals(name)
                    || "createTable".equals(name) || "disableTable".equals(name)
                    || "enableTable".equals(name) || "truncateTable".equals(name);
        }
        if (owner.endsWith("/SolrClient")) {
            return "request".equals(name) || "query".equals(name)
                    || "add".equals(name) || "deleteById".equals(name)
                    || "deleteByQuery".equals(name) || "commit".equals(name);
        }
        return false;
    }

    private static Map<String, Map<String, MethodPlan>> parse(JsonObject selection) {
        Map<String, Map<String, MethodPlan>> classes = new HashMap<>();
        // Existing campaign selections have no opt-in and keep their corpus.
        boolean postCallRpc = selection.has("post_call_rpc_enabled")
                && selection.get("post_call_rpc_enabled").getAsBoolean();
        JsonArray specs = selection.getAsJsonArray("method_specs");
        if (specs == null) throw new IllegalArgumentException("selection has no method_specs");
        Map<String, MethodPlan> bySignature = new HashMap<>();
        for (JsonElement element : specs) {
            JsonObject row = element.getAsJsonObject();
            MethodPlan method = new MethodPlan(text(row, "signature"));
            classes.computeIfAbsent(text(row, "owner"), ignored -> new LinkedHashMap<>())
                    .put(methodKey(text(row, "name"), text(row, "descriptor")), method);
            bySignature.put(method.signature, method);
        }
        if (selection.has("target_site_id") && selection.has("target_check_line")) {
            MethodPlan target = bySignature.get(text(selection, "target_method"));
            if (target == null) throw new IllegalArgumentException("target outside selection");
            target.checkSiteId = text(selection, "target_site_id");
            target.checkLine = selection.get("target_check_line").getAsInt();
        }
        for (JsonElement element : selection.getAsJsonArray("io_calls")) {
            JsonObject row = element.getAsJsonObject();
            MethodPlan method = bySignature.get(text(row, "method"));
            if (method == null) throw new IllegalArgumentException("I/O method outside selection");
            method.ioSites.put(ioKey(row.get("line").getAsInt(), text(row, "call_owner"),
                    text(row, "call_name"), text(row, "call_descriptor"),
                    row.get("line_ordinal").getAsInt()),
                    new IoSite(text(row, "site_id"), text(row, "callee"),
                            postCallRpc && supportsPostCallFault(
                                    text(row, "call_owner"), text(row, "call_name"),
                                    text(row, "call_descriptor"))));
        }
        for (JsonElement element : selection.getAsJsonArray("branches")) {
            JsonObject row = element.getAsJsonObject();
            MethodPlan method = bySignature.get(text(row, "method"));
            if (method != null) {
                method.branches.put(row.get("line").getAsInt() + ":"
                        + row.get("line_ordinal").getAsInt(), text(row, "site_id"));
            }
        }
        return classes;
    }

    private static final class MethodPlan {
        final String signature;
        final Map<String, IoSite> ioSites = new HashMap<>();
        final Map<String, String> branches = new HashMap<>();
        String checkSiteId;
        int checkLine = -1;
        MethodPlan(String signature) { this.signature = signature; }
    }

    private static final class IoSite {
        final String siteId;
        final String callee;
        final boolean postCallRpc;
        IoSite(String siteId, String callee, boolean postCallRpc) {
            this.siteId = siteId;
            this.callee = callee;
            this.postCallRpc = postCallRpc;
        }
    }

    private static final class Transformer implements ClassFileTransformer {
        private static final String SOLR_CONTROLLER = "org/apache/solr/cloud/ZkController";
        private static final String HDFS_DATA_XCEIVER =
                "org/apache/hadoop/hdfs/server/datanode/DataXceiver";
        private static final String HDFS_DATA_TRANSFER =
                "org/apache/hadoop/hdfs/server/datanode/DataNode$DataTransfer";
        final Map<String, Map<String, MethodPlan>> classes;
        Transformer(Map<String, Map<String, MethodPlan>> classes) { this.classes = classes; }

        @Override public byte[] transform(ClassLoader loader, String className,
                Class<?> redefining, ProtectionDomain domain, byte[] original) {
            Map<String, MethodPlan> selected = classes.get(className);
            boolean solrController = SOLR_CONTROLLER.equals(className);
            boolean hdfsActor = HDFS_DATA_XCEIVER.equals(className)
                    || HDFS_DATA_TRANSFER.equals(className);
            if (selected == null && !solrController && !hdfsActor) return null;
            final Map<String, MethodPlan> methods = selected == null
                    ? Collections.emptyMap() : selected;
            try {
                WeaveStats stats = new WeaveStats();
                int expectedIo = 0;
                int expectedBranches = 0;
                for (MethodPlan method : methods.values()) {
                    expectedIo += method.ioSites.size();
                    expectedBranches += method.branches.size();
                }
                ClassReader reader = new ClassReader(original);
                ClassWriter writer = new SafeClassWriter(reader,
                        ClassWriter.COMPUTE_FRAMES | ClassWriter.COMPUTE_MAXS, loader);
                reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
                    @Override public MethodVisitor visitMethod(int access, String name,
                            String descriptor, String signature, String[] exceptions) {
                        MethodVisitor originalVisitor = super.visitMethod(access, name,
                                descriptor, signature, exceptions);
                        MethodPlan plan = methods.get(methodKey(name, descriptor));
                        if (plan != null && originalVisitor != null) stats.methods++;
                        if (originalVisitor == null) return null;
                        boolean actorRun = hdfsActor && "run".equals(name)
                                && "()V".equals(descriptor);
                        MethodVisitor visitor = plan == null ? originalVisitor
                                : new SelectedMethod(originalVisitor, access, name,
                                        descriptor, plan, stats, actorRun);
                        if (actorRun && plan == null) {
                            visitor = new ActorRunBinding(visitor, access, name, descriptor);
                        }
                        return solrController && "<init>".equals(name)
                                ? new SolrControllerConstructor(visitor, access, name, descriptor)
                                : visitor;
                    }
                }, ClassReader.EXPAND_FRAMES);
                byte[] rewritten = writer.toByteArray();
                if (!methods.isEmpty()) {
                    SelectionProbe.weaveClass(className, methods.size(), stats.methods,
                            expectedIo, stats.io, expectedBranches, stats.branches);
                }
                return rewritten;
            } catch (Throwable error) {
                System.err.println("CrashFuzz selection weave failed for " + className
                        + ": " + error);
                error.printStackTrace(System.err);
                throw new IllegalStateException("static selection weave failed", error);
            }
        }
    }

    /** Constructor return runs after the ZkStateReader field has been initialized. */
    private static final class SolrControllerConstructor extends AdviceAdapter {
        SolrControllerConstructor(MethodVisitor delegate, int access, String name,
                                  String descriptor) {
            super(Opcodes.ASM9, delegate, access, name, descriptor);
        }

        @Override protected void onMethodExit(int opcode) {
            if (opcode == RETURN) {
                mv.visitVarInsn(ALOAD, 0);
                mv.visitMethodInsn(INVOKESTATIC, PROBE, "registerSolrController",
                        "(Ljava/lang/Object;)V", false);
            }
        }
    }

    /** Identity hook only: no I/O or coverage site is added by this visitor. */
    private static final class ActorRunBinding extends AdviceAdapter {
        private final Label start = new Label();
        private final Label end = new Label();
        private final Label handler = new Label();

        ActorRunBinding(MethodVisitor delegate, int access, String name,
                        String descriptor) {
            super(Opcodes.ASM9, delegate, access, name, descriptor);
        }

        @Override protected void onMethodEnter() {
            mv.visitVarInsn(ALOAD, 0);
            mv.visitMethodInsn(INVOKESTATIC, PROBE, "bindActor",
                    "(Ljava/lang/Object;)V", false);
            mv.visitLabel(start);
        }

        @Override protected void onMethodExit(int opcode) {
            if (opcode != ATHROW) {
                mv.visitMethodInsn(INVOKESTATIC, PROBE, "unbindActor", "()V", false);
            }
        }

        @Override public void visitMaxs(int maxStack, int maxLocals) {
            mv.visitLabel(end);
            mv.visitTryCatchBlock(start, end, handler, "java/lang/Throwable");
            mv.visitLabel(handler);
            mv.visitMethodInsn(INVOKESTATIC, PROBE, "unbindActor", "()V", false);
            mv.visitInsn(ATHROW);
            super.visitMaxs(maxStack, maxLocals);
        }
    }

    private static final class WeaveStats {
        int methods;
        int io;
        int branches;
    }

    /** Resolve frame merges from class resources without defining classes mid-transform. */
    private static final class SafeClassWriter extends ClassWriter {
        final ClassLoader loader;
        final Map<String, List<String>> parents = new HashMap<>();

        SafeClassWriter(ClassReader reader, int flags, ClassLoader loader) {
            super(reader, flags);
            this.loader = loader;
        }

        private List<String> parents(String type) {
            if (parents.containsKey(type)) return parents.get(type);
            List<String> result = new ArrayList<>();
            parents.put(type, result);
            if ("java/lang/Object".equals(type) || type.startsWith("[")) return result;
            String resource = type + ".class";
            try (InputStream input = loader == null
                    ? ClassLoader.getSystemResourceAsStream(resource)
                    : loader.getResourceAsStream(resource)) {
                if (input == null) {
                    result.add("java/lang/Object");
                    return result;
                }
                new ClassReader(input).accept(new ClassVisitor(Opcodes.ASM9) {
                    @Override public void visit(int version, int access, String name,
                            String signature, String parent, String[] interfaces) {
                        if (parent != null) result.add(parent);
                        if (interfaces != null) {
                            for (String item : interfaces) result.add(item);
                        }
                    }
                }, ClassReader.SKIP_CODE | ClassReader.SKIP_DEBUG | ClassReader.SKIP_FRAMES);
            } catch (IOException error) {
                result.add("java/lang/Object");
            }
            return result;
        }

        private boolean assignable(String parent, String child) {
            if (parent.equals(child) || "java/lang/Object".equals(parent)) return true;
            Deque<String> pending = new ArrayDeque<>();
            Set<String> visited = new HashSet<>();
            pending.add(child);
            while (!pending.isEmpty()) {
                String current = pending.removeFirst();
                if (!visited.add(current)) continue;
                for (String ancestor : parents(current)) {
                    if (parent.equals(ancestor)) return true;
                    pending.addLast(ancestor);
                }
            }
            return false;
        }

        @Override protected String getCommonSuperClass(String left, String right) {
            if (assignable(left, right)) return left;
            if (assignable(right, left)) return right;
            String current = left;
            Set<String> visited = new HashSet<>();
            while (visited.add(current)) {
                List<String> ancestors = parents(current);
                String superclass = ancestors.isEmpty() ? null : ancestors.get(0);
                if (superclass == null) break;
                if (assignable(superclass, right)) return superclass;
                current = superclass;
            }
            return "java/lang/Object";
        }
    }

    private static final class SelectedMethod extends AdviceAdapter {
        final MethodPlan plan;
        final WeaveStats stats;
        final boolean instanceMethod;
        final boolean actorRun;
        final int solrRequestLocal;
        final Map<String, Integer> ioOrdinals = new HashMap<>();
        final Map<Integer, Integer> branchOrdinals = new HashMap<>();
        final Map<Integer, Integer> throwOrdinals = new HashMap<>();
        final Set<Label> catchAllHandlers = new HashSet<>();
        final Label tryStart = new Label();
        final Label tryEnd = new Label();
        final Label tryHandler = new Label();
        int line = -1;
        boolean thisAvailable;
        int catchAllExceptionSlot = -1;
        boolean awaitingCatchAllStore;
        boolean lastLoadedCatchAllException;

        SelectedMethod(MethodVisitor delegate, int access, String name,
                       String descriptor, MethodPlan plan, WeaveStats stats,
                       boolean actorRun) {
            super(Opcodes.ASM9, delegate, access, name, descriptor);
            this.plan = plan;
            this.stats = stats;
            this.actorRun = actorRun;
            this.instanceMethod = (access & ACC_STATIC) == 0;
            int local = instanceMethod ? 1 : 0;
            int request = -1;
            for (Type argument : Type.getArgumentTypes(descriptor)) {
                if (argument.getSort() == Type.OBJECT &&
                        "org.apache.solr.request.SolrQueryRequest".equals(
                                argument.getClassName())) {
                    request = local;
                    break;
                }
                local += argument.getSize();
            }
            this.solrRequestLocal = request;
        }

        @Override protected void onMethodEnter() {
            thisAvailable = instanceMethod;
            if (actorRun) {
                mv.visitVarInsn(ALOAD, 0);
                mv.visitMethodInsn(INVOKESTATIC, PROBE, "bindActor",
                        "(Ljava/lang/Object;)V", false);
            }
            mv.visitLdcInsn(plan.signature);
            mv.visitMethodInsn(INVOKESTATIC, PROBE, "enter", NO_CALL, false);
            mv.visitLabel(tryStart);
        }

        @Override protected void onMethodExit(int opcode) {
            if (opcode != ATHROW) {
                mv.visitLdcInsn(plan.signature);
                mv.visitMethodInsn(INVOKESTATIC, PROBE, "exitNormal", NO_CALL, false);
                if (actorRun) {
                    mv.visitMethodInsn(INVOKESTATIC, PROBE, "unbindActor", "()V", false);
                }
            }
        }

        @Override public void visitMaxs(int maxStack, int maxLocals) {
            mv.visitLabel(tryEnd);
            mv.visitTryCatchBlock(tryStart, tryEnd, tryHandler,
                    "java/lang/Throwable");
            mv.visitLabel(tryHandler);
            mv.visitInsn(DUP);
            mv.visitLdcInsn(plan.signature);
            mv.visitInsn(SWAP);
            mv.visitMethodInsn(INVOKESTATIC, PROBE, "exitThrow",
                    "(Ljava/lang/String;Ljava/lang/Throwable;)V", false);
            if (actorRun) {
                mv.visitMethodInsn(INVOKESTATIC, PROBE, "unbindActor", "()V", false);
            }
            mv.visitInsn(ATHROW);
            super.visitMaxs(maxStack, maxLocals);
        }

        @Override public void visitLineNumber(int line, Label start) {
            this.line = line;
            super.visitLineNumber(line, start);
            if (line == plan.checkLine) {
                mv.visitLdcInsn(plan.checkSiteId);
                if (solrRequestLocal >= 0) mv.visitVarInsn(ALOAD, solrRequestLocal);
                else if (thisAvailable) mv.visitVarInsn(ALOAD, 0);
                else mv.visitInsn(ACONST_NULL);
                mv.visitMethodInsn(INVOKESTATIC, PROBE, "check",
                        "(Ljava/lang/String;Ljava/lang/Object;)V", false);
            }
        }

        @Override public void visitTryCatchBlock(Label start, Label end,
                                                  Label handler, String type) {
            if (type == null) catchAllHandlers.add(handler);
            super.visitTryCatchBlock(start, end, handler, type);
        }

        @Override public void visitLabel(Label label) {
            if (catchAllHandlers.contains(label)) {
                awaitingCatchAllStore = true;
                catchAllExceptionSlot = -1;
                lastLoadedCatchAllException = false;
            }
            super.visitLabel(label);
        }

        @Override public void visitVarInsn(int opcode, int var) {
            if (awaitingCatchAllStore) {
                catchAllExceptionSlot = opcode == ASTORE ? var : -1;
                awaitingCatchAllStore = false;
            }
            lastLoadedCatchAllException = opcode == ALOAD
                    && var == catchAllExceptionSlot && catchAllExceptionSlot >= 0;
            super.visitVarInsn(opcode, var);
        }

        @Override public void visitMethodInsn(int opcode, String owner, String name,
                String descriptor, boolean isInterface) {
            lastLoadedCatchAllException = false;
            String ordinalKey = line + ":" + owner + ":" + name + descriptor;
            int ordinal = ioOrdinals.getOrDefault(ordinalKey, 0);
            ioOrdinals.put(ordinalKey, ordinal + 1);
            IoSite site = plan.ioSites.get(ioKey(line, owner, name, descriptor, ordinal));
            if (site != null) {
                stats.io++;
                mv.visitLdcInsn(site.siteId);
                mv.visitLdcInsn(site.callee);
                if (thisAvailable) mv.visitVarInsn(ALOAD, 0);
                else mv.visitInsn(ACONST_NULL);
                mv.visitMethodInsn(INVOKESTATIC, PROBE, "io",
                        "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Object;)V", false);
            }
            super.visitMethodInsn(opcode, owner, name, descriptor, isInterface);
            // The original return value (including category-2 primitives) stays
            // below the probe arguments on the operand stack. If the invocation
            // throws, execution never reaches this hook.
            if (site != null && site.postCallRpc) {
                Type returnType = Type.getReturnType(descriptor);
                boolean objectResult = returnType.getSort() == Type.OBJECT
                        || returnType.getSort() == Type.ARRAY;
                int resultLocal = -1;
                if (objectResult) {
                    resultLocal = newLocal(returnType);
                    mv.visitVarInsn(ASTORE, resultLocal);
                }
                mv.visitLdcInsn(site.siteId);
                mv.visitLdcInsn(site.callee);
                if (thisAvailable) mv.visitVarInsn(ALOAD, 0);
                else mv.visitInsn(ACONST_NULL);
                if (objectResult) mv.visitVarInsn(ALOAD, resultLocal);
                mv.visitMethodInsn(INVOKESTATIC, PROBE, "ioAfter",
                        objectResult
                            ? "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Object;Ljava/lang/Object;)V"
                            : "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Object;)V",
                        false);
                if (objectResult) mv.visitVarInsn(ALOAD, resultLocal);
            }
        }

        @Override public void visitJumpInsn(int opcode, Label target) {
            lastLoadedCatchAllException = false;
            if (opcode == GOTO) catchAllExceptionSlot = -1;
            if (opcode >= IFEQ && opcode <= IF_ACMPNE || opcode == IFNULL
                    || opcode == IFNONNULL) {
                int ordinal = branchOrdinals.getOrDefault(line, 0);
                branchOrdinals.put(line, ordinal + 1);
                String branchKey = line + ":" + ordinal;
                if (plan.branches.containsKey(branchKey)) stats.branches++;
                String site = plan.branches.getOrDefault(branchKey,
                        plan.signature + "#bytecode:" + line + ":" + ordinal);
                if (opcode >= IFEQ && opcode <= IFLE) {
                    mv.visitInsn(DUP);
                    mv.visitLdcInsn(site);
                    mv.visitLdcInsn(opcode);
                    mv.visitMethodInsn(INVOKESTATIC, PROBE, "branchInt1",
                            "(ILjava/lang/String;I)V", false);
                } else if (opcode >= IF_ICMPEQ && opcode <= IF_ICMPLE) {
                    mv.visitInsn(DUP2);
                    mv.visitLdcInsn(site);
                    mv.visitLdcInsn(opcode);
                    mv.visitMethodInsn(INVOKESTATIC, PROBE, "branchInt2",
                            "(IILjava/lang/String;I)V", false);
                } else if (opcode == IF_ACMPEQ || opcode == IF_ACMPNE) {
                    mv.visitInsn(DUP2);
                    mv.visitLdcInsn(site);
                    mv.visitLdcInsn(opcode);
                    mv.visitMethodInsn(INVOKESTATIC, PROBE, "branchRef2",
                            "(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/String;I)V", false);
                } else {
                    mv.visitInsn(DUP);
                    mv.visitLdcInsn(site);
                    mv.visitLdcInsn(opcode);
                    mv.visitMethodInsn(INVOKESTATIC, PROBE, "branchRef1",
                            "(Ljava/lang/Object;Ljava/lang/String;I)V", false);
                }
            }
            super.visitJumpInsn(opcode, target);
        }

        @Override public void visitInsn(int opcode) {
            boolean compilerRethrow = opcode == ATHROW && lastLoadedCatchAllException;
            lastLoadedCatchAllException = false;
            if (opcode >= IRETURN && opcode <= RETURN) catchAllExceptionSlot = -1;
            if (opcode == ATHROW) {
                // javac's synchronized/finally cleanup stores the caught
                // Throwable, runs cleanup, then reloads and rethrows it. It
                // is the same throw already observed at its source site.
                if (compilerRethrow) {
                    catchAllExceptionSlot = -1;
                    super.visitInsn(opcode);
                    return;
                }
                int ordinal = throwOrdinals.getOrDefault(line, 0);
                throwOrdinals.put(line, ordinal + 1);
                String site = plan.signature + "#bytecode:throw:" + line + ":" + ordinal;
                // Keep the Throwable on the operand stack for the original ATHROW.
                mv.visitInsn(DUP);
                mv.visitLdcInsn(plan.signature);
                mv.visitLdcInsn(site);
                mv.visitLdcInsn(line);
                mv.visitLdcInsn(ordinal);
                mv.visitMethodInsn(INVOKESTATIC, PROBE, "explicitThrow",
                        "(Ljava/lang/Throwable;Ljava/lang/String;Ljava/lang/String;II)V", false);
            }
            super.visitInsn(opcode);
        }

        @Override public void visitIntInsn(int opcode, int operand) {
            lastLoadedCatchAllException = false;
            super.visitIntInsn(opcode, operand);
        }

        @Override public void visitTypeInsn(int opcode, String type) {
            lastLoadedCatchAllException = false;
            super.visitTypeInsn(opcode, type);
        }

        @Override public void visitFieldInsn(int opcode, String owner, String name,
                                             String descriptor) {
            lastLoadedCatchAllException = false;
            super.visitFieldInsn(opcode, owner, name, descriptor);
        }

        @Override public void visitInvokeDynamicInsn(String name, String descriptor,
                org.objectweb.asm.Handle bootstrapMethod, Object... bootstrapArguments) {
            lastLoadedCatchAllException = false;
            super.visitInvokeDynamicInsn(name, descriptor, bootstrapMethod, bootstrapArguments);
        }

        @Override public void visitLdcInsn(Object value) {
            lastLoadedCatchAllException = false;
            super.visitLdcInsn(value);
        }

        @Override public void visitIincInsn(int var, int increment) {
            lastLoadedCatchAllException = false;
            super.visitIincInsn(var, increment);
        }

        @Override public void visitTableSwitchInsn(int min, int max, Label dflt,
                                                    Label... labels) {
            lastLoadedCatchAllException = false;
            super.visitTableSwitchInsn(min, max, dflt, labels);
        }

        @Override public void visitLookupSwitchInsn(Label dflt, int[] keys,
                                                     Label[] labels) {
            lastLoadedCatchAllException = false;
            super.visitLookupSwitchInsn(dflt, keys, labels);
        }

        @Override public void visitMultiANewArrayInsn(String descriptor, int dimensions) {
            lastLoadedCatchAllException = false;
            super.visitMultiANewArrayInsn(descriptor, dimensions);
        }
    }
}
