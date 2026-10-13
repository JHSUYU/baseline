package edu.uva.liftlab.mallory.nativefault;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.InsnList;
import org.objectweb.asm.tree.InsnNode;
import org.objectweb.asm.tree.LdcInsnNode;
import org.objectweb.asm.tree.LineNumberNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Test-only bytecode fixture writer. Production hooks use the exact-unit Soot pass. */
public final class NativeFaultWeaver {
    private static final String HOOK =
            "edu/uva/liftlab/graphchecker/runtime/NativeFaultHooks";
    private static final Pattern SOOT_METHOD = Pattern.compile(
            "^<([^:]+): (.+) ([^ (]+)\\((.*)\\)>$");

    private NativeFaultWeaver() { }

    public static void main(String[] args) throws Exception {
        if (args.length != 4) throw new IllegalArgumentException(
                "usage: NativeFaultWeaver <original-woven-classes>"
                + " <input-classes> <dependency-classpath-file> <static-weave-manifest>");
        weave(Paths.get(args[0]), Paths.get(args[1]),
                new String(Files.readAllBytes(Paths.get(args[2])),
                        StandardCharsets.UTF_8).trim(), Paths.get(args[3]));
    }

    public static void weave(Path classes, Path manifestFile) throws IOException {
        weave(classes, classes, "", manifestFile);
    }

    public static void weave(Path classes, Path inputClasses,
                             String dependencies, Path manifestFile) throws IOException {
        if (!Files.isDirectory(classes)) throw new IllegalArgumentException(
                "woven class tree is absent: " + classes);
        JsonObject manifest = new JsonParser().parse(new String(Files.readAllBytes(
                manifestFile), StandardCharsets.UTF_8)).getAsJsonObject();
        List<Site> sites = new ArrayList<>();
        readSites(manifest.getAsJsonArray("doors"), false, sites);
        readSites(manifest.getAsJsonArray("targets"), true, sites);
        if (sites.isEmpty()) throw new IllegalArgumentException(
                "static manifest selected no I/O doors or THROW targets");
        Map<String, List<Site>> byClass = new HashMap<>();
        for (Site site : sites) byClass.computeIfAbsent(site.clazz, ignored ->
                new ArrayList<>()).add(site);
        Map<Path, byte[]> changed = new HashMap<>();
        for (Map.Entry<String, List<Site>> entry : byClass.entrySet()) {
            String resource = entry.getKey().replace('.', '/') + ".class";
            Path file = classes.resolve(resource);
            byte[] original = loadClass(inputClasses.resolve(resource),
                    dependencies, resource);
            byte[] woven = Files.isRegularFile(file) ? Files.readAllBytes(file)
                    : original;
            ClassReader reader = new ClassReader(woven);
            ClassNode tree = new ClassNode();
            reader.accept(tree, 0);
            ClassNode before = new ClassNode();
            new ClassReader(original).accept(before, 0);
            Map<String, List<Integer>> offsets = BytecodeOffsets.instructions(original);
            if (tree.name.equals(HOOK)) throw new IllegalArgumentException(
                    "selected native adapter helper as workload class");
            for (MethodNode method : tree.methods) {
                List<Site> selected = new ArrayList<>();
                for (Site site : entry.getValue()) {
                    if (site.method.equals(method.name)
                            && site.descriptor.equals(method.desc)) selected.add(site);
                }
                if (!selected.isEmpty()) {
                    MethodNode prior = null;
                    for (MethodNode candidate : before.methods) {
                        if (candidate.name.equals(method.name)
                                && candidate.desc.equals(method.desc)) {
                            prior = candidate;
                            break;
                        }
                    }
                    if (prior == null) throw new IllegalArgumentException(
                            "original method absent for " + method.name + method.desc);
                    instrument(method, prior, offsets.get(method.name + '\n'
                            + method.desc), selected);
                }
            }
            for (Site site : entry.getValue()) if (!site.matched) {
                throw new IllegalArgumentException("selected site has no exact bytecode: "
                        + site.siteId);
            }
            ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
            tree.accept(writer);
            changed.put(file, writer.toByteArray());
        }
        // Verify every site before writing any class. A bad static/bytecode
        // mapping cannot leave a partially instrumented tree behind.
        Path helper = classes.resolve(HOOK + ".class");
        if (Files.exists(helper)) throw new IllegalArgumentException(
                "native fault hook already installed: " + helper);
        byte[] helperBytes;
        try (InputStream stream = NativeFaultWeaver.class.getClassLoader().getResourceAsStream(
                HOOK + ".class")) {
            if (stream == null) throw new IllegalStateException("runtime hook class unavailable");
            helperBytes = readAll(stream);
        }
        for (Map.Entry<Path, byte[]> entry : changed.entrySet()) {
            Files.createDirectories(entry.getKey().getParent());
            Files.write(entry.getKey(), entry.getValue());
        }
        Files.createDirectories(helper.getParent());
        Files.write(helper, helperBytes);
        // The hook's nested fault-plan class is also needed in fresh JUnit VMs.
        String nested = HOOK + "$Fault.class";
        Path nestedFile = classes.resolve(nested);
        try (InputStream stream = NativeFaultWeaver.class.getClassLoader().getResourceAsStream(
                nested)) {
            if (stream == null) throw new IllegalStateException("fault-plan class unavailable");
            Files.write(nestedFile, readAll(stream));
        }
    }

