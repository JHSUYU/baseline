package edu.uva.liftlab.mallory.hbase.clientowner;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.io.InputStream;
import java.lang.instrument.ClassFileTransformer;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.Map;
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
import org.objectweb.asm.util.CheckClassAdapter;

/** Offline HBase 2.6.6 bytecode and actor-scope checks; never starts a MiniCluster. */
public class ClientRpcOwnerTransformerTest {
  private static final String CLIENT = "org/apache/hadoop/hbase/ipc/AbstractRpcClient";
  private static final String UTILITY = "org/apache/hadoop/hbase/HBaseTestingUtility";

  @Test public void testConnectionRegistersExactRpcClientAfterBaseHook() throws Exception {
    ClassNode node = transformed(UTILITY, "hbase-server-2.6.6-tests.jar");
    MethodNode method = find(node, "getConnection");
    int baseAt = -1;
    int ownerAt = -1;
    int returnAt = -1;
    int at = 0;
    for (AbstractInsnNode insn : method.instructions.toArray()) {
      if (insn instanceof MethodInsnNode) {
        MethodInsnNode call = (MethodInsnNode) insn;
        if ("registerClient".equals(call.name)) baseAt = at;
        if ("registerTestConnection".equals(call.name)) ownerAt = at;
      }
      if (insn.getOpcode() == Opcodes.ARETURN) returnAt = at;
      at++;
    }
    assertTrue("base and owner hooks must observe the same returned connection",
        baseAt >= 0 && ownerAt > baseAt && returnAt > ownerAt);
  }

  @Test public void callCreationAndBlockingClaimRemainInsideClientScope() throws Exception {
    ClassNode node = transformed(CLIENT, "hbase-client-2.6.6.jar");
    Map<String, Boolean> seen = new HashMap<String, Boolean>();
    for (MethodNode method : node.methods) {
      if (!"callMethod".equals(method.name) && !"callBlockingMethod".equals(method.name))
        continue;
      int ownerEnter = -1;
      int callCreate = -1;
      int baseEnter = -1;
      int baseClose = -1;
      int firstOwnerClose = -1;
      int ownerCloses = 0;
      int returns = 0;
      int at = 0;
      for (AbstractInsnNode insn : method.instructions.toArray()) {
        if (insn instanceof MethodInsnNode) {
          MethodInsnNode call = (MethodInsnNode) insn;
          if ("enterKnownRpcClient".equals(call.name)) ownerEnter = at;
          if ("<init>".equals(call.name)
              && "org/apache/hadoop/hbase/ipc/Call".equals(call.owner)) callCreate = at;
          if ("enterBlockingCall".equals(call.name)) baseEnter = at;
          if ("edu/uva/liftlab/mallory/hbase/HBaseHooks$Scope".equals(call.owner)
              && "close".equals(call.name) && baseClose < 0) baseClose = at;
          if ("closeScope".equals(call.name)) {
            if (firstOwnerClose < 0) firstOwnerClose = at;
            ownerCloses++;
          }
        }
        if (insn.getOpcode() == Opcodes.ARETURN) returns++;
        at++;
      }
      assertTrue("registered actor must enter at method entry", ownerEnter >= 0);
      assertEquals("normal and exceptional exit restore actor", returns + 1, ownerCloses);
      boolean hasFinally = false;
      for (TryCatchBlockNode block : method.tryCatchBlocks)
        if (block.type == null) hasFinally = true;
      assertTrue("exceptional exit must restore actor", hasFinally);
      if ("callMethod".equals(method.name))
        assertTrue("Call constructor must inherit client actor",
            callCreate > ownerEnter && firstOwnerClose > callCreate);
      else
        assertTrue("base completion claim must precede owner restoration",
            baseEnter > ownerEnter && baseClose > baseEnter && firstOwnerClose > baseClose);
      seen.put(method.name, Boolean.TRUE);
    }
    assertEquals(2, seen.size());
  }

  @Test public void unregisteredRpcClientPreservesCurrentActor() {
    try (Probe.NodeScope prior = Probe.withNode("master0", 0)) {
      assertEquals(null, ClientRpcOwnerHooks.enterKnownRpcClient(new Object()));
      assertEquals("master0", Probe.currentNode());
      ClientRpcOwnerHooks.closeScope(null);
      assertEquals("master0", Probe.currentNode());
    }
  }

  private static ClassNode transformed(String name, String jarName) throws Exception {
    String distribution = System.getProperty("hbase.dist",
        "/users/ZhenyuLi/.baseline-deps/hbase-2.6.6");
    byte[] original;
    try (ZipFile jar = new ZipFile(Paths.get(distribution, "lib", jarName).toFile());
         InputStream in = jar.getInputStream(jar.getEntry(name + ".class"))) {
      java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
      byte[] bytes = new byte[8192];
      for (int count; (count = in.read(bytes)) >= 0;) out.write(bytes, 0, count);
      original = out.toByteArray();
    }
    Path adapterJar = Paths.get(System.getProperty("hbase.adapter.jar",
        "/users/ZhenyuLi/baseline/Mallory/adapters/hbase/overlays/"
        + "hbase28-constructor-actor-v1/runtime/adapter.jar"));
    URL[] urls = {
        Paths.get(distribution, "lib", "hbase-client-2.6.6.jar").toUri().toURL(),
        Paths.get(distribution, "lib", "hbase-server-2.6.6-tests.jar").toUri().toURL(),
        adapterJar.toUri().toURL()};
    try (URLClassLoader loader =
        new URLClassLoader(urls, ClientRpcOwnerTransformerTest.class.getClassLoader())) {
      Class<?> type = Class.forName(
          "edu.uva.liftlab.mallory.hbase.HBaseAdapterTransformer", true, loader);
      ClassFileTransformer base = (ClassFileTransformer) type.newInstance();
      byte[] afterBase = base.transform(loader, name, null, null, original);
      assertNotNull("base HBase adapter must transform " + name, afterBase);
      byte[] afterOverlay =
          new ClientRpcOwnerTransformer().transform(loader, name, null, null, afterBase);
      assertNotNull("client owner overlay must transform " + name, afterOverlay);
      new ClassReader(afterOverlay).accept(new CheckClassAdapter(new ClassWriter(0), true),
          ClassReader.EXPAND_FRAMES);
      ClassNode node = new ClassNode();
      new ClassReader(afterOverlay).accept(node, ClassReader.EXPAND_FRAMES);
      return node;
    }
  }

  private static MethodNode find(ClassNode node, String name) {
    for (MethodNode method : node.methods) if (name.equals(method.name)) return method;
    throw new AssertionError("missing method " + name);
  }
}
