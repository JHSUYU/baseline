package edu.uva.liftlab.crashfuzz.runtime;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.lang.instrument.ClassFileTransformer;
import java.lang.reflect.Constructor;
import java.util.Collections;
import java.util.Map;
import org.junit.Test;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

import static org.junit.Assert.assertEquals;

public class SolrControllerInstrumentationTest {
    @Test
    public void registersControllerAfterItsConstructorReturns() throws Exception {
        String owner = "org/apache/solr/cloud/ZkController";
        byte[] original;
        try (InputStream input = getClass().getClassLoader().getResourceAsStream(owner + ".class")) {
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            int count;
            while ((count = input.read(buffer)) >= 0) output.write(buffer, 0, count);
            original = output.toByteArray();
        }
        Class<?> type = Class.forName(SelectionAgent.class.getName() + "$Transformer");
        Constructor<?> constructor = type.getDeclaredConstructor(Map.class);
        constructor.setAccessible(true);
        ClassFileTransformer transformer = (ClassFileTransformer) constructor.newInstance(
                Collections.emptyMap());
        byte[] rewritten = transformer.transform(getClass().getClassLoader(), owner,
                null, null, original);
        final int[] registrations = {0};
        new ClassReader(rewritten).accept(new ClassVisitor(Opcodes.ASM9) {
            @Override public MethodVisitor visitMethod(int access, String name,
                    String descriptor, String signature, String[] exceptions) {
                if (!"<init>".equals(name)) return null;
                return new MethodVisitor(Opcodes.ASM9) {
                    @Override public void visitMethodInsn(int opcode, String callee,
                            String method, String callDescriptor, boolean isInterface) {
                        if (opcode == Opcodes.INVOKESTATIC &&
                                callee.equals("edu/uva/liftlab/crashfuzz/runtime/SelectionProbe") &&
                                method.equals("registerSolrController")) registrations[0]++;
                    }
                };
            }
        }, 0);
        assertEquals(1, registrations[0]);
    }
}