    private static byte[] loadClass(Path input, String dependencies,
                                    String resource) throws IOException {
        if (Files.isRegularFile(input)) return Files.readAllBytes(input);
        for (String part : dependencies.split(Pattern.quote(java.io.File.pathSeparator))) {
            if (part.isEmpty()) continue;
            Path entry = Paths.get(part);
            if (Files.isDirectory(entry)) {
                Path candidate = entry.resolve(resource);
                if (Files.isRegularFile(candidate)) return Files.readAllBytes(candidate);
            } else if (Files.isRegularFile(entry)
                    && (part.endsWith(".jar") || part.endsWith(".zip"))) {
                try (ZipFile archive = new ZipFile(entry.toFile())) {
                    ZipEntry candidate = archive.getEntry(resource);
                    if (candidate != null) try (InputStream stream = archive.getInputStream(candidate)) {
                        return readAll(stream);
                    }
                }
            }
        }
        throw new IllegalArgumentException(
                "selected class absent from pinned classpath: " + resource);
    }

    private static byte[] readAll(InputStream stream) throws IOException {
        java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
        byte[] block = new byte[8192];
        for (int n; (n = stream.read(block)) >= 0;) bytes.write(block, 0, n);
        return bytes.toByteArray();
    }

    private static void readSites(JsonArray values, boolean target,
                                  List<Site> result) {
        if (values == null) return;
        Set<String> ids = new HashSet<>();
        for (JsonElement value : values) {
            JsonObject row = value.getAsJsonObject();
            if (target && !"THROW".equals(required(row, "kind"))) continue;
            Site site = new Site(row, target);
            if (!ids.add(site.siteId)) throw new IllegalArgumentException(
                    "duplicate static selected site " + site.siteId);
            result.add(site);
        }
    }

    private static void instrument(MethodNode method, MethodNode original,
                                   List<Integer> offsets, List<Site> selected) {
        if (offsets == null) throw new IllegalArgumentException(
                "original Code attribute absent: " + original.name);
        Map<String, List<AbstractInsnNode>> originalGroups = candidates(original);
        Map<AbstractInsnNode, Integer> bci = new HashMap<>();
        int offsetIndex = 0;
        for (AbstractInsnNode insn = original.instructions.getFirst(); insn != null;
                insn = insn.getNext()) {
            if (insn.getOpcode() < 0) continue;
            if (offsetIndex >= offsets.size()) throw new IllegalArgumentException(
                    "original classfile/ASM instruction count differs");
            bci.put(insn, offsets.get(offsetIndex++));
        }
        if (offsetIndex != offsets.size()) throw new IllegalArgumentException(
                "original classfile/ASM instruction count differs");
        Map<String, List<AbstractInsnNode>> candidates = candidates(method);
        Map<String, List<Site>> groups = new HashMap<>();
        for (Site site : selected) groups.computeIfAbsent(site.key,
                ignored -> new ArrayList<>()).add(site);
        for (Map.Entry<String, List<Site>> entry : groups.entrySet()) {
            List<Site> sites = entry.getValue();
            List<AbstractInsnNode> originalFound = originalGroups.get(entry.getKey());
            List<AbstractInsnNode> found = candidates.get(entry.getKey());
            if (originalFound == null || found == null
                    || originalFound.size() != found.size()) {
                throw new IllegalArgumentException("original/woven call shape differs "
                        + entry.getKey());
            }
            sites.sort(Comparator.comparingInt(site -> site.unitIndex));
            Set<Integer> used = new HashSet<>();
            for (Site site : sites) {
                int rank = -1;
                if (site.bytecodeOffset >= 0) {
                    for (int i = 0; i < originalFound.size(); i++) {
                        if (bci.get(originalFound.get(i)) == site.bytecodeOffset) {
                            rank = i;
                            break;
                        }
                    }
                } else if (sites.size() == 1 && originalFound.size() == 1) {
                    // A selected Soot unit can map to bytecode by line and
                    // callee only when there is exactly one candidate.
                    rank = 0;
                }
                if (rank < 0 || !used.add(rank)) throw new IllegalArgumentException(
                        "static/bytecode offset is absent or ambiguous: " + site.siteId);
                inject(method, found.get(rank), site);
                site.matched = true;
            }
        }
    }

