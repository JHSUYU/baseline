package edu.uva.liftlab.graphchecker.causynth;

import org.objectweb.asm.ClassReader;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.LineNumberNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.TypeInsnNode;
import org.objectweb.asm.tree.VarInsnNode;
import org.objectweb.asm.tree.analysis.Analyzer;
import org.objectweb.asm.tree.analysis.AnalyzerException;
import org.objectweb.asm.tree.analysis.Frame;
import org.objectweb.asm.tree.analysis.SourceInterpreter;
import org.objectweb.asm.tree.analysis.SourceValue;
import soot.ArrayType;
import soot.BooleanType;
import soot.ByteType;
import soot.CharType;
import soot.DoubleType;
import soot.FloatType;
import soot.IntType;
import soot.LongType;
import soot.RefType;
import soot.Scene;
import soot.ShortType;
import soot.SootClass;
import soot.SootMethod;
import soot.VoidType;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import java.util.stream.Collectors;

/**
 * The exception target a case declares by source line:
 * {@code exception_target: <name> <binary class name> <line> [<thrown type>]}.
 *
 * <p>The site is the exception {@code NEW T} javac compiled at that line
 * whose object reaches an explicit {@code ATHROW}, directly or through local
 * stores and loads. A same-method throw of another object is insufficient.
 * of the class or of a class nested in it.  A lambda body is a method of its
 * enclosing class ({@code lambda$m$N}) and an anonymous class is {@code C$N};
 * both keep the source's LineNumberTable, and neither keeps a type annotation
 * on its {@code new} (javac 8 drops it in lambda bodies), so the line is the
 * one name every throw has.  A case therefore needs no annotation and no
 * rebuild of its tree.
 *
 * <p>The identity is the class-file one the analyzer matches on Jimple:
 * method, thrown type, and the {@code NEW}'s ordinal among the method's
 * {@code NEW}s of that type ({@link ExceptionTargetSite#stableIdentity}).
 * A line that holds no such throw, or several, is refused by name.
 */
final class ExceptionTargetLineResolver {
    private ExceptionTargetLineResolver() {
    }

    /** One declared target: its name, class, source line and thrown type. */
    static final class TargetLine {
        final String name;
        final String className;
        final int line;
        /** Trailing name segments of the thrown class; empty when unstated. */
        final String thrownType;

        TargetLine(String name, String className, int line,
                   String thrownType) {
            this.name = name;
            this.className = className;
            this.line = line;
            this.thrownType = thrownType;
        }

        /** {@code <name> <binary class name> <line> [<thrown type>]}. */
        static TargetLine parse(String value) throws IOException {
            String[] fields = value.trim().split("\\s+");
            if (fields.length < 3 || fields.length > 4
                    || !fields[2].matches("[1-9][0-9]*")) {
                throw new IOException("exception_target is <name> <binary "
                        + "class name> <source line> [<thrown type>], not: "
                        + value.trim());
            }
            return new TargetLine(fields[0], fields[1],
                    Integer.parseInt(fields[2]),
                    fields.length == 4 ? fields[3] : "");
        }

        /**
         * Whether the internal name {@code a/b/C$D} is the stated type: the
         * binary name, or its trailing segments ({@code D}, {@code C.D}).
         */
        boolean throwsType(String internalName) {
            if (thrownType.isEmpty()) {
                return true;
            }
            String[] actual = internalName.split("[/$]");
            String[] stated = thrownType.split("[.$]");
            if (stated.length > actual.length) {
                return false;
            }
            for (int i = 1; i <= stated.length; i++) {
                if (!stated[stated.length - i]
                        .equals(actual[actual.length - i])) {
                    return false;
                }
            }
            return true;
        }

        String render() {
            return className + ":" + line
                    + (thrownType.isEmpty() ? "" : " (" + thrownType + ")");
        }
    }

    /** The declared site, with its method's Soot signature. */
    static ExceptionTargetSite resolve(List<String> inputs, TargetLine target)
            throws IOException {
        ExceptionTargetSite site = locate(inputs, target);
        return new ExceptionTargetSite(site.id, site.className,
                site.methodName, site.methodDescriptor,
                methodSignature(site), site.exceptionClass,
                site.exceptionConstructionOrdinal);
    }

