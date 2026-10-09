package edu.uva.liftlab.mallory.hbase.masterbinding;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;

import java.io.File;
import java.util.jar.JarFile;
import org.junit.Test;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;

public class MasterTrackerTransformerTest {
  private static final String OWNER = "org/apache/hadoop/hbase/master/ActiveMasterManager";
  private static final String HOOKS = "edu/uva/liftlab/mallory/hbase/masterbinding/MasterTrackerHooks";

  @Test public void transformsRealHBase266ManagerAtExactEntry() throws Exception {
    String jarPath = System.getProperty("mallory.hbase.server.jar");
    assertNotNull("Supply -Dmallory.hbase.server.jar", jarPath);
    try (JarFile jar = new JarFile(new File(jarPath))) {
      byte[] original = readAll(jar.getInputStream(jar.getJarEntry(OWNER + ".class")));
      MasterTrackerTransformer transformer = new MasterTrackerTransformer();
      assertNull(transformer.transform(null, "other/Class", null, null, original));
      byte[] rewritten = transformer.transform(null, OWNER, null, null, original);
      assertNotNull(rewritten);
      ClassNode owner = new ClassNode();
      new ClassReader(rewritten).accept(owner, 0);
      int hooks = 0;
      for (MethodNode method : owner.methods) {
        if (!"getActiveMasterInfoPort".equals(method.name) || !"()I".equals(method.desc))
          continue;
        AbstractInsnNode first = method.instructions.getFirst();
        while (first != null && first.getOpcode() < 0) first = first.getNext();
        assertEquals(Opcodes.ALOAD, first.getOpcode());
        AbstractInsnNode call = first.getNext();
        while (call != null && call.getOpcode() < 0) call = call.getNext();
        MethodInsnNode invoke = (MethodInsnNode) call;
        assertEquals(Opcodes.INVOKESTATIC, invoke.getOpcode());
        assertEquals(HOOKS, invoke.owner);
        assertEquals("bindWatcherFromManager", invoke.name);
        hooks++;
      }
      assertEquals(1, hooks);
    }
  }

  private static byte[] readAll(java.io.InputStream input) throws java.io.IOException {
    try (java.io.InputStream source = input;
         java.io.ByteArrayOutputStream output = new java.io.ByteArrayOutputStream()) {
      byte[] buffer = new byte[8192];
      int count;
      while ((count = source.read(buffer)) != -1) output.write(buffer, 0, count);
      return output.toByteArray();
    }
  }
}