    private static Map<String, List<AbstractInsnNode>> candidates(MethodNode method) {
        int line = -1;
        Map<String, List<AbstractInsnNode>> candidates = new HashMap<>();
        for (AbstractInsnNode insn = method.instructions.getFirst(); insn != null;
                insn = insn.getNext()) {
            if (insn instanceof LineNumberNode) {
                line = ((LineNumberNode) insn).line;
            } else if (insn instanceof MethodInsnNode) {
                MethodInsnNode call = (MethodInsnNode) insn;
                String key = "D\n" + line + '\n' + call.owner + '\n'
                        + call.name + '\n' + call.desc;
                candidates.computeIfAbsent(key, ignored -> new ArrayList<>()).add(insn);
            } else if (insn.getOpcode() == Opcodes.ATHROW) {
                candidates.computeIfAbsent("T\n" + line,
                        ignored -> new ArrayList<>()).add(insn);
            }
        }
        return candidates;
    }

    private static void inject(MethodNode method, AbstractInsnNode at, Site site) {
        InsnList injected = new InsnList();
        if (site.target) {
            // Stack starts [throwable]. Preserve it for ATHROW while passing
            // the same object as the hook's third argument.
            injected.add(new InsnNode(Opcodes.DUP));
            injected.add(new LdcInsnNode(site.siteId));
            injected.add(new InsnNode(Opcodes.SWAP));
            injected.add(new LdcInsnNode(site.exceptionClass));
            injected.add(new InsnNode(Opcodes.SWAP));
            injected.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOK,
                    "targetThrow",
                    "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Throwable;)V",
                    false));
        } else {
            injected.add(new LdcInsnNode(site.siteId));
            injected.add(new LdcInsnNode(site.exceptionClass));
            injected.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOK,
                    "beforeDoor", "(Ljava/lang/String;Ljava/lang/String;)V", false));
        }
        method.instructions.insertBefore(at, injected);
    }

    private static String required(JsonObject row, String name) {
        if (!row.has(name) || !row.get(name).isJsonPrimitive()) {
            throw new IllegalArgumentException("missing static site " + name);
        }
        String value = row.get(name).getAsString();
        if (value.isEmpty()) throw new IllegalArgumentException(
                "empty static site " + name);
        return value;
    }

    private static String type(String name) {
        int dimensions = 0;
        while (name.endsWith("[]")) {
            dimensions++;
            name = name.substring(0, name.length() - 2);
        }
        String primitive;
        switch (name) {
            case "void": primitive = "V"; break;
            case "boolean": primitive = "Z"; break;
            case "byte": primitive = "B"; break;
            case "char": primitive = "C"; break;
            case "short": primitive = "S"; break;
            case "int": primitive = "I"; break;
            case "long": primitive = "J"; break;
            case "float": primitive = "F"; break;
            case "double": primitive = "D"; break;
            default: primitive = "L" + name.replace('.', '/') + ";";
        }
        StringBuilder descriptor = new StringBuilder();
        for (int i = 0; i < dimensions; i++) descriptor.append('[');
        return descriptor.append(primitive).toString();
    }

    private static String[] callee(String signature) {
        Matcher matcher = SOOT_METHOD.matcher(signature);
        if (!matcher.matches()) throw new IllegalArgumentException(
                "invalid selected Soot callee " + signature);
        StringBuilder descriptor = new StringBuilder("(");
        String args = matcher.group(4).trim();
        if (!args.isEmpty()) for (String arg : args.split(",")) {
            descriptor.append(type(arg.trim()));
        }
        descriptor.append(')').append(type(matcher.group(2).trim()));
        return new String[] {matcher.group(1).replace('.', '/'),
                matcher.group(3), descriptor.toString()};
    }

    private static final class Site {
        final String clazz;
        final String method;
        final String descriptor;
        final int line;
        final int unitIndex;
        final int bytecodeOffset;
        final String siteId;
        final String exceptionClass;
        final boolean target;
        final String key;
        boolean matched;

        Site(JsonObject row, boolean target) {
            clazz = required(row, "clazz");
            method = required(row, "method");
            descriptor = required(row, "descriptor");
            line = row.get("line").getAsInt();
            unitIndex = row.has("unitIndex") ? row.get("unitIndex").getAsInt() : -1;
            bytecodeOffset = row.has("bytecodeOffset")
                    ? row.get("bytecodeOffset").getAsInt() : -1;
            siteId = required(row, "siteId");
            exceptionClass = row.has("exceptionClass")
                    ? required(row, "exceptionClass") : "java.io.IOException";
            this.target = target;
            if (line <= 0) throw new IllegalArgumentException(
                    "selected site has no source line: " + siteId);
            if (target) {
                key = "T\n" + line;
            } else {
                String[] call = callee(required(row, "callee"));
                key = "D\n" + line + '\n' + call[0] + '\n' + call[1]
                        + '\n' + call[2];
            }
        }
    }
}
