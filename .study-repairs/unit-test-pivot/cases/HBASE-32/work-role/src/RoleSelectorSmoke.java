import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.lang.instrument.ClassFileTransformer;
import java.lang.reflect.Constructor;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Offline identity and ASM callsite smoke; never starts a MiniHBaseCluster. */
public final class RoleSelectorSmoke {
  private static final String STABLE = "dGVzdExvdHNPZlJlZ2lvblJlcGxpMix1t-o";
  private static final String F1 = "MASTER_OPENED_RPC~" + STABLE
    + "~replica-2~meta-host";
  private static final String F2 = "RPC_FLUSH_REGION~" + STABLE
    + "~replica-2~actor-selected~target-1~rpc-1~FlushRegionCallable.call:81";

  private static void require(boolean value, String explanation) {
    if (!value) throw new AssertionError(explanation);
  }

  private static byte[] classBytes(String className) throws Exception {
    try (InputStream stream = RoleSelectorSmoke.class.getClassLoader()
           .getResourceAsStream(className + ".class")) {
      require(stream != null, "Missing release class " + className);
      ByteArrayOutputStream out = new ByteArrayOutputStream();
      byte[] block = new byte[8192];
      for (int n; (n = stream.read(block)) != -1;) out.write(block, 0, n);
      return out.toByteArray();
    }
  }

  private static boolean woven(String transformerClass, String className,
                               String methodName, String calleeClass,
                               String calleeName) throws Exception {
    Constructor<?> constructor = Class.forName(transformerClass).getDeclaredConstructor();
    constructor.setAccessible(true);
    ClassFileTransformer transformer = (ClassFileTransformer) constructor.newInstance();
    byte[] changed = transformer.transform(null, className, null, null, classBytes(className));
    require(changed != null, "No woven bytes for " + className);
    final boolean[] found = {false};
    new ClassReader(changed).accept(new ClassVisitor(Opcodes.ASM9) {
      @Override
      public MethodVisitor visitMethod(int access, String method, String descriptor,
                                       String signature, String[] exceptions) {
        MethodVisitor outer = super.visitMethod(access, method, descriptor,
                                                signature, exceptions);
        if (!method.equals(methodName)) return outer;
        return new MethodVisitor(Opcodes.ASM9, outer) {
          @Override
          public void visitMethodInsn(int opcode, String owner, String name,
                                      String desc, boolean itf) {
            if (opcode == Opcodes.INVOKESTATIC && owner.equals(calleeClass)
                && name.equals(calleeName)) found[0] = true;
            super.visitMethodInsn(opcode, owner, name, desc, itf);
          }
        };
      }
    }, 0);
    return found[0];
  }

  public static void main(String[] args) throws Exception {
    System.setProperty("hbase32.upstream.fault.plan", F1 + "~DO_NOT_RETRY_IOEXCEPTION");
    System.setProperty("hbase32.fault.plan", F2 + "~DO_NOT_RETRY_IOEXCEPTION");
    HBase32RoleUpstreamAgent.metaLocationCommitted("meta-A", 0, "OPEN");
    require(HBase32RoleUpstreamAgent.roleMatchCandidate("meta-A", F1), "meta host match");
    require(!HBase32RoleUpstreamAgent.roleMatchCandidate("other-B", F1), "exclude other RS");
    HBase32RoleUpstreamAgent.selectActor("raw-primary-A", "raw-secondary-A", 2, "meta-A");
    require(HBase32RoleUpstreamAgent.selectedMatches("raw-primary-A", "raw-secondary-A", 2),
            "same actor");
    require(!HBase32RoleUpstreamAgent.selectedMatches("raw-primary-B", "raw-secondary-A", 2),
            "different primary");
    require(!HBase32RoleUpstreamAgent.selectedMatches("raw-primary-A", "raw-secondary-B", 2),
            "different secondary");
    require(!HBase32RoleUpstreamAgent.selectedMatches("raw-primary-A", "raw-secondary-A", 1),
            "different replica");
    require(HBase32RoleBaseAgent.rpcSelector(STABLE, "2", true, 1, 1).equals(F2),
            "exact selected-actor RPC selector");
    require(!HBase32RoleBaseAgent.rpcSelector(STABLE, "2", false, 1, 1).equals(F2),
            "exclude different actor RPC");
    require(HBase32RoleBaseAgent.plannedRpcMatches(F2), "selected RPC plan match");
    require(!HBase32RoleBaseAgent.plannedRpcMatches(
      HBase32RoleBaseAgent.rpcSelector(STABLE, "2", false, 1, 1)),
      "unselected RPC must not match fault plan");
    HBase32RoleUpstreamAgent.metaLocationCommitted("meta-A", 0, "CLOSING");
    require(!HBase32RoleUpstreamAgent.roleMatchCandidate("meta-A", F1), "clear closed host");
    require(HBase32RoleUpstreamAgent.selectedMatches("raw-primary-A", "raw-secondary-A", 2),
            "retain selected actor after location change");
    HBase32RoleUpstreamAgent.metaLocationCommitted("meta-B", 0, "OPEN");
    require(HBase32RoleUpstreamAgent.roleMatchCandidate("meta-B", F1), "updated meta host");

    require(woven("HBase32RoleUpstreamAgent$Probes",
      "org/apache/hadoop/hbase/zookeeper/MetaTableLocator", "setMetaLocation",
      "HBase32RoleUpstreamAgent", "metaLocationCommitted"), "meta write-success hook");
    require(woven("HBase32RoleUpstreamAgent$Probes",
      "org/apache/hadoop/hbase/regionserver/HRegionServer", "reportRegionStateTransition",
      "HBase32RoleUpstreamAgent", "beforeMasterReport"), "master report hook");
    require(woven("HBase32RoleBaseAgent$ProbeTransformer",
      "org/apache/hadoop/hbase/client/FlushRegionCallable", "call",
      "HBase32RoleBaseAgent", "beforeFlushRpc"), "client RPC hook");
    System.out.println("ROLE_SMOKE PASS meta_success_hook=true master_report_hook=true"
      + " client_rpc_hook=true actor_region_bound=true");
  }
}
