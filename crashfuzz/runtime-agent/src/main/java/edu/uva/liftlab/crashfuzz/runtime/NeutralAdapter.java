package edu.uva.liftlab.crashfuzz.runtime;

import com.google.gson.GsonBuilder;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.FieldVisitor;
import org.objectweb.asm.Handle;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.Type;

import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.regex.Pattern;
import java.util.stream.Stream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * A neutral stand-in for an adapter API a source tree calls but no entry of its classpath provides.
 *
 * <p>A tree may be built against a library it declares {@code provided} and run with that library
 * supplied by its own launcher; GraphChecker's bug trees call GraphChecker's runtime doors that way.
 * CrashFuzz runs such a tree's plain build without that library. This tool reads the tree's compiled
 * classes, finds every class of the adapter namespace they reference that the classpath lacks, and
 * writes a class for each holding exactly the referenced members, all neutral:</p>
 * <ul>
 *   <li>a method returns {@code false}, zero, {@code ""}, an empty array, the neutral instance of a
 *   stand-in type, or {@code null} for any other type;</li>
 *   <li>a {@code void} method handed {@code Runnable}s runs them, in order (a door that is given the
 *   system's own work, such as delivering a watch notification, does it); any other argument is
 *   ignored;</li>
 *   <li>a field holds {@code ""} when it is a {@code String}, else its default;</li>
 *   <li>a constructor does nothing beyond that.</li>
 * </ul>
 * <p>This is how such doors answer outside a recording: nothing is recorded, held or deferred, so
 * the system goes its own way. No code of the absent library is used.</p>
 *
 * <p>Usage: {@code NeutralAdapter <output dir> <manifest.json> <namespace regex> <hint,...> <entry>...}:
 * an entry prefixed with {@code +} is scanned for references (the tree's own code); every entry,
 * directory or jar, counts as providing the classes it holds. A class is scanned only when its bytes
 * hold one of the comma-separated hints.</p>
 */
public final class NeutralAdapter {
    static final String NEUTRAL = "CRASHFUZZ_NEUTRAL";

    private NeutralAdapter() {}

    /** A referenced member of one stand-in class. */
    static final class Member {
        final String name;
        final String descriptor;
        final boolean isStatic;

        Member(String name, String descriptor, boolean isStatic) {
            this.name = name;
            this.descriptor = descriptor;
            this.isStatic = isStatic;
        }
    }

    /** What the scanned code needs of one absent class. */
    static final class Stub {
        final String name;
        boolean isInterface;
        boolean throwable;
        boolean neutralInstance;
        final Map<String, Member> methods = new TreeMap<>();
        final Map<String, Member> fields = new TreeMap<>();
        final Set<String> constructors = new java.util.TreeSet<>();

        Stub(String name) {
            this.name = name;
        }
    }

    /** The references of the scanned classes into the namespace, by class. */
    static final class References {
        final Pattern namespace;
        final Map<String, Stub> stubs = new TreeMap<>();

        References(Pattern namespace) {
            this.namespace = namespace;
        }

        boolean inNamespace(String internalName) {
            return internalName != null && namespace.matcher(internalName).find();
        }

        Stub stub(String internalName) {
            return stubs.computeIfAbsent(internalName, Stub::new);
        }

        void type(Type type) {
            if (type == null) return;
            if (type.getSort() == Type.ARRAY) type = type.getElementType();
            if (type.getSort() == Type.OBJECT && inNamespace(type.getInternalName())) {
                stub(type.getInternalName());
            } else if (type.getSort() == Type.METHOD) {
                type(type.getReturnType());
                for (Type argument : type.getArgumentTypes()) type(argument);
            }
        }

        void descriptor(String descriptor) {
            if (descriptor == null) return;
            type(descriptor.startsWith("(") ? Type.getMethodType(descriptor) : Type.getType(descriptor));
        }

        void internalName(String internalName) {
            if (internalName == null) return;
            type(internalName.startsWith("[") ? Type.getType(internalName)
                    : Type.getObjectType(internalName));
        }

        void method(String owner, String name, String descriptor, boolean isStatic, boolean itf) {
            descriptor(descriptor);
            if (owner.startsWith("[") || !inNamespace(owner)) return;
            Stub stub = stub(owner);
            stub.isInterface |= itf;
            if ("<init>".equals(name)) stub.constructors.add(descriptor);
            else stub.methods.putIfAbsent(name + descriptor, new Member(name, descriptor, isStatic));
        }

        void field(String owner, String name, String descriptor, boolean isStatic) {
            descriptor(descriptor);
            if (!inNamespace(owner)) return;
            stub(owner).fields.putIfAbsent(name, new Member(name, descriptor, isStatic));
        }

        void handle(Handle handle) {
            int tag = handle.getTag();
            if (tag <= Opcodes.H_PUTSTATIC) {
                field(handle.getOwner(), handle.getName(), handle.getDesc(),
                        tag == Opcodes.H_GETSTATIC || tag == Opcodes.H_PUTSTATIC);
            } else {
                method(handle.getOwner(), handle.getName(), handle.getDesc(),
                        tag == Opcodes.H_INVOKESTATIC, handle.isInterface());
            }
        }

        void constant(Object value) {
            if (value instanceof Type) type((Type) value);
            else if (value instanceof Handle) handle((Handle) value);
        }
    }

    // --- scanning -----------------------------------------------------------------

    static void scan(byte[] bytes, References references) {
        new ClassReader(bytes).accept(new ClassVisitor(Opcodes.ASM9) {
            @Override
            public void visit(int version, int access, String name, String signature,
                              String superName, String[] interfaces) {
                if (references.inNamespace(superName)) references.stub(superName);
                if (interfaces != null) {
                    for (String each : interfaces) {
                        if (references.inNamespace(each)) references.stub(each).isInterface = true;
                    }
                }
            }

            @Override
            public FieldVisitor visitField(int access, String name, String descriptor,
                                           String signature, Object value) {
                references.descriptor(descriptor);
                return null;
            }

            @Override
            public MethodVisitor visitMethod(int access, String name, String descriptor,
                                             String signature, String[] exceptions) {
                references.descriptor(descriptor);
                return new MethodVisitor(Opcodes.ASM9) {
                    @Override
                    public void visitMethodInsn(int opcode, String owner, String member,
                                                String memberDescriptor, boolean itf) {
                        references.method(owner, member, memberDescriptor,
                                opcode == Opcodes.INVOKESTATIC, itf);
                    }

                    @Override
                    public void visitFieldInsn(int opcode, String owner, String member,
                                               String memberDescriptor) {
                        references.field(owner, member, memberDescriptor,
                                opcode == Opcodes.GETSTATIC || opcode == Opcodes.PUTSTATIC);
                    }

                    @Override
                    public void visitTypeInsn(int opcode, String type) {
                        references.internalName(type);
                    }

                    @Override
                    public void visitLdcInsn(Object value) {
                        references.constant(value);
                    }

                    @Override
                    public void visitMultiANewArrayInsn(String arrayDescriptor, int dimensions) {
                        references.descriptor(arrayDescriptor);
                    }

                    @Override
                    public void visitInvokeDynamicInsn(String member, String memberDescriptor,
                                                       Handle bootstrap, Object... arguments) {
                        references.descriptor(memberDescriptor);
                        references.handle(bootstrap);
                        for (Object argument : arguments) references.constant(argument);
                    }

                    @Override
                    public void visitTryCatchBlock(Label start, Label end, Label handler,
                                                   String type) {
                        if (references.inNamespace(type)) references.stub(type).throwable = true;
                    }

                    @Override
                    public void visitLocalVariable(String local, String localDescriptor,
                                                   String localSignature, Label start, Label end,
                                                   int index) {
                        references.descriptor(localDescriptor);
                    }
                };
            }
        }, ClassReader.SKIP_FRAMES);
    }

    static boolean holdsAny(byte[] bytes, byte[][] hints) {
        for (byte[] hint : hints) {
            outer:
            for (int at = 0; at + hint.length <= bytes.length; at++) {
                for (int k = 0; k < hint.length; k++) {
                    if (bytes[at + k] != hint[k]) continue outer;
                }
                return true;
            }
        }
        return false;
    }

    static void scanEntry(Path entry, byte[][] hints, References references) throws IOException {
        if (Files.isDirectory(entry)) {
            List<Path> classes = new ArrayList<>();
            try (Stream<Path> walk = Files.walk(entry)) {
                walk.filter(path -> path.toString().endsWith(".class")).forEach(classes::add);
            }
            for (Path path : classes) {
                byte[] bytes = Files.readAllBytes(path);
                if (holdsAny(bytes, hints)) scan(bytes, references);
            }
        } else if (Files.isRegularFile(entry)) {
            try (ZipFile jar = new ZipFile(entry.toFile())) {
                Enumeration<? extends ZipEntry> entries = jar.entries();
                while (entries.hasMoreElements()) {
                    ZipEntry each = entries.nextElement();
                    if (!each.getName().endsWith(".class")) continue;
                    byte[] bytes;
                    try (InputStream in = jar.getInputStream(each)) {
                        bytes = readAll(in);
                    }
                    if (holdsAny(bytes, hints)) scan(bytes, references);
                }
            }
        }
    }

    private static byte[] readAll(InputStream in) throws IOException {
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
        byte[] buffer = new byte[65536];
        for (int read; (read = in.read(buffer)) > 0; ) out.write(buffer, 0, read);
        return out.toByteArray();
    }

    /** Which internal class names the classpath provides, answered entry by entry. */
    static final class Classpath {
        private final List<Path> entries;
        private final Map<Path, Set<String>> jars = new HashMap<>();

        Classpath(List<Path> entries) {
            this.entries = entries;
        }

        boolean provides(String internalName) throws IOException {
            String file = internalName + ".class";
            for (Path entry : entries) {
                if (Files.isDirectory(entry)) {
                    if (Files.isRegularFile(entry.resolve(file))) return true;
                } else if (Files.isRegularFile(entry)) {
                    Set<String> names = jars.get(entry);
                    if (names == null) {
                        names = new HashSet<>();
                        try (ZipFile jar = new ZipFile(entry.toFile())) {
                            Enumeration<? extends ZipEntry> all = jar.entries();
                            while (all.hasMoreElements()) names.add(all.nextElement().getName());
                        }
                        jars.put(entry, names);
                    }
                    if (names.contains(file)) return true;
                }
            }
            return false;
        }
    }

    // --- generation -----------------------------------------------------------------

    /** Neutral stand-ins for the referenced classes no entry provides, by internal name. */
    static Map<String, byte[]> generate(References references, Classpath classpath)
            throws IOException {
        Map<String, Stub> absent = new TreeMap<>();
        for (Stub stub : references.stubs.values()) {
            if (!classpath.provides(stub.name)) absent.put(stub.name, stub);
        }
        // A method returning a stand-in type returns its neutral instance.
        for (Stub stub : absent.values()) {
            for (Member method : stub.methods.values()) {
                Type returned = Type.getReturnType(method.descriptor);
                if (returned.getSort() == Type.OBJECT && absent.containsKey(returned.getInternalName())
                        && !absent.get(returned.getInternalName()).isInterface) {
                    absent.get(returned.getInternalName()).neutralInstance = true;
                }
            }
        }
        Map<String, byte[]> classes = new TreeMap<>();
        for (Stub stub : absent.values()) classes.put(stub.name, write(stub, absent));
        return classes;
    }

    static String superName(Stub stub) {
        return stub.isInterface ? "java/lang/Object"
                : stub.throwable ? "java/lang/RuntimeException" : "java/lang/Object";
    }

    static byte[] write(Stub stub, Map<String, Stub> absent) {
        ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_FRAMES | ClassWriter.COMPUTE_MAXS) {
            @Override
            protected String getCommonSuperClass(String first, String second) {
                return "java/lang/Object";
            }
        };
        int access = Opcodes.ACC_PUBLIC | Opcodes.ACC_SUPER
                | (stub.isInterface ? Opcodes.ACC_INTERFACE | Opcodes.ACC_ABSTRACT : 0);
        if (stub.isInterface) access &= ~Opcodes.ACC_SUPER;
        String parent = superName(stub);
        writer.visit(Opcodes.V1_8, access, stub.name, null, parent, null);
        for (Member field : stub.fields.values()) {
            int fieldAccess = Opcodes.ACC_PUBLIC | (field.isStatic || stub.isInterface
                    ? Opcodes.ACC_STATIC : 0) | (stub.isInterface ? Opcodes.ACC_FINAL : 0);
            writer.visitField(fieldAccess, field.name, field.descriptor, null, null).visitEnd();
        }
        if (stub.neutralInstance) {
            writer.visitField(Opcodes.ACC_PUBLIC | Opcodes.ACC_STATIC | Opcodes.ACC_FINAL,
                    NEUTRAL, "L" + stub.name + ";", null, null).visitEnd();
        }
        if (!stub.isInterface) {
            Set<String> constructors = new java.util.TreeSet<>(stub.constructors);
            constructors.add("()V");
            for (String descriptor : constructors) constructor(writer, stub, parent, descriptor);
        }
        staticInitializer(writer, stub);
        for (Member method : stub.methods.values()) {
            int methodAccess = Opcodes.ACC_PUBLIC | (method.isStatic ? Opcodes.ACC_STATIC : 0);
            MethodVisitor code = writer.visitMethod(methodAccess, method.name, method.descriptor,
                    null, null);
            code.visitCode();
            Type type = Type.getMethodType(method.descriptor);
            if (type.getReturnType().getSort() == Type.VOID) runRunnables(code, type, method.isStatic);
            neutralReturn(code, type.getReturnType(), absent);
            code.visitMaxs(0, 0);
            code.visitEnd();
        }
        writer.visitEnd();
        return writer.toByteArray();
    }

    private static void constructor(ClassWriter writer, Stub stub, String parent, String descriptor) {
        MethodVisitor code = writer.visitMethod(Opcodes.ACC_PUBLIC, "<init>", descriptor, null, null);
        code.visitCode();
        code.visitVarInsn(Opcodes.ALOAD, 0);
        code.visitMethodInsn(Opcodes.INVOKESPECIAL, parent, "<init>", "()V", false);
        for (Member field : stub.fields.values()) {
            if (field.isStatic || !"Ljava/lang/String;".equals(field.descriptor)) continue;
            code.visitVarInsn(Opcodes.ALOAD, 0);
            code.visitLdcInsn("");
            code.visitFieldInsn(Opcodes.PUTFIELD, stub.name, field.name, field.descriptor);
        }
        code.visitInsn(Opcodes.RETURN);
        code.visitMaxs(0, 0);
        code.visitEnd();
    }

    private static void staticInitializer(ClassWriter writer, Stub stub) {
        boolean strings = stub.fields.values().stream().anyMatch(field ->
                (field.isStatic || stub.isInterface) && "Ljava/lang/String;".equals(field.descriptor));
        if (!strings && !stub.neutralInstance) return;
        MethodVisitor code = writer.visitMethod(Opcodes.ACC_STATIC, "<clinit>", "()V", null, null);
        code.visitCode();
        for (Member field : stub.fields.values()) {
            if (!(field.isStatic || stub.isInterface) || !"Ljava/lang/String;".equals(field.descriptor)) {
                continue;
            }
            code.visitLdcInsn("");
            code.visitFieldInsn(Opcodes.PUTSTATIC, stub.name, field.name, field.descriptor);
        }
        if (stub.neutralInstance) {
            code.visitTypeInsn(Opcodes.NEW, stub.name);
            code.visitInsn(Opcodes.DUP);
            code.visitMethodInsn(Opcodes.INVOKESPECIAL, stub.name, "<init>", "()V", false);
            code.visitFieldInsn(Opcodes.PUTSTATIC, stub.name, NEUTRAL, "L" + stub.name + ";");
        }
        code.visitInsn(Opcodes.RETURN);
        code.visitMaxs(0, 0);
        code.visitEnd();
    }

    private static void runRunnables(MethodVisitor code, Type type, boolean isStatic) {
        int slot = isStatic ? 0 : 1;
        for (Type argument : type.getArgumentTypes()) {
            if ("Ljava/lang/Runnable;".equals(argument.getDescriptor())) {
                Label skip = new Label();
                code.visitVarInsn(Opcodes.ALOAD, slot);
                code.visitJumpInsn(Opcodes.IFNULL, skip);
                code.visitVarInsn(Opcodes.ALOAD, slot);
                code.visitMethodInsn(Opcodes.INVOKEINTERFACE, "java/lang/Runnable", "run", "()V", true);
                code.visitLabel(skip);
            }
            slot += argument.getSize();
        }
    }

    private static void neutralReturn(MethodVisitor code, Type returned, Map<String, Stub> absent) {
        switch (returned.getSort()) {
            case Type.VOID:
                code.visitInsn(Opcodes.RETURN);
                return;
            case Type.BOOLEAN: case Type.BYTE: case Type.CHAR: case Type.SHORT: case Type.INT:
                code.visitInsn(Opcodes.ICONST_0);
                code.visitInsn(Opcodes.IRETURN);
                return;
            case Type.LONG:
                code.visitInsn(Opcodes.LCONST_0);
                code.visitInsn(Opcodes.LRETURN);
                return;
            case Type.FLOAT:
                code.visitInsn(Opcodes.FCONST_0);
                code.visitInsn(Opcodes.FRETURN);
                return;
            case Type.DOUBLE:
                code.visitInsn(Opcodes.DCONST_0);
                code.visitInsn(Opcodes.DRETURN);
                return;
            case Type.ARRAY:
                code.visitInsn(Opcodes.ICONST_0);
                Type component = Type.getType(returned.getDescriptor().substring(1));
                if (component.getSort() == Type.OBJECT || component.getSort() == Type.ARRAY) {
                    code.visitTypeInsn(Opcodes.ANEWARRAY, component.getSort() == Type.OBJECT
                            ? component.getInternalName() : component.getDescriptor());
                } else {
                    code.visitIntInsn(Opcodes.NEWARRAY, primitiveArrayType(component));
                }
                code.visitInsn(Opcodes.ARETURN);
                return;
            default:
                String name = returned.getInternalName();
                Stub stub = absent.get(name);
                if ("java/lang/String".equals(name)) code.visitLdcInsn("");
                else if (stub != null && stub.neutralInstance) {
                    code.visitFieldInsn(Opcodes.GETSTATIC, name, NEUTRAL, "L" + name + ";");
                } else code.visitInsn(Opcodes.ACONST_NULL);
                code.visitInsn(Opcodes.ARETURN);
        }
    }

    private static int primitiveArrayType(Type component) {
        switch (component.getSort()) {
            case Type.BOOLEAN: return Opcodes.T_BOOLEAN;
            case Type.BYTE: return Opcodes.T_BYTE;
            case Type.CHAR: return Opcodes.T_CHAR;
            case Type.SHORT: return Opcodes.T_SHORT;
            case Type.INT: return Opcodes.T_INT;
            case Type.LONG: return Opcodes.T_LONG;
            case Type.FLOAT: return Opcodes.T_FLOAT;
            default: return Opcodes.T_DOUBLE;
        }
    }

    /** What each stand-in answers, for the record. */
    static JsonObject manifest(Map<String, Stub> stubs, Set<String> written) {
        JsonObject root = new JsonObject();
        JsonArray classes = new JsonArray();
        for (Stub stub : stubs.values()) {
            if (!written.contains(stub.name)) continue;
            JsonObject row = new JsonObject();
            row.addProperty("class", stub.name.replace('/', '.'));
            row.addProperty("kind", stub.isInterface ? "interface" : "class");
            row.addProperty("super", superName(stub).replace('/', '.'));
            JsonArray methods = new JsonArray();
            for (Member method : stub.methods.values()) {
                JsonObject each = new JsonObject();
                each.addProperty("name", method.name);
                each.addProperty("descriptor", method.descriptor);
                each.addProperty("static", method.isStatic);
                each.addProperty("answer", answer(Type.getMethodType(method.descriptor), stubs));
                methods.add(each);
            }
            row.add("methods", methods);
            JsonArray fields = new JsonArray();
            for (Member field : stub.fields.values()) {
                JsonObject each = new JsonObject();
                each.addProperty("name", field.name);
                each.addProperty("descriptor", field.descriptor);
                each.addProperty("static", field.isStatic);
                fields.add(each);
            }
            row.add("fields", fields);
            JsonArray constructors = new JsonArray();
            stub.constructors.forEach(constructors::add);
            row.add("constructors", constructors);
            classes.add(row);
        }
        root.add("classes", classes);
        return root;
    }

    static String answer(Type method, Map<String, Stub> stubs) {
        Type returned = method.getReturnType();
        switch (returned.getSort()) {
            case Type.VOID:
                for (Type argument : method.getArgumentTypes()) {
                    if ("Ljava/lang/Runnable;".equals(argument.getDescriptor())) {
                        return "runs its Runnable arguments";
                    }
                }
                return "nothing";
            case Type.BOOLEAN: return "false";
            case Type.ARRAY: return "an empty array";
            case Type.OBJECT:
                if ("java/lang/String".equals(returned.getInternalName())) return "\"\"";
                Stub stub = stubs.get(returned.getInternalName());
                return stub != null && stub.neutralInstance ? "the neutral instance" : "null";
            default: return "0";
        }
    }

    public static void main(String[] args) throws IOException {
        if (args.length < 5) {
            throw new IllegalArgumentException(
                    "usage: NeutralAdapter <output dir> <manifest> <namespace regex> <hints> <entry>...");
        }
        Path output = Paths.get(args[0]);
        Path manifestPath = Paths.get(args[1]);
        References references = new References(Pattern.compile(args[2]));
        String[] hintText = args[3].split(",");
        byte[][] hints = new byte[hintText.length][];
        for (int i = 0; i < hintText.length; i++) hints[i] = hintText[i].getBytes(StandardCharsets.UTF_8);
        List<Path> entries = new ArrayList<>();
        for (int i = 4; i < args.length; i++) {
            boolean scanned = args[i].startsWith("+");
            Path entry = Paths.get(scanned ? args[i].substring(1) : args[i]);
            entries.add(entry);
            if (scanned) scanEntry(entry, hints, references);
        }
        Map<String, byte[]> classes = generate(references, new Classpath(entries));
        for (Map.Entry<String, byte[]> each : classes.entrySet()) {
            Path file = output.resolve(each.getKey().replace('/', File.separatorChar) + ".class");
            Files.createDirectories(file.getParent());
            Files.write(file, each.getValue());
        }
        JsonObject manifest = manifest(references.stubs, classes.keySet());
        manifest.addProperty("namespace", args[2]);
        Files.createDirectories(manifestPath.toAbsolutePath().getParent());
        Files.write(manifestPath, new GsonBuilder().setPrettyPrinting().create()
                .toJson(manifest).getBytes(StandardCharsets.UTF_8));
        System.out.println("neutral adapter: " + classes.size() + " classes in " + output);
    }
}