    /** The declared site in the class files, without Soot. */
    static ExceptionTargetSite locate(List<String> inputs, TargetLine target)
            throws IOException {
        List<ClassNode> family = classFamily(inputs, target.className);
        if (family.isEmpty()) {
            throw new IOException("TARGET_LINE_UNRESOLVED: "
                    + target.className + " is not among the analysis inputs "
                    + inputs + " (" + target.name + ")");
        }
        List<ExceptionTargetSite> found = new ArrayList<>();
        for (ClassNode owner : family) {
            for (MethodNode method : owner.methods) {
                collect(owner, method, target, found);
            }
        }
        if (found.isEmpty()) {
            throw new IOException("TARGET_LINE_UNRESOLVED: no matching throw at "
                    + target.render() + " in " + target.className
                    + " or its nested classes (" + target.name + ")");
        }
        if (found.size() > 1) {
            throw new IOException("TARGET_LINE_AMBIGUOUS: " + found.size()
                    + " matching throws at " + target.render() + " ("
                    + target.name + ")"
                    + (target.thrownType.isEmpty()
                    ? "; state the thrown type" : "") + ": "
                    + found.stream().map(ExceptionTargetSite::stableIdentity)
                    .sorted().collect(Collectors.toList()));
        }
        return found.get(0);
    }

    /** Every target-line {@code NEW T} whose exact object reaches ATHROW. */
    private static void collect(ClassNode owner, MethodNode method,
                                TargetLine target,
                                List<ExceptionTargetSite> found)
            throws IOException {
        Map<String, Integer> ordinals = new HashMap<>();
        Map<TypeInsnNode, Integer> candidates = new LinkedHashMap<>();
        int line = -1;
        for (AbstractInsnNode instruction = method.instructions.getFirst();
             instruction != null; instruction = instruction.getNext()) {
            if (instruction instanceof LineNumberNode) {
                line = ((LineNumberNode) instruction).line;
                continue;
            }
            if (instruction.getOpcode() != Opcodes.NEW) {
                continue;
            }
            TypeInsnNode creation = (TypeInsnNode) instruction;
            int ordinal = ordinals.merge(creation.desc, 1, Integer::sum) - 1;
            if (line == target.line && target.throwsType(creation.desc)) {
                candidates.put(creation, ordinal);
            }
        }
        if (candidates.isEmpty()) {
            return;
        }
        Frame<SourceValue>[] frames;
        try {
            frames = new Analyzer<>(new SourceInterpreter()).analyze(
                    owner.name, method);
        } catch (AnalyzerException exception) {
            throw new IOException("TARGET_LINE_UNRESOLVED: bytecode use-def "
                    + "analysis failed for " + owner.name + "#" + method.name,
                    exception);
        }
        Map<AbstractInsnNode, Integer> positions = new IdentityHashMap<>();
        for (int index = 0; index < method.instructions.size(); index++) {
            positions.put(method.instructions.get(index), index);
        }
        Set<TypeInsnNode> thrown = new LinkedHashSet<>();
        for (AbstractInsnNode instruction = method.instructions.getFirst();
             instruction != null; instruction = instruction.getNext()) {
            if (instruction.getOpcode() != Opcodes.ATHROW) {
                continue;
            }
            Frame<SourceValue> before = frames[positions.get(instruction)];
            if (before == null || before.getStackSize() == 0) {
                continue;
            }
            Set<TypeInsnNode> origins = origins(before.getStack(
                    before.getStackSize() - 1), frames, positions,
                    new LinkedHashSet<AbstractInsnNode>());
            // A merged throw that may receive another object is ambiguous.
            if (origins != null && origins.size() == 1) {
                thrown.add(origins.iterator().next());
            }
        }
        for (Map.Entry<TypeInsnNode, Integer> candidate : candidates.entrySet()) {
            TypeInsnNode creation = candidate.getKey();
            if (thrown.contains(creation)) {
                found.add(new ExceptionTargetSite(target.name,
                        owner.name.replace('/', '.'), method.name,
                        method.desc, "", creation.desc.replace('/', '.'),
                        candidate.getValue()));
            }
        }
    }

    /** Trace only alias-preserving bytecode operations; fail closed otherwise. */
    private static Set<TypeInsnNode> origins(SourceValue value,
            Frame<SourceValue>[] frames,
            Map<AbstractInsnNode, Integer> positions,
            Set<AbstractInsnNode> active) {
        if (value == null || value.insns.isEmpty()) {
            return null;
        }
        Set<TypeInsnNode> result = new LinkedHashSet<>();
        for (AbstractInsnNode producer : value.insns) {
            if (!active.add(producer)) {
                return null;
            }
            try {
                int opcode = producer.getOpcode();
                if (opcode == Opcodes.NEW) {
                    result.add((TypeInsnNode) producer);
                    continue;
                }
                Integer position = positions.get(producer);
                Frame<SourceValue> before = position == null ? null
                        : frames[position];
                if (before == null) {
                    return null;
                }
                SourceValue prior;
                if (opcode == Opcodes.ALOAD) {
                    prior = before.getLocal(((VarInsnNode) producer).var);
                } else if (opcode == Opcodes.ASTORE || opcode == Opcodes.DUP
                        || opcode == Opcodes.CHECKCAST) {
                    if (before.getStackSize() == 0) {
                        return null;
                    }
                    prior = before.getStack(before.getStackSize() - 1);
                } else {
                    return null;
                }
                Set<TypeInsnNode> preceding = origins(prior, frames,
                        positions, active);
                if (preceding == null) {
                    return null;
                }
                result.addAll(preceding);
            } finally {
                active.remove(producer);
            }
        }
        return result;
    }

