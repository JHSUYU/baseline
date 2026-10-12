package edu.uva.liftlab.mallory.hbase.hbase28;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import java.io.InputStream;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import org.junit.Test;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.TryCatchBlockNode;
import org.objectweb.asm.tree.VarInsnNode;
import org.objectweb.asm.util.CheckClassAdapter;

/** Offline bytecode check against the pinned HBase 2.6.6 distribution class. */
public class ConstructorActorTransformerTest {
  private static final String OWNER = "org/apache/hadoop/hbase/util/JVMClusterUtil";

  @Test public void scopesBothRealHBaseFactoriesBeforeReflectiveConstruction() throws Exception {
    Path jar = Paths.get(System.getProperty("hbase.server.jar",
        "/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-server-2.6.6.jar"));
    byte[] original;
    try (ZipFile zip = new ZipFile(jar.toFile())) {
      ZipEntry entry = zip.getEntry(OWNER + ".class");
      assertNotNull(entry);
      try (InputStream in = zip.getInputStream(entry)) {
        java.io.ByteArrayOutputStream bytes = new java.io.ByteArrayOutputStream();
        byte[] chunk = new byte[8192];
        for (int n; (n = in.read(chunk)) >= 0;) bytes.write(chunk, 0, n);
        original = bytes.toByteArray();
      }
    }

    byte[] transformed = new ConstructorActorTransformer().transform(
        getClass().getClassLoader(), OWNER, null, null, original);
    assertNotNull("exact 2.6.6 factories must transform", transformed);
    new ClassReader(transformed).accept(new CheckClassAdapter(new ClassWriter(0), true),
        ClassReader.EXPAND_FRAMES);

    ClassNode owner = new ClassNode();
    new ClassReader(transformed).accept(owner, ClassReader.EXPAND_FRAMES);
    Map<String, String> expected = new HashMap<String, String>();
    expected.put("createRegionServerThread", "enterRegionServer");
    expected.put("createMasterThread", "enterMaster");
    for (MethodNode method : owner.methods) {
      String hook = expected.remove(method.name);
      if (hook == null) continue;
      int hookAt = -1;
      int constructorAt = -1;
      int returns = 0;
      int closes = 0;
      int cursor = 0;
      for (AbstractInsnNode insn : method.instructions.toArray()) {
        if (insn.getOpcode() == Opcodes.ARETURN) returns++;
        if (insn instanceof MethodInsnNode) {
          MethodInsnNode call = (MethodInsnNode) insn;
          if (call.owner.endsWith("ConstructorActorHooks") && hook.equals(call.name)) {
            hookAt = cursor;
            AbstractInsnNode previous = insn.getPrevious();
            assertTrue("scope must use factory index parameter",
                previous instanceof VarInsnNode && previous.getOpcode() == Opcodes.ILOAD
                    && ((VarInsnNode) previous).var == 2);
          }
          if ("java/lang/reflect/Constructor".equals(call.owner)
              && "newInstance".equals(call.name)) constructorAt = cursor;
          if ("edu/uva/liftlab/mallory/instrumentation/Probe$NodeScope".equals(call.owner)
              && "close".equals(call.name)) closes++;
        }
        cursor++;
      }
      assertTrue("scope must begin before reflective server constructor", hookAt >= 0
          && constructorAt > hookAt);
      assertEquals("every normal return and exceptional exit closes scope", returns + 1, closes);
      boolean catchAll = false;
      for (TryCatchBlockNode block : method.tryCatchBlocks)
        if (block.type == null) catchAll = true;
      assertTrue("exceptional exit needs a finally handler", catchAll);
    }
    assertTrue("both factories found", expected.isEmpty());
  }
}
