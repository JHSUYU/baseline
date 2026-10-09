package edu.uva.liftlab.mallory.hbase31;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import java.io.File;
import java.security.MessageDigest;
import java.util.jar.JarFile;
import org.junit.Test;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;

public class DispatchBindingTransformerTest {
  private static final String CLASS =
      "org/apache/hadoop/hbase/master/procedure/RSProcedureDispatcher$ExecuteProceduresRemoteCall";
  private static final String JAR =
      "/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-server-2.6.6.jar";

  @Test public void exactCompiledMethodReceivesOneEntryAndExitScope() throws Exception {
    byte[] original;
    try (JarFile jar = new JarFile(new File(JAR))) {
      try (java.io.InputStream input = jar.getInputStream(jar.getJarEntry(CLASS + ".class"))) {
        original = read(input);
      }
    }
    assertEquals("d3d8d4ea265e4b271371ca7876d266b0ccfa9067b1e7a78307d679a00c3038da",
        hex(MessageDigest.getInstance("SHA-256").digest(original)));
    DispatchBindingTransformer transformer = new DispatchBindingTransformer();
    assertNull(transformer.transform(getClass().getClassLoader(), "unrelated/Class", null,
        null, original));
    byte[] transformed = transformer.transform(getClass().getClassLoader(), CLASS, null,
        null, original);
    assertNotNull(transformed);
    ClassNode node = new ClassNode();
    new ClassReader(transformed).accept(node, 0);
    int entries = 0, exits = 0;
    for (MethodNode method : node.methods) {
      if (!method.name.equals("sendRequest")) continue;
      for (AbstractInsnNode instruction : method.instructions) {
        if (!(instruction instanceof MethodInsnNode)) continue;
        MethodInsnNode call = (MethodInsnNode) instruction;
        if (call.owner.equals("edu/uva/liftlab/mallory/hbase31/DispatchBindingHooks")
            && call.name.equals("enterSendRequest") && call.getOpcode() == Opcodes.INVOKESTATIC)
          entries++;
        if (call.owner.equals("edu/uva/liftlab/mallory/instrumentation/Probe$NodeScope")
            && call.name.equals("close")) exits++;
      }
    }
    assertEquals(1, entries);
    assertEquals(2, exits);
  }

  private static byte[] read(java.io.InputStream input) throws java.io.IOException {
    java.io.ByteArrayOutputStream output = new java.io.ByteArrayOutputStream();
    byte[] block = new byte[8192];
    for (int count; (count = input.read(block)) >= 0; ) output.write(block, 0, count);
    return output.toByteArray();
  }

  private static String hex(byte[] bytes) {
    StringBuilder text = new StringBuilder();
    for (byte value : bytes) text.append(String.format("%02x", value & 0xff));
    return text.toString();
  }
}
