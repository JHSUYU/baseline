package edu.uva.liftlab.mallory.hbase.requestqualified;

import java.io.InputStream;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.lang.instrument.ClassFileTransformer;
import java.security.MessageDigest;
import java.util.jar.JarFile;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.VarInsnNode;
import org.objectweb.asm.util.CheckClassAdapter;

/** Plain offline artifact check; it starts no HBase cluster or selected JUnit. */
public final class OfflinePreflight {
  private static final String OWNER = "org/apache/hadoop/hbase/ipc/RpcServer";
  private static final String HOOKS =
      "edu/uva/liftlab/mallory/hbase/requestqualified/RequestQualifiedRpcHooks";

  private OfflinePreflight() { }

  public static void main(String[] args) throws Exception {
    if (args.length != 1) throw new IllegalArgumentException("HBase server jar required");
    byte[] raw;
    try (JarFile jar = new JarFile(args[0])) {
      try (InputStream input = jar.getInputStream(jar.getJarEntry(OWNER + ".class"))) {
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int n;
        while ((n = input.read(buffer)) >= 0) out.write(buffer, 0, n);
        raw = out.toByteArray();
      }
    }
    ClassFileTransformer base = (ClassFileTransformer) Class.forName(
        "edu.uva.liftlab.mallory.hbase.HBaseAdapterTransformer").newInstance();
    ClassLoader loader = OfflinePreflight.class.getClassLoader();
    byte[] scoped = base.transform(loader, OWNER, null, null, raw);
    if (scoped == null) throw new IllegalStateException("Base RPC scope was not installed");
    byte[] qualified = new RequestQualifiedRpcTransformer().transform(
        loader, OWNER, null, null, scoped);
    if (qualified == null) throw new IllegalStateException("Request-qualified probe missing");
    StringWriter verifier = new StringWriter();
    CheckClassAdapter.verify(new ClassReader(qualified), loader, false,
        new PrintWriter(verifier));
    if (verifier.getBuffer().length() != 0)
      throw new IllegalStateException("ASM verification failed: " + verifier);

    ClassNode owner = new ClassNode();
    new ClassReader(qualified).accept(owner, ClassReader.EXPAND_FRAMES);
    int dispatches = 0;
    int hooks = 0;
    for (MethodNode method : owner.methods) {
      if (!"call".equals(method.name) || !method.desc.startsWith(
          "(Lorg/apache/hadoop/hbase/ipc/RpcCall;")) continue;
      for (AbstractInsnNode instruction : method.instructions.toArray()) {
        if (!(instruction instanceof MethodInsnNode)) continue;
        MethodInsnNode call = (MethodInsnNode) instruction;
        if ("callBlockingMethod".equals(call.name)) {
          dispatches++;
          AbstractInsnNode before = instruction.getPrevious();
          if (!(before instanceof MethodInsnNode)
              || !HOOKS.equals(((MethodInsnNode) before).owner)
              || !"beforeDispatch".equals(((MethodInsnNode) before).name)
              || !(before.getPrevious() instanceof VarInsnNode)
              || ((VarInsnNode) before.getPrevious()).var != 1)
            throw new IllegalStateException("Probe does not precede service dispatch");
        }
        if (HOOKS.equals(call.owner) && "beforeDispatch".equals(call.name)) hooks++;
      }
    }
    if (dispatches != 1 || hooks != 1)
      throw new IllegalStateException("Expected one dispatch and one qualified hook");

    String caseId = System.getProperty("mallory.hbase.rpc.door.case", "");
    String port = "HBASE-02".equals(caseId) ? "hbase.pb.ClientService.Get"
        : "hbase.pb.MasterService.UnassignRegion";
    String node = "HBASE-02".equals(caseId) ? "rs0" : "master0";
    String site = RequestQualifiedRpcHooks.selectedSiteFor(new FakeCall(port), node);
    if (site == null || !site.endsWith(":rpc:" + port))
      throw new IllegalStateException("Correct request was not selected");
    if (RequestQualifiedRpcHooks.selectedSiteFor(new FakeCall(port), "wrong-node") != null
        || RequestQualifiedRpcHooks.selectedSiteFor(new FakeCall("hbase.pb.Other.Get"), node) != null
        || RequestQualifiedRpcHooks.selectedSiteFor(new Object(), node) != null)
      throw new IllegalStateException("A mismatched request was selected");
    System.out.println("OFFLINE_SCOPE_OK case=" + caseId + " raw_sha256=" + sha(raw)
        + " base_sha256=" + sha(scoped) + " overlay_sha256=" + sha(qualified)
        + " site=" + site);
  }

  private static String sha(byte[] input) throws Exception {
    byte[] digest = MessageDigest.getInstance("SHA-256").digest(input);
    StringBuilder out = new StringBuilder();
    for (byte b : digest) out.append(String.format("%02x", b & 255));
    return out.toString();
  }

  public static final class FakeCall {
    private final FakeDescriptor descriptor;
    public FakeCall(String port) { descriptor = new FakeDescriptor(port); }
    public FakeDescriptor getMethod() { return descriptor; }
  }

  public static final class FakeDescriptor {
    private final String port;
    public FakeDescriptor(String port) { this.port = port; }
    public String getFullName() { return port; }
  }
}
