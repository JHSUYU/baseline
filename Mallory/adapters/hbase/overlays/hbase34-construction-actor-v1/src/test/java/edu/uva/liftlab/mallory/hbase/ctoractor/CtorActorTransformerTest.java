package edu.uva.liftlab.mallory.hbase.ctoractor;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.file.Paths;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import org.junit.Test;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.TryCatchBlockNode;

public class CtorActorTransformerTest {
  @Test public void exactIndexedFactoriesHaveBalancedScopes() throws Exception {
    String ownerName = "org/apache/hadoop/hbase/util/JVMClusterUtil";
    byte[] original;
    String jar = System.getProperty("hbase.server.jar",
        "/users/ZhenyuLi/.baseline-deps/hbase-2.6.6/lib/hbase-server-2.6.6.jar");
    try (ZipFile zip = new ZipFile(Paths.get(jar).toFile())) {
      ZipEntry entry = zip.getEntry(ownerName + ".class");
      assertNotNull(entry);
      try (InputStream in = zip.getInputStream(entry)) {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        byte[] chunk = new byte[8192];
        for (int n; (n = in.read(chunk)) >= 0;) bytes.write(chunk, 0, n);
        original = bytes.toByteArray();
      }
    }
    byte[] transformed = new CtorActorTransformer().transform(
        getClass().getClassLoader(), ownerName, null, null, original);
    assertNotNull(transformed);
    ClassNode owner = new ClassNode();
    new ClassReader(transformed).accept(owner, ClassReader.EXPAND_FRAMES);
    int matches = 0;
    for (MethodNode method : owner.methods) {
      if (!"createRegionServerThread".equals(method.name) &&
          !"createMasterThread".equals(method.name)) continue;
      matches++;
      int opens = 0, closes = 0, returns = 0;
      for (AbstractInsnNode insn : method.instructions.toArray()) {
        if (insn.getOpcode() >= 172 && insn.getOpcode() <= 177) returns++;
        if (!(insn instanceof MethodInsnNode)) continue;
        MethodInsnNode call = (MethodInsnNode) insn;
        if (call.owner.endsWith("CtorActorHooks") && call.name.startsWith("enter")) opens++;
        if (call.owner.endsWith("Probe$NodeScope") && "close".equals(call.name)) closes++;
      }
      assertEquals(1, opens);
      assertEquals(returns + 1, closes);
      boolean finallyHandler = false;
      for (TryCatchBlockNode block : method.tryCatchBlocks)
        if (block.type == null) finallyHandler = true;
      assertTrue(finallyHandler);
    }
    assertEquals(2, matches);
  }
}
