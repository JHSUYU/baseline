package edu.uva.liftlab.mallory.adapters.hdfs;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.io.File;
import java.lang.reflect.Method;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.atomic.AtomicReference;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.junit.Test;
import org.junit.Assume;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;

/** Focused ordering checks for the isolated HDFS command queue bridge. */
public class HdfsHeartbeatBridgeTest {
  private static final String WORKER =
      "org/apache/hadoop/hdfs/server/datanode/BPServiceActor$CommandProcessingThread";
  private static final String HOOKS =
      "edu/uva/liftlab/mallory/adapters/hdfs/HdfsHooks";

  private static final class FakeActor {
    private final Object dn;
    FakeActor(Object dn) { this.dn = dn; }
  }

  private static final class FakeWorker {
    private final FakeActor actor;
    FakeWorker(Object dn) { actor = new FakeActor(dn); }
  }

  @Test public void transformedSubmitPrecedesVisiblePutAndClaimEnclosesRun() {
    ClassWriter writer = new ClassWriter(0);
    writer.visit(Opcodes.V1_8, Opcodes.ACC_PUBLIC, WORKER, null,
        "java/lang/Object", null);
    writer.visitField(Opcodes.ACC_PRIVATE, "queue",
        "Ljava/util/concurrent/BlockingQueue;", null, null).visitEnd();
    MethodVisitor method = writer.visitMethod(Opcodes.ACC_PUBLIC, "enqueue",
        "(Ljava/lang/Runnable;)V", null, new String[]{"java/lang/InterruptedException"});
    method.visitCode();
    method.visitVarInsn(Opcodes.ALOAD, 0);
    method.visitFieldInsn(Opcodes.GETFIELD, WORKER, "queue",
        "Ljava/util/concurrent/BlockingQueue;");
    method.visitVarInsn(Opcodes.ALOAD, 1);
    method.visitMethodInsn(Opcodes.INVOKEINTERFACE,
        "java/util/concurrent/BlockingQueue", "put", "(Ljava/lang/Object;)V", true);
    method.visitInsn(Opcodes.RETURN);
    method.visitMaxs(2, 2);
    method.visitEnd();
    method = writer.visitMethod(Opcodes.ACC_PRIVATE, "processQueue", "()V", null, null);
    method.visitCode();
    method.visitInsn(Opcodes.ACONST_NULL);
    method.visitVarInsn(Opcodes.ASTORE, 1);
    method.visitVarInsn(Opcodes.ALOAD, 1);
    method.visitMethodInsn(Opcodes.INVOKEINTERFACE,
        "java/lang/Runnable", "run", "()V", true);
    method.visitInsn(Opcodes.RETURN);
    method.visitMaxs(1, 2);
    method.visitEnd();
    writer.visitEnd();

    byte[] transformed = new HdfsMiniClusterTransformer().transform(
        getClass().getClassLoader(), WORKER, null, null, writer.toByteArray());
    assertNotNull(transformed);
    ClassNode clazz = new ClassNode();
    new ClassReader(transformed).accept(clazz, 0);
    MethodNode enqueue = null, queue = null;
    for (MethodNode candidate : clazz.methods) {
      if (candidate.name.equals("enqueue")) enqueue = candidate;
      if (candidate.name.equals("processQueue")) queue = candidate;
    }
    assertNotNull(enqueue);
    assertNotNull(queue);
    assertTrue(callIndex(enqueue, HOOKS, "datanodeCommandSubmitted") <
        callIndex(enqueue, "java/util/concurrent/BlockingQueue", "put"));
    assertTrue(callIndex(queue, HOOKS, "datanodeCommandTaskEnter") <
        callIndex(queue, "java/lang/Runnable", "run"));
  }

