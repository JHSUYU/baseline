package edu.uva.liftlab.crashfuzz.runtime;

import org.junit.Test;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.regex.Pattern;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public class NeutralAdapterTest {
    private static final String DOORS = "edu/uva/liftlab/graphchecker/runtime/Doors";
    private static final String OUTBOUND = DOORS + "$Outbound";
    private static final String SHIM = "org/example/ipc/CausynthPropagation";

    /** A tree class calling doors no classpath entry provides. */
    private static byte[] caller() {
        ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_FRAMES | ClassWriter.COMPUTE_MAXS);
        writer.visit(Opcodes.V1_8, Opcodes.ACC_PUBLIC, "example/Caller", null, "java/lang/Object", null);
        method(writer, "notifyThrough", "(Ljava/lang/Runnable;)V", code -> {
            code.visitLdcInsn("watch");
            code.visitVarInsn(Opcodes.ALOAD, 0);
            code.visitMethodInsn(Opcodes.INVOKESTATIC, DOORS, "notified",
                    "(Ljava/lang/String;Ljava/lang/Runnable;)V", false);
            code.visitInsn(Opcodes.RETURN);
        });
        method(writer, "publish", "(Ljava/lang/Runnable;)Z", code -> {
            code.visitLdcInsn("/path");
            code.visitInsn(Opcodes.LCONST_1);
            code.visitVarInsn(Opcodes.ALOAD, 0);
            code.visitMethodInsn(Opcodes.INVOKESTATIC, DOORS, "publishing",
                    "(Ljava/lang/String;JLjava/lang/Runnable;)Z", false);
            code.visitInsn(Opcodes.IRETURN);
        });
        method(writer, "trace", "()Ljava/lang/String;", code -> {
            code.visitMethodInsn(Opcodes.INVOKESTATIC, DOORS, "outbound", "()L" + OUTBOUND + ";", false);
            code.visitFieldInsn(Opcodes.GETFIELD, OUTBOUND, "trace", "Ljava/lang/String;");
            code.visitInsn(Opcodes.ARETURN);
        });
        method(writer, "active", "()Z", code -> {
            code.visitMethodInsn(Opcodes.INVOKESTATIC, DOORS, "outbound", "()L" + OUTBOUND + ";", false);
            code.visitMethodInsn(Opcodes.INVOKEVIRTUAL, OUTBOUND, "active", "()Z", false);
            code.visitInsn(Opcodes.IRETURN);
        });
        method(writer, "tick", "()J", code -> {
            code.visitInsn(Opcodes.ACONST_NULL);
            code.visitMethodInsn(Opcodes.INVOKESTATIC, SHIM, "beginTick", "(Ljava/lang/Object;)J", false);
            code.visitInsn(Opcodes.LRETURN);
        });
        method(writer, "scope", "()Ljava/lang/Object;", code -> {
            code.visitMethodInsn(Opcodes.INVOKESTATIC, SHIM, "captureScope", "()Ljava/lang/Object;", false);
            code.visitInsn(Opcodes.ARETURN);
        });
        method(writer, "names", "()[Ljava/lang/String;", code -> {
            code.visitMethodInsn(Opcodes.INVOKESTATIC, DOORS, "names", "()[Ljava/lang/String;", false);
            code.visitInsn(Opcodes.ARETURN);
        });
        method(writer, "present", "()Ljava/lang/String;", code -> {
            code.visitMethodInsn(Opcodes.INVOKESTATIC, "example/CausynthHelper", "name",
                    "()Ljava/lang/String;", false);
            code.visitInsn(Opcodes.ARETURN);
        });
        writer.visitEnd();
        return writer.toByteArray();
    }

    private interface Body { void emit(MethodVisitor code); }

    private static void method(ClassWriter writer, String name, String descriptor, Body body) {
        MethodVisitor code = writer.visitMethod(Opcodes.ACC_PUBLIC | Opcodes.ACC_STATIC, name,
                descriptor, null, null);
        code.visitCode();
        body.emit(code);
        code.visitMaxs(0, 0);
        code.visitEnd();
    }

    private static final class Loader extends ClassLoader {
        private final Map<String, byte[]> classes;

        Loader(Map<String, byte[]> classes) {
            super(NeutralAdapterTest.class.getClassLoader());
            this.classes = classes;
        }

        @Override
        protected Class<?> findClass(String name) throws ClassNotFoundException {
            byte[] bytes = classes.get(name.replace('.', '/'));
            if (bytes == null) throw new ClassNotFoundException(name);
            return defineClass(name, bytes, 0, bytes.length);
        }
    }

    @Test
    public void absentDoorsAnswerNeutrallyAndRunTheSystemsWork() throws Exception {
        Path present = Files.createTempDirectory("present");
        Files.createDirectories(present.resolve("example"));
        Files.write(present.resolve("example/CausynthHelper.class"), new byte[] {0});
        NeutralAdapter.References references = new NeutralAdapter.References(
                Pattern.compile("^edu/uva/liftlab/graphchecker/|(^|/)Causynth[^/]*$"));
        NeutralAdapter.scan(caller(), references);
        Map<String, byte[]> stubs = NeutralAdapter.generate(references,
                new NeutralAdapter.Classpath(Collections.singletonList(present)));
        assertEquals(new java.util.TreeSet<>(java.util.Arrays.asList(DOORS, OUTBOUND, SHIM)),
                stubs.keySet());   // the tree's own CausynthHelper is present: no stand-in

        Map<String, byte[]> all = new HashMap<>(stubs);
        all.put("example/Caller", caller());
        Class<?> caller = new Loader(all).loadClass("example.Caller");
        AtomicInteger ran = new AtomicInteger();
        Runnable work = ran::incrementAndGet;
        caller.getMethod("notifyThrough", Runnable.class).invoke(null, work);
        assertEquals(1, ran.get());            // a void door runs the work it is handed
        assertFalse((Boolean) caller.getMethod("publish", Runnable.class).invoke(null, work));
        assertEquals(1, ran.get());            // one answering false leaves it to the caller
        assertEquals("", caller.getMethod("trace").invoke(null));
        assertFalse((Boolean) caller.getMethod("active").invoke(null));
        assertEquals(0L, caller.getMethod("tick").invoke(null));
        assertEquals(null, caller.getMethod("scope").invoke(null));
        assertArrayEquals(new String[0], (String[]) caller.getMethod("names").invoke(null));
        Method notified = caller.getMethod("notifyThrough", Runnable.class);
        notified.invoke(null, (Runnable) null);  // a null callback is not run
        assertTrue(NeutralAdapter.manifest(references.stubs, stubs.keySet()).toString()
                .contains("runs its Runnable arguments"));
    }
}