    /** {@code C.class} and every {@code C$*.class} of the inputs. */
    private static List<ClassNode> classFamily(List<String> inputs,
                                               String className)
            throws IOException {
        String internal = className.replace('.', '/');
        String simple = internal.substring(internal.lastIndexOf('/') + 1);
        List<ClassNode> family = new ArrayList<>();
        for (String input : inputs == null
                ? Collections.<String>emptyList() : inputs) {
            if (input == null || input.trim().isEmpty()) {
                continue;
            }
            Path root = Paths.get(input.trim()).toAbsolutePath().normalize();
            if (Files.isDirectory(root)) {
                Path directory = root.resolve(internal).getParent();
                if (!Files.isDirectory(directory)) {
                    continue;
                }
                List<Path> files = new ArrayList<>();
                try (DirectoryStream<Path> members = Files.newDirectoryStream(
                        directory, simple + "{.class,$*.class}")) {
                    members.forEach(files::add);
                }
                Collections.sort(files);
                for (Path file : files) {
                    try (InputStream bytes = Files.newInputStream(file)) {
                        family.add(read(bytes));
                    }
                }
            } else if (Files.isRegularFile(root)) {
                try (JarFile jar = new JarFile(root.toFile())) {
                    List<JarEntry> entries = jar.stream()
                            .filter(entry -> entry.getName()
                                    .equals(internal + ".class")
                                    || entry.getName().startsWith(internal + "$")
                                    && entry.getName().endsWith(".class"))
                            .sorted((a, b) -> a.getName()
                                    .compareTo(b.getName()))
                            .collect(Collectors.toList());
                    for (JarEntry entry : entries) {
                        try (InputStream bytes = jar.getInputStream(entry)) {
                            family.add(read(bytes));
                        }
                    }
                }
            }
        }
        return family;
    }

    private static ClassNode read(InputStream bytes) throws IOException {
        ClassNode node = new ClassNode(Opcodes.ASM9);
        try {
            new ClassReader(bytes).accept(node, ClassReader.SKIP_FRAMES);
        } catch (RuntimeException exception) {
            throw new IOException("Could not read a target class file",
                    exception);
        }
        return node;
    }

    private static String methodSignature(ExceptionTargetSite site)
            throws IOException {
        SootClass owner = Scene.v().getSootClassUnsafe(site.className, false);
        if (owner == null || !owner.isApplicationClass()) {
            throw new IOException("The target class is not an application "
                    + "class: " + site.className);
        }
        List<SootMethod> matches = new ArrayList<>();
        for (SootMethod method : owner.getMethods()) {
            if (site.methodName.equals(method.getName())
                    && site.methodDescriptor.equals(descriptor(method))) {
                matches.add(method);
            }
        }
        if (matches.size() != 1) {
            throw new IOException("Could not resolve the target's bytecode "
                    + "method " + site.className + "#" + site.methodName
                    + site.methodDescriptor + " in Soot; matches="
                    + matches.size());
        }
        return matches.get(0).getSignature();
    }

    private static String descriptor(SootMethod method) throws IOException {
        StringBuilder descriptor = new StringBuilder("(");
        for (soot.Type parameter : method.getParameterTypes()) {
            descriptor.append(descriptor(parameter));
        }
        return descriptor.append(')')
                .append(descriptor(method.getReturnType())).toString();
    }

    private static String descriptor(soot.Type type) throws IOException {
        if (type instanceof VoidType) return "V";
        if (type instanceof BooleanType) return "Z";
        if (type instanceof ByteType) return "B";
        if (type instanceof CharType) return "C";
        if (type instanceof ShortType) return "S";
        if (type instanceof IntType) return "I";
        if (type instanceof LongType) return "J";
        if (type instanceof FloatType) return "F";
        if (type instanceof DoubleType) return "D";
        if (type instanceof RefType) {
            return "L" + ((RefType) type).getClassName()
                    .replace('.', '/') + ";";
        }
        if (type instanceof ArrayType) {
            ArrayType array = (ArrayType) type;
            return String.join("", Collections.nCopies(array.numDimensions,
                    "[")) + descriptor(array.baseType);
        }
        throw new IOException("Unsupported Soot type in the target method's "
                + "descriptor: " + type);
    }
}
