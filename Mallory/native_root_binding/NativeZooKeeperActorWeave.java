package edu.uva.liftlab.mallory.nativebinding;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
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
        transform(classes, "org/apache/zookeeper/server/quorum/QuorumPeer", false);
        transform(classes, "org/apache/zookeeper/server/quorum/Learner", true);
        Path bridge = classes.resolve(BRIDGE + ".class");
        Files.createDirectories(bridge.getParent());
        try (InputStream source = NativeZooKeeperActorBridge.class
                .getClassLoader().getResourceAsStream(BRIDGE + ".class")) {
            if (source == null) throw new IOException("bridge class resource absent");
            Files.copy(source, bridge, StandardCopyOption.REPLACE_EXISTING);
        }
        System.out.println("NATIVE_ZK_ACTOR_BINDING_OK " + classes);
    }

    private static void transform(Path classes, String internalName,
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
        ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
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
                    @Override protected void onMethodEnter() {
                        loadThis();
                        invokeStatic(BRIDGE_TYPE, new Method(entry,
                                "(Ljava/lang/Object;)V"));
                    }
                    @Override protected void onMethodExit(int opcode) {
                        invokeStatic(BRIDGE_TYPE, new Method(exit, "()V"));
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
        Files.write(path, writer.toByteArray());
    }

    private static final class Counts {
        private int actorMethods;
        private int carrierMethods;
    }
}
