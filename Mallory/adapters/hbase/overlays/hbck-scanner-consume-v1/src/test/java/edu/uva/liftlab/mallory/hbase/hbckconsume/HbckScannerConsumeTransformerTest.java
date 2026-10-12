package edu.uva.liftlab.mallory.hbase.hbckconsume;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.lang.instrument.ClassFileTransformer;
import java.net.URL;
import java.net.URLClassLoader;
import java.util.jar.JarFile;
import java.util.zip.ZipEntry;
import org.junit.Test;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.InsnNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.VarInsnNode;

public class HbckScannerConsumeTransformerTest {
  private final HbckScannerConsumeTransformer transformer = new HbckScannerConsumeTransformer();

  @Test public void futureGetBindsOnlySuccessfulReturnValue() {
    String owner = "org/apache/hadoop/hbase/client/ResultBoundedCompletionService$QueueingFuture";
    ClassNode source = bare(owner);
    MethodNode get = new MethodNode(Opcodes.ACC_PUBLIC, "get", "()Ljava/lang/Object;", null, null);
    get.instructions.add(new InsnNode(Opcodes.ACONST_NULL));
    get.instructions.add(new InsnNode(Opcodes.ARETURN));
    source.methods.add(get);
    ClassNode result = transform(owner, source);
    assertEquals(1, calls(result.methods.get(0), "futureValueReturned"));
    assertEquals(0, result.methods.get(0).tryCatchBlocks.size());
  }

  @Test public void onlyExactScanMetaVisitorCallIsScopedIncludingThrow() {
    String owner = "org/apache/hadoop/hbase/MetaTableAccessor";
    ClassNode source = bare(owner);
    MethodNode scan = new MethodNode(Opcodes.ACC_STATIC, "scanMeta",
        "(Lorg/apache/hadoop/hbase/MetaTableAccessor$Visitor;"
        + "Lorg/apache/hadoop/hbase/client/Result;)V", null, null);
    scan.instructions.add(new VarInsnNode(Opcodes.ALOAD, 0));
    scan.instructions.add(new VarInsnNode(Opcodes.ALOAD, 1));
    scan.instructions.add(new MethodInsnNode(Opcodes.INVOKEINTERFACE,
        "org/apache/hadoop/hbase/MetaTableAccessor$Visitor", "visit",
        "(Lorg/apache/hadoop/hbase/client/Result;)Z", true));
    scan.instructions.add(new InsnNode(Opcodes.POP));
    scan.instructions.add(new InsnNode(Opcodes.RETURN));
    source.methods.add(scan);
    ClassNode result = transform(owner, source);
    assertEquals(1, calls(result.methods.get(0), "enterConsumedResult"));
    assertEquals(2, calls(result.methods.get(0), "leaveConsumedResult"));
    assertEquals(1, result.methods.get(0).tryCatchBlocks.size());
    assertEquals(null, result.methods.get(0).tryCatchBlocks.get(0).type);
  }

  @Test public void unrelatedClassesAndMissingVisitorRemainUnmodified() {
    ClassNode unrelated = bare("unrelated/Scanner");
    assertNull(transformer.transform(null, unrelated.name, null, null, bytes(unrelated)));
    ClassNode meta = bare("org/apache/hadoop/hbase/MetaTableAccessor");
    MethodNode noVisit = new MethodNode(Opcodes.ACC_STATIC, "scanMeta", "()V", null, null);
    noVisit.instructions.add(new InsnNode(Opcodes.RETURN));
    meta.methods.add(noVisit);
    assertNull(transformer.transform(null, meta.name, null, null, bytes(meta)));
  }

