package edu.uva.liftlab.mallory.hbase.zkmonitor;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.lang.reflect.Method;
import java.net.URLClassLoader;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.Map;
import java.util.jar.JarEntry;
import java.util.jar.JarFile;
import org.junit.Test;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;

public class TrackerMonitorTransformerTest {
  private static final String NAME = "org.apache.hadoop.hbase.zookeeper.ZKNodeTracker";
  private static final String INTERNAL = NAME.replace('.', '/');

  @Test public void exactMonitorCallsitesAreRewrittenAndVerifierAcceptsTheClass()
      throws Exception {
    byte[] input;
    try (InputStream stream = getClass().getClassLoader().getResourceAsStream(INTERNAL + ".class")) {
      assertNotNull(stream);
      ByteArrayOutputStream output = new ByteArrayOutputStream();
      byte[] buffer = new byte[8192];
      for (int count; (count = stream.read(buffer)) >= 0; ) output.write(buffer, 0, count);
      input = output.toByteArray();
    }
    byte[] transformed = new TrackerMonitorTransformer().transform(getClass().getClassLoader(),
        INTERNAL, null, null, input);
    assertNotNull(transformed);
    ClassNode owner = new ClassNode();
    new ClassReader(transformed).accept(owner, 0);
    Map<String, Integer> calls = new HashMap<String, Integer>();
    for (MethodNode method : owner.methods) {
      for (AbstractInsnNode instruction : method.instructions.toArray()) {
        if (!(instruction instanceof MethodInsnNode)) continue;
        MethodInsnNode call = (MethodInsnNode) instruction;
        if (call.owner.endsWith("/TrackerMonitorHooks"))
          calls.put(call.name, calls.containsKey(call.name) ? calls.get(call.name) + 1 : 1);
      }
    }
    assertEquals(Integer.valueOf(1), calls.get("beforeWait"));
    assertEquals(Integer.valueOf(1), calls.get("afterWait"));
    assertEquals(Integer.valueOf(3), calls.get("publish"));
    assertEquals(Integer.valueOf(3), calls.get("enterCallback"));

    ClassLoader loader = new ClassLoader(getClass().getClassLoader()) {
      @Override protected Class<?> loadClass(String name, boolean resolve)
          throws ClassNotFoundException {
        if (!NAME.equals(name)) return super.loadClass(name, resolve);
        synchronized (getClassLoadingLock(name)) {
          Class<?> type = findLoadedClass(name);
          if (type == null) type = defineClass(name, transformed, 0, transformed.length);
          if (resolve) resolveClass(type);
          return type;
        }
      }
    };
    Class<?> type = loader.loadClass(NAME);
    Object tracker = type.getConstructor().newInstance();
    Method wait = type.getMethod("blockUntilAvailable", long.class, boolean.class);
    assertNull(wait.invoke(tracker, 1L, false));
    type.getMethod("nodeDeleted", String.class).invoke(tracker, "/test");
    type.getMethod("nodeCreated", String.class).invoke(tracker, "/test");
    assertNotNull(wait.invoke(tracker, 1L, false));
    type.getMethod("stop").invoke(tracker);
  }

  @Test public void realHBaseClassHasTheSameFourInstrumentableMethods() throws Exception {
    String jarPath = System.getProperty("mallory.hbase.zookeeper.jar");
    if (jarPath == null) return;
    byte[] input;
    try (JarFile jar = new JarFile(jarPath)) {
      JarEntry entry = jar.getJarEntry(INTERNAL + ".class");
      assertNotNull(entry);
      try (InputStream stream = jar.getInputStream(entry)) {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        for (int count; (count = stream.read(buffer)) >= 0; ) output.write(buffer, 0, count);
        input = output.toByteArray();
      }
    }
    try (URLClassLoader loader = new URLClassLoader(
        new java.net.URL[] {Paths.get(jarPath).toUri().toURL()}, getClass().getClassLoader())) {
      byte[] transformed = new TrackerMonitorTransformer().transform(loader, INTERNAL,
          null, null, input);
      assertNotNull(transformed);
      ClassNode owner = new ClassNode();
      new ClassReader(transformed).accept(owner, 0);
      int before = 0, after = 0, publish = 0;
      for (MethodNode method : owner.methods) {
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          if (!(instruction instanceof MethodInsnNode)) continue;
          MethodInsnNode call = (MethodInsnNode) instruction;
          if (!call.owner.endsWith("/TrackerMonitorHooks")) continue;
          if ("beforeWait".equals(call.name)) before++;
          if ("afterWait".equals(call.name)) after++;
          if ("publish".equals(call.name)) publish++;
        }
      }
      assertEquals(1, before);
      assertEquals(1, after);
      assertEquals(3, publish);
    }
  }
}