  @Test public void everyConcurrentClaimHasEarlierExactSubmit() throws Exception {
    Path events = Files.createTempFile("mallory-hdfs-command-queue-", ".jsonl");
    Class<?> faultPlan = Class.forName("edu.uva.liftlab.mallory.instrumentation.FaultPlan");
    Method install = Probe.class.getDeclaredMethod("install",
        String.class, File.class, faultPlan);
    install.setAccessible(true);
    install.invoke(null, "hdfs-command-race-test", events.toFile(), null);

    Object dn = new Object();
    Probe.registerNode(dn, "hdfs-test/dn0", 0);
    FakeWorker worker = new FakeWorker(dn);
    LinkedBlockingQueue<Runnable> queue = new LinkedBlockingQueue<Runnable>();
    AtomicReference<Throwable> failure = new AtomicReference<Throwable>();
    Thread consumer = new Thread(() -> {
      try {
        for (int i = 0; i < 100; i++) {
          Runnable action = queue.take();
          try (HdfsHooks.DatanodeReplyScope ignored =
                   HdfsHooks.datanodeCommandTaskEnter(worker, action)) {
            action.run();
          }
        }
      } catch (Throwable thrown) { failure.set(thrown); }
    }, "hdfs-command-race-consumer");
    consumer.start();
    for (int i = 0; i < 100; i++) {
      final int item = i;
      // Hadoop's enqueue lambdas capture their command payload. Preserve
      // distinct Runnable identity here so no two queued items are aliases.
      Runnable action = () -> { if (item < 0) throw new AssertionError(); };
      HdfsHooks.datanodeCommandSubmitted(worker, action, null);
      queue.put(action);
    }
    consumer.join(10000L);
    assertTrue("consumer did not finish", !consumer.isAlive());
    if (failure.get() != null) throw new AssertionError(failure.get());

    Pattern correlation = Pattern.compile("\\\"correlation\\\":\\\"([^\\\"]+)\\\"");
    Map<String, Integer> submissions = new HashMap<String, Integer>();
    Map<String, Integer> claims = new HashMap<String, Integer>();
    List<String> rows = Files.readAllLines(events, StandardCharsets.UTF_8);
    for (int index = 0; index < rows.size(); index++) {
      String row = rows.get(index);
      Matcher match = correlation.matcher(row);
      if (!match.find()) continue;
      if (row.contains("\"type\":\"TASK_SUBMIT\"")) submissions.put(match.group(1), index);
      if (row.contains("\"type\":\"TASK_CLAIM\"")) claims.put(match.group(1), index);
    }
    assertEquals(100, submissions.size());
    assertEquals(100, claims.size());
    for (Map.Entry<String, Integer> claim : claims.entrySet()) {
      Integer submit = submissions.get(claim.getKey());
      assertNotNull(submit);
      assertTrue(submit.intValue() < claim.getValue().intValue());
    }
  }

  @Test public void pinnedHadoopClassImagesTransform() throws Exception {
    String classes = System.getProperty("mallory.hadoop.classes");
    Assume.assumeTrue("supply -Dmallory.hadoop.classes for the real image check", classes != null);
    Path root = new File(classes).toPath();
    try (URLClassLoader loader = new URLClassLoader(new URL[]{root.toUri().toURL()},
        getClass().getClassLoader())) {
      for (String name : new String[]{
          "org/apache/hadoop/hdfs/server/datanode/BPServiceActor$CommandProcessingThread",
          "org/apache/hadoop/hdfs/server/datanode/BPOfferService",
          "org/apache/hadoop/hdfs/protocolPB/DatanodeProtocolClientSideTranslatorPB"}) {
        byte[] original = Files.readAllBytes(root.resolve(name + ".class"));
        byte[] transformed = new HdfsMiniClusterTransformer().transform(
            loader, name, null, null, original);
        assertNotNull("not transformed: " + name, transformed);
        ClassNode parsed = new ClassNode();
        new ClassReader(transformed).accept(parsed, ClassReader.EXPAND_FRAMES);
        assertEquals(name, parsed.name);
      }
    }
  }

  private static int callIndex(MethodNode method, String owner, String name) {
    int index = 0;
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (instruction instanceof MethodInsnNode) {
        MethodInsnNode call = (MethodInsnNode) instruction;
        if (call.owner.equals(owner) && call.name.equals(name)) return index;
      }
      index++;
    }
    throw new AssertionError("missing " + owner + "#" + name);
  }
}