  @Test public void pinnedHBaseClientBytecodeHasBothExactHooks() throws Exception {
    String jarPath = System.getProperty("hbaseClientJar");
    if (jarPath == null || jarPath.isEmpty()) return;
    try (JarFile jar = new JarFile(jarPath)) {
      String future = "org/apache/hadoop/hbase/client/ResultBoundedCompletionService$QueueingFuture";
      String meta = "org/apache/hadoop/hbase/MetaTableAccessor";
      ClassNode changedFuture = transformedJarClass(jar, future);
      ClassNode changedMeta = transformedJarClass(jar, meta);
      assertEquals(1, changedFuture.methods.stream().mapToInt(m -> calls(m,
          "futureValueReturned")).sum());
      assertEquals(1, changedMeta.methods.stream().mapToInt(m -> calls(m,
          "enterConsumedResult")).sum());
      assertEquals(2, changedMeta.methods.stream().mapToInt(m -> calls(m,
          "leaveConsumedResult")).sum());
    }
  }

  @Test public void composesAfterExistingHBaseAdapterOnPinnedFuture() throws Exception {
    String jarPath = System.getProperty("hbaseClientJar");
    String adapterPath = System.getProperty("hbaseAdapterJar");
    if (jarPath == null || adapterPath == null) return;
    String owner = "org/apache/hadoop/hbase/client/ResultBoundedCompletionService$QueueingFuture";
    try (JarFile jar = new JarFile(jarPath);
        URLClassLoader adapterLoader = new URLClassLoader(
            new URL[] { new java.io.File(adapterPath).toURI().toURL() },
            getClass().getClassLoader())) {
      ZipEntry entry = jar.getEntry(owner + ".class");
      assertNotNull(entry);
      ByteArrayOutputStream out = new ByteArrayOutputStream();
      try (InputStream in = jar.getInputStream(entry)) {
        byte[] chunk = new byte[8192];
        for (int count; (count = in.read(chunk)) != -1;) out.write(chunk, 0, count);
      }
      ClassFileTransformer existing = (ClassFileTransformer) Class.forName(
          "edu.uva.liftlab.mallory.hbase.HBaseAdapterTransformer", true, adapterLoader)
          .newInstance();
      byte[] base = existing.transform(adapterLoader, owner, null, null, out.toByteArray());
      assertNotNull(base);
      byte[] combined = transformer.transform(adapterLoader, owner, null, null, base);
      assertNotNull(combined);
      ClassNode parsed = new ClassNode();
      new ClassReader(combined).accept(parsed, ClassReader.EXPAND_FRAMES);
      assertEquals(1, parsed.methods.stream().mapToInt(m -> calls(m,
          "futureValueReturned")).sum());
      assertEquals(3, parsed.methods.stream().mapToInt(m -> calls(m,
          "scannerTaskCompleted")).sum());
    }
  }

  private ClassNode transformedJarClass(JarFile jar, String owner) throws Exception {
    ZipEntry entry = jar.getEntry(owner + ".class");
    assertNotNull(entry);
    ByteArrayOutputStream out = new ByteArrayOutputStream();
    try (InputStream in = jar.getInputStream(entry)) {
      byte[] chunk = new byte[8192];
      for (int count; (count = in.read(chunk)) != -1;) out.write(chunk, 0, count);
    }
    byte[] changed = transformer.transform(null, owner, null, null, out.toByteArray());
    assertNotNull(changed);
    ClassNode result = new ClassNode();
    new ClassReader(changed).accept(result, ClassReader.EXPAND_FRAMES);
    return result;
  }

  private ClassNode transform(String owner, ClassNode source) {
    byte[] changed = transformer.transform(null, owner, null, null, bytes(source));
    assertNotNull(changed);
    ClassNode result = new ClassNode();
    new ClassReader(changed).accept(result, ClassReader.EXPAND_FRAMES);
    assertTrue(result.methods.size() > 0);
    return result;
  }

  private static ClassNode bare(String owner) {
    ClassNode node = new ClassNode();
    node.version = Opcodes.V1_8;
    node.access = Opcodes.ACC_PUBLIC;
    node.name = owner;
    node.superName = "java/lang/Object";
    return node;
  }

  private static byte[] bytes(ClassNode node) {
    ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
    node.accept(writer);
    return writer.toByteArray();
  }

  private static int calls(MethodNode method, String name) {
    int count = 0;
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (instruction instanceof MethodInsnNode && name.equals(((MethodInsnNode) instruction).name))
        count++;
    }
    return count;
  }
}
