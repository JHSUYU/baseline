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

    private static Map<String, Map<String, MethodPlan>> parse(JsonObject selection) {
        Map<String, Map<String, MethodPlan>> classes = new HashMap<>();
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
                    new IoSite(text(row, "site_id"), text(row, "callee")));
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
        IoSite(String siteId, String callee) {
            this.siteId = siteId;
            this.callee = callee;
        }
    }

    private static final class Transformer implements ClassFileTransformer {
        final Map<String, Map<String, MethodPlan>> classes;
        Transformer(Map<String, Map<String, MethodPlan>> classes) { this.classes = classes; }

        @Override public byte[] transform(ClassLoader loader, String className,
                Class<?> redefining, ProtectionDomain domain, byte[] original) {
            Map<String, MethodPlan> methods = classes.get(className);
            if (methods == null) return null;
            try {
                ClassReader reader = new ClassReader(original);
                ClassWriter writer = new SafeClassWriter(reader,
                        ClassWriter.COMPUTE_FRAMES | ClassWriter.COMPUTE_MAXS, loader);
                reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
                    @Override public MethodVisitor visitMethod(int access, String name,
                            String descriptor, String signature, String[] exceptions) {
                        MethodVisitor originalVisitor = super.visitMethod(access, name,
                                descriptor, signature, exceptions);
                        MethodPlan plan = methods.get(methodKey(name, descriptor));
                        return plan == null || originalVisitor == null ? originalVisitor
                                : new SelectedMethod(originalVisitor, access, name,
                                        descriptor, plan);
                    }
                }, ClassReader.EXPAND_FRAMES);
                return writer.toByteArray();
            } catch (Throwable error) {
                System.err.println("CrashFuzz selection weave failed for " + className
                        + ": " + error);
                error.printStackTrace(System.err);
                throw new IllegalStateException("static selection weave failed", error);
            }
        }
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
        final Map<String, Integer> ioOrdinals = new HashMap<>();
        final Map<Integer, Integer> branchOrdinals = new HashMap<>();
        final Label tryStart = new Label();
        final Label tryEnd = new Label();
        final Label tryHandler = new Label();
        int line = -1;

        SelectedMethod(MethodVisitor delegate, int access, String name,
                       String descriptor, MethodPlan plan) {
            super(Opcodes.ASM9, delegate, access, name, descriptor);
            this.plan = plan;
        }

        @Override protected void onMethodEnter() {
            mv.visitLdcInsn(plan.signature);
            mv.visitMethodInsn(INVOKESTATIC, PROBE, "enter", NO_CALL, false);
            mv.visitLabel(tryStart);
        }

        @Override protected void onMethodExit(int opcode) {
            if (opcode != ATHROW) {
                mv.visitLdcInsn(plan.signature);
                mv.visitMethodInsn(INVOKESTATIC, PROBE, "exitNormal", NO_CALL, false);
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
            mv.visitInsn(ATHROW);
            super.visitMaxs(maxStack, maxLocals);
        }

        @Override public void visitLineNumber(int line, Label start) {
            this.line = line;
            super.visitLineNumber(line, start);
            if (line == plan.checkLine) {
                mv.visitLdcInsn(plan.checkSiteId);
                mv.visitMethodInsn(INVOKESTATIC, PROBE, "check",
                        "(Ljava/lang/String;)V", false);
            }
        }

        @Override public void visitMethodInsn(int opcode, String owner, String name,
                String descriptor, boolean isInterface) {
            String ordinalKey = line + ":" + owner + ":" + name + descriptor;
            int ordinal = ioOrdinals.getOrDefault(ordinalKey, 0);
            ioOrdinals.put(ordinalKey, ordinal + 1);
            IoSite site = plan.ioSites.get(ioKey(line, owner, name, descriptor, ordinal));
            if (site != null) {
                mv.visitLdcInsn(site.siteId);
                mv.visitLdcInsn(site.callee);
                mv.visitMethodInsn(INVOKESTATIC, PROBE, "io",
                        "(Ljava/lang/String;Ljava/lang/String;)V", false);
            }
            super.visitMethodInsn(opcode, owner, name, descriptor, isInterface);
        }

        @Override public void visitJumpInsn(int opcode, Label target) {
            if (opcode >= IFEQ && opcode <= IF_ACMPNE || opcode == IFNULL
                    || opcode == IFNONNULL) {
                int ordinal = branchOrdinals.getOrDefault(line, 0);
                branchOrdinals.put(line, ordinal + 1);
                String site = plan.branches.getOrDefault(line + ":" + ordinal,
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
    }
}
