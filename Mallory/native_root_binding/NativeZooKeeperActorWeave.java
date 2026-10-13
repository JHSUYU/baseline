package edu.uva.liftlab.mallory.nativebinding;

import java.io.IOException;
import java.io.InputStream;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.Type;
import org.objectweb.asm.commons.AdviceAdapter;
import org.objectweb.asm.commons.Method;

/** Post-processes original GraphChecker-woven ZooKeeper classes in place. */
public final class NativeZooKeeperActorWeave {
    private static final String BRIDGE =
            Type.getInternalName(NativeZooKeeperActorBridge.class);
    private static final Type BRIDGE_TYPE =
            Type.getType(NativeZooKeeperActorBridge.class);

    private NativeZooKeeperActorWeave() { }

    public static void main(String[] args) throws Exception {
        if (args.length != 2 || !"--classes".equals(args[0])) {
            throw new IllegalArgumentException("expected --classes WOVEN_DIRECTORY");
        }
        Path classes = Paths.get(args[1]).toAbsolutePath();
        String peerName = "org/apache/zookeeper/server/quorum/QuorumPeer";
        String learnerName = "org/apache/zookeeper/server/quorum/Learner";
        // Compute both before writing either. A missing dependency while ASM
        // merges frames must not leave half of the actor adapter installed.
        byte[] peer = transform(classes, peerName, false);
        byte[] learner = transform(classes, learnerName, true);
        Files.write(classes.resolve(peerName + ".class"), peer);
        Files.write(classes.resolve(learnerName + ".class"), learner);
        Path bridge = classes.resolve(BRIDGE + ".class");
        Files.createDirectories(bridge.getParent());
        try (InputStream source = NativeZooKeeperActorBridge.class
                .getClassLoader().getResourceAsStream(BRIDGE + ".class")) {
            if (source == null) throw new IOException("bridge class resource absent");
            Files.copy(source, bridge, StandardCopyOption.REPLACE_EXISTING);
        }
        System.out.println("NATIVE_ZK_ACTOR_BINDING_OK " + classes);
    }

    private static byte[] transform(Path classes, String internalName,
                                    boolean learner) throws IOException {
        Path path = classes.resolve(internalName + ".class");
        if (!Files.isRegularFile(path)) {
            throw new IOException("original woven class is absent: " + path);
        }
        ClassReader reader = new ClassReader(Files.readAllBytes(path));
        Counts prior = new Counts();
        reader.accept(new ClassVisitor(Opcodes.ASM9) {
            @Override public MethodVisitor visitMethod(int access, String name,
                    String descriptor, String signature, String[] exceptions) {
                return new MethodVisitor(Opcodes.ASM9) {
                    @Override public void visitMethodInsn(int opcode,
                            String owner, String method, String desc,
                            boolean isInterface) {
                        if (BRIDGE.equals(owner)) prior.actorMethods++;
                    }
                };
            }
        }, ClassReader.SKIP_DEBUG | ClassReader.SKIP_FRAMES);
        if (prior.actorMethods != 0) {
            throw new IOException("actor binding already woven: " + path);
        }
        // The catch-all below adds one verifier frame. Resolve common types
        // against the woven application tree, rather than this adapter's own
        // small classpath (which has no ZooKeeper application classes).
        ClassLoader hierarchy = new URLClassLoader(
                new URL[] {classes.toUri().toURL()},
                NativeZooKeeperActorWeave.class.getClassLoader());
        ClassWriter writer = new ClassWriter(reader,
                ClassWriter.COMPUTE_MAXS | ClassWriter.COMPUTE_FRAMES) {
            @Override protected String getCommonSuperClass(String left,
                                                              String right) {
                try {
                    Class<?> a = Class.forName(left.replace('/', '.'), false,
                            hierarchy);
                    Class<?> b = Class.forName(right.replace('/', '.'), false,
                            hierarchy);
                    if (a.isAssignableFrom(b)) return left;
                    if (b.isAssignableFrom(a)) return right;
                    if (a.isInterface() || b.isInterface())
                        return "java/lang/Object";
                    do { a = a.getSuperclass(); } while (!a.isAssignableFrom(b));
                    return Type.getInternalName(a);
                } catch (ClassNotFoundException failure) {
                    throw new IllegalStateException("cannot resolve actor frame "
                            + left + " and " + right, failure);
                }
            }
        };
        Counts counts = new Counts();
        reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
            @Override
            public MethodVisitor visitMethod(int access, String name,
                                             String descriptor,
                                             String signature,
                                             String[] exceptions) {
                MethodVisitor next = super.visitMethod(access, name,
                        descriptor, signature, exceptions);
                if (next == null || (access & Opcodes.ACC_STATIC) != 0
                        || (access & Opcodes.ACC_ABSTRACT) != 0
                        || name.startsWith("<")) return next;
                if (learner) {
                    counts.carrierMethods++;
                    return new AdviceAdapter(Opcodes.ASM9, next, access,
                            name, descriptor) {
                        @Override protected void onMethodEnter() {
                            loadThis();
                            invokeStatic(BRIDGE_TYPE, new Method(
                                    "learnerEntered", "(Ljava/lang/Object;)V"));
                        }
                    };
                }
                if (!"()V".equals(descriptor) || (!"start".equals(name)
                        && !"run".equals(name))) return next;
                counts.actorMethods++;
                String entry = "start".equals(name)
                        ? "peerStartEntered" : "peerRunEntered";
                String exit = "start".equals(name)
                        ? "peerStartExited" : "peerRunExited";
                return new AdviceAdapter(Opcodes.ASM9, next, access,
                        name, descriptor) {
                    private final Label begin = new Label();
                    private final Label finish = new Label();
                    private final Label exceptionalExit = new Label();

                    @Override protected void onMethodEnter() {
                        loadThis();
                        invokeStatic(BRIDGE_TYPE, new Method(entry,
                                "(Ljava/lang/Object;)V"));
                        mark(begin);
                    }
                    @Override protected void onMethodExit(int opcode) {
                        // An ATHROW in the original method may be caught by
                        // that same method. Closing here loses the peer turn
                        // while its catch block is still running.
                        if (opcode != ATHROW) {
                            invokeStatic(BRIDGE_TYPE, new Method(exit, "()V"));
                        }
                    }
                    @Override public void visitMaxs(int maxStack,
                                                    int maxLocals) {
                        mark(finish);
                        visitTryCatchBlock(begin, finish, exceptionalExit,
                                null);
                        mark(exceptionalExit);
                        invokeStatic(BRIDGE_TYPE, new Method(exit, "()V"));
                        throwException();
                        super.visitMaxs(maxStack, maxLocals);
                    }
                };
            }
        }, ClassReader.EXPAND_FRAMES);
        if (learner && counts.carrierMethods < 1 || !learner
                && counts.actorMethods != 2) {
            throw new IOException("actor lifecycle signature changed: "
                    + internalName + " actor=" + counts.actorMethods
                    + " carrier=" + counts.carrierMethods);
        }
        return writer.toByteArray();
    }

    private static final class Counts {
        private int actorMethods;
        private int carrierMethods;
    }
}
