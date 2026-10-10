package edu.uva.liftlab.mallory.solr;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import edu.uva.liftlab.mallory.instrumentation.AgentConfig;
import edu.uva.liftlab.mallory.instrumentation.MalloryTransformer;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Stream;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.jar.JarFile;
import org.junit.Test;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.util.CheckClassAdapter;

public final class Solr37TargetTransformTest {
  @Test
  public void coverageThenOperandRewriteKeepsVerifiableFrames() throws Exception {
    String owner = "org/apache/solr/update/processor/DistributedZkUpdateProcessor";
    byte[] original;
    try (JarFile source = new JarFile(
        "/users/ZhenyuLi/.baseline-deps/solr-8.11.4/dist/solr-core-8.11.4.jar")) {
      try (java.io.InputStream input = source.getInputStream(source.getJarEntry(owner + ".class"))) {
        java.io.ByteArrayOutputStream buffer = new java.io.ByteArrayOutputStream();
        byte[] block = new byte[8192];
        for (int n; (n = input.read(block)) >= 0;) buffer.write(block, 0, n);
        original = buffer.toByteArray();
      }
    }
    AgentConfig config = new AgentConfig();
    config.includes.add(owner);
    AgentConfig.SiteRule check = new AgentConfig.SiteRule();
    check.clazz = owner.replace('/', '.');
    check.method = "doDefensiveChecks";
    check.descriptor = "(Lorg/apache/solr/update/processor/DistributedUpdateProcessor$DistribPhase;)V";
    check.line = 994;
    config.targets.add(check);
    AgentConfig.SiteRule throwingCheck = new AgentConfig.SiteRule();
    throwingCheck.clazz = check.clazz;
    throwingCheck.method = check.method;
    throwingCheck.descriptor = check.descriptor;
    throwingCheck.line = 995;
    config.targets.add(throwingCheck);
    AgentConfig.SiteRule region = new AgentConfig.SiteRule();
    region.clazz = check.clazz;
    region.method = check.method;
    region.descriptor = check.descriptor;
    config.regions.add(region);
    config.autoIoDoors = true;
    byte[] covered = new MalloryTransformer(config).transform(null, owner, null, null, original);
    assertNotNull(covered);
    byte[] changed = new SolrTransformer().transform(null, owner, null, null, covered);
    assertNotNull(changed);
    List<URL> jars = new ArrayList<URL>();
    Path distribution = Paths.get("/users/ZhenyuLi/.baseline-deps/solr-8.11.4");
    try (Stream<Path> paths = Files.walk(distribution)) {
      paths.filter(path -> path.toString().endsWith(".jar")).forEach(path -> {
        try { jars.add(path.toUri().toURL()); }
        catch (java.net.MalformedURLException failure) { throw new IllegalStateException(failure); }
      });
    }
    StringWriter diagnostics = new StringWriter();
    final byte[] finalBytes = changed;
    final String binaryName = owner.replace('/', '.');
    try (URLClassLoader verifier = new URLClassLoader(jars.toArray(new URL[0]),
        getClass().getClassLoader()) {
          @Override protected synchronized Class<?> loadClass(String name, boolean resolve)
              throws ClassNotFoundException {
            if (!binaryName.equals(name)) return super.loadClass(name, resolve);
            Class<?> loaded = findLoadedClass(name);
            if (loaded == null) loaded = defineClass(name, finalBytes, 0, finalBytes.length);
            if (resolve) resolveClass(loaded);
            return loaded;
          }
        }) {
      CheckClassAdapter.verify(new ClassReader(changed), verifier, false,
          new PrintWriter(diagnostics));
      Class.forName(binaryName, false, verifier).getDeclaredMethods();
    }
    assertTrue(diagnostics.toString(), diagnostics.toString().trim().isEmpty());
  }

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
