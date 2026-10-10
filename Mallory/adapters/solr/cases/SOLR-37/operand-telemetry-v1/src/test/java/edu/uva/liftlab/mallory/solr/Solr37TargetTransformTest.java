package edu.uva.liftlab.mallory.solr;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;

import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.jar.JarFile;
import org.junit.Test;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

public final class Solr37TargetTransformTest {
  @Test
  public void exactGuardHasOneOperandHook() throws Exception {
    Path jar = Paths.get("/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist/solr-core-8.11.4.jar");
    String owner = "org/apache/solr/update/processor/DistributedZkUpdateProcessor";
    byte[] original;
    try (JarFile source = new JarFile(jar.toFile())) {
      try (java.io.InputStream input = source.getInputStream(source.getJarEntry(owner + ".class"))) {
        java.io.ByteArrayOutputStream buffer = new java.io.ByteArrayOutputStream();
        byte[] block = new byte[8192];
        for (int n; (n = input.read(block)) >= 0;) buffer.write(block, 0, n);
        original = buffer.toByteArray();
      }
    }
    byte[] changed = new SolrTransformer().transform(null, owner, null, null, original);
    assertNotNull(changed);
    AtomicInteger calls = new AtomicInteger();
    new ClassReader(changed).accept(new ClassVisitor(Opcodes.ASM9) {
      @Override public MethodVisitor visitMethod(int access, String name, String descriptor,
          String signature, String[] exceptions) {
        if (!"doDefensiveChecks".equals(name)) return null;
        return new MethodVisitor(Opcodes.ASM9) {
          @Override public void visitMethodInsn(int opcode, String target, String method,
              String callDescriptor, boolean isInterface) {
            if ("edu/uva/liftlab/mallory/solr/SolrHooks".equals(target)
                && "solr37TargetOperand".equals(method)) calls.incrementAndGet();
          }
        };
      }
    }, 0);
    assertEquals(1, calls.get());
  }

  @Test
  public void watcherPublishesOnlyAfterConstructStateCall() throws Exception {
    Path jar = Paths.get("/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist/solr-solrj-8.11.4.jar");
    String owner = "org/apache/solr/common/cloud/ZkStateReader$StateWatcher";
    byte[] original;
    try (JarFile source = new JarFile(jar.toFile())) {
      try (java.io.InputStream input = source.getInputStream(source.getJarEntry(owner + ".class"))) {
        java.io.ByteArrayOutputStream buffer = new java.io.ByteArrayOutputStream();
        byte[] block = new byte[8192];
        for (int n; (n = input.read(block)) >= 0;) buffer.write(block, 0, n);
        original = buffer.toByteArray();
      }
    }
    byte[] changed = new SolrTransformer().transform(null, owner, null, null, original);
    assertNotNull(changed);
    AtomicInteger constructionCalls = new AtomicInteger();
    AtomicInteger publicationHooks = new AtomicInteger();
    new ClassReader(changed).accept(new ClassVisitor(Opcodes.ASM9) {
      @Override public MethodVisitor visitMethod(int access, String name, String descriptor,
          String signature, String[] exceptions) {
        if (!"refreshAndWatch".equals(name) || !"(Lorg/apache/zookeeper/Watcher$Event$EventType;)V".equals(descriptor))
          return null;
        return new MethodVisitor(Opcodes.ASM9) {
          @Override public void visitMethodInsn(int opcode, String target, String method,
              String callDescriptor, boolean isInterface) {
            if ("org/apache/solr/common/cloud/ZkStateReader".equals(target)
                && "access$700".equals(method)) constructionCalls.incrementAndGet();
            if ("edu/uva/liftlab/mallory/solr/SolrHooks".equals(target)
                && "solr37StatePublished".equals(method)) publicationHooks.incrementAndGet();
          }
        };
      }
    }, 0);
    assertEquals(1, constructionCalls.get());
    assertEquals(1, publicationHooks.get());
  }
}
