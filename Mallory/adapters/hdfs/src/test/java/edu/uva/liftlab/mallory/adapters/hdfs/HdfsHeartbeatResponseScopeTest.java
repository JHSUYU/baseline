package edu.uva.liftlab.mallory.adapters.hdfs;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import org.apache.hadoop.ipc.RemoteException;
import org.junit.Test;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;

public class HdfsHeartbeatResponseScopeTest {
  private static final String ACTOR = "org/apache/hadoop/hdfs/server/datanode/BPServiceActor";
  private static final String OFFER_SERVICE = "()V";

  private static final class FakeActor {
    private final Object dn;
    FakeActor(Object dn) { this.dn = dn; }
  }

  private static final class FakeClient {
    private final byte[] clientId = { 1, 2 };
    private final class Connection { }
  }

  private static final class FakeCall {
    private final int id;
    private final int retry = 0;
    private final Object error;
    private final boolean done = true;
    FakeCall(int id) { this(id, null); }
    FakeCall(int id, Object error) { this.id = id; this.error = error; }
  }

  @Test public void heartbeatBindsOnlyItsRegisteredDataNodeAndRestoresCaller() {
    Object dn = new Object();
    Probe.registerNode(dn, "hdfs-cluster-test/dn2", 3);
    try (Probe.NodeScope caller = Probe.withNode("caller", 0)) {
      try (HdfsHooks.HeartbeatScope heartbeat =
               HdfsHooks.heartbeatEnter(new FakeActor(dn))) {
        assertEquals("hdfs-cluster-test/dn2", Probe.currentNode());
        assertEquals(3, Probe.currentEpoch());
      }
      assertEquals("caller", Probe.currentNode());
      assertEquals(0, Probe.currentEpoch());
      try (HdfsHooks.HeartbeatScope unregistered =
               HdfsHooks.heartbeatEnter(new FakeActor(new Object()))) {
        assertEquals("unknown", Probe.currentNode());
      }
      assertEquals("caller", Probe.currentNode());
    }
  }

  @Test public void transformerScopesReplyThroughOfferServiceTargetIncludingThrowPath() {
    HdfsMiniClusterTransformer transformer = new HdfsMiniClusterTransformer();
    byte[] transformed = transformer.transform(getClass().getClassLoader(), ACTOR,
        null, null, syntheticActor(OFFER_SERVICE));
    assertNotNull(transformed);
    ClassNode clazz = new ClassNode();
    new ClassReader(transformed).accept(clazz, 0);
    int enters = 0;
    int closes = 0;
    int stateChecks = 0;
    int clears = 0;
    int handlers = 0;
    for (MethodNode method : clazz.methods) {
      if (!"offerService".equals(method.name)) continue;
      handlers += method.tryCatchBlocks.size();
      for (AbstractInsnNode instruction : method.instructions) {
        if (!(instruction instanceof MethodInsnNode)) continue;
        MethodInsnNode call = (MethodInsnNode) instruction;
        if (call.owner.endsWith("/HdfsHooks") && "heartbeatEnter".equals(call.name))
          enters++;
        if (call.owner.endsWith("/HdfsHooks$HeartbeatScope") && "close".equals(call.name))
          closes++;
        if (call.owner.endsWith("/BPOfferService")
            && "updateActorStatesFromHeartbeat".equals(call.name))
          stateChecks++;
        if (call.owner.endsWith("/HdfsHooks")
            && "heartbeatStateUpdated".equals(call.name)) {
          assertTrue("reply context must close after target",
              ((MethodInsnNode) instruction.getPrevious()).name.equals("updateActorStatesFromHeartbeat"));
          clears++;
        }
      }
    }
    assertEquals(1, enters);
    assertEquals(1, stateChecks);
    assertEquals(1, clears);
    assertTrue("normal and exceptional exits must close the scope", closes >= 2);
    assertTrue("the exceptional exit needs a handler", handlers >= 1);
    assertNull(transformer.transform(getClass().getClassLoader(), ACTOR,
        null, null, syntheticActor("(Z)V")));
  }

  @Test public void latestExactReplyContextEndsAfterStateCheck() {
    Object dn = new Object();
    Probe.registerNode(dn, "hdfs-cluster-test/dn1", 4);
    FakeClient client = new FakeClient();
    Object connection = client.new Connection();
    try (Probe.NodeScope caller = Probe.withNode("caller", 0);
         HdfsHooks.HeartbeatScope heartbeat = HdfsHooks.heartbeatEnter(new FakeActor(dn))) {
      HdfsHooks.rpcResponseConsumed(new Object(), connection, new FakeCall(7));
      assertEquals("0102:7:0", Probe.captureContext());
      assertEquals("hdfs-cluster-test/dn1", Probe.currentNode());
      HdfsHooks.rpcResponseConsumed(new Object(), connection, new FakeCall(8));
      assertEquals("0102:8:0", Probe.captureContext());
      HdfsHooks.heartbeatStateUpdated();
      assertEquals("root", Probe.captureContext());
      HdfsHooks.rpcResponseConsumed(new Object(), connection, new FakeCall(9));
      assertEquals("0102:9:0", Probe.captureContext());
    }
    assertEquals("root", Probe.captureContext());
    assertEquals("unknown", Probe.currentNode());
  }

  @Test public void exactErrorReplyParentsRetryUntilNextHeartbeatReply() {
    Object dn = new Object();
    Probe.registerNode(dn, "hdfs-cluster-test/dn3", 2);
    FakeClient client = new FakeClient();
    Object connection = client.new Connection();
    RemoteException error = new RemoteException();
    try (HdfsHooks.HeartbeatScope heartbeat = HdfsHooks.heartbeatEnter(new FakeActor(dn))) {
      HdfsHooks.rpcErrorConsumed(error, connection, new FakeCall(11, error));
      assertEquals("0102:11:0", Probe.captureContext());
      assertEquals("hdfs-cluster-test/dn3", Probe.currentNode());
      HdfsHooks.rpcResponseConsumed(new Object(), connection, new FakeCall(12));
      assertEquals("0102:12:0", Probe.captureContext());
      HdfsHooks.heartbeatStateUpdated();
      assertEquals("root", Probe.captureContext());
    }
  }

  private static byte[] syntheticActor(String descriptor) {
    ClassWriter writer = new ClassWriter(0);
    writer.visit(Opcodes.V1_8, Opcodes.ACC_PUBLIC, ACTOR, null, "java/lang/Object", null);
    MethodVisitor method = writer.visitMethod(Opcodes.ACC_PUBLIC,
        "offerService", descriptor, null, null);
    method.visitCode();
    if ("()V".equals(descriptor)) {
      method.visitInsn(Opcodes.ACONST_NULL);
      method.visitInsn(Opcodes.ACONST_NULL);
      method.visitInsn(Opcodes.ACONST_NULL);
      method.visitMethodInsn(Opcodes.INVOKEVIRTUAL,
          "org/apache/hadoop/hdfs/server/datanode/BPOfferService",
          "updateActorStatesFromHeartbeat", "(Ljava/lang/Object;Ljava/lang/Object;)V", false);
    }
    method.visitInsn(Opcodes.RETURN);
    method.visitMaxs("()V".equals(descriptor) ? 3 : 0, "()V".equals(descriptor) ? 1 : 2);
    method.visitEnd();
    writer.visitEnd();
    return writer.toByteArray();
  }
}
