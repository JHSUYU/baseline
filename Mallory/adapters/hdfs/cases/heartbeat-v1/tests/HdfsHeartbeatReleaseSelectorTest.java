package edu.uva.liftlab.mallory.adapters.hdfs;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import java.io.File;
import java.net.URL;
import java.net.URLClassLoader;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.Test;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;

/** Assert the bridge selectors against the pinned Hadoop class images. */
public class HdfsHeartbeatReleaseSelectorTest {
  private static final String HOOKS =
      "edu/uva/liftlab/mallory/adapters/hdfs/HdfsHooks";
  private static final String DN = "org/apache/hadoop/hdfs/server/datanode/";
  private static final String PB =
      "org/apache/hadoop/hdfs/protocolPB/DatanodeProtocolClientSideTranslatorPB";

  @Test public void realHadoopSelectorsBindBothReplyPathsAndExactQueueAction()
      throws Exception {
    String classes = System.getProperty("mallory.hadoop.classes");
    assertNotNull("real Hadoop class directory is required", classes);
    Path root = new File(classes).toPath();
    try (URLClassLoader loader = new URLClassLoader(new URL[]{root.toUri().toURL()},
        getClass().getClassLoader())) {
      ClassNode offer = transformed(root, loader, DN + "BPOfferService");
      assertEquals(1, calls(method(offer, "updateActorStatesFromHeartbeat"),
          HOOKS, "heartbeatStatusEnter"));
      assertEquals(1, calls(method(offer, "processCommandFromActive"),
          HOOKS, "datanodeCommandEnter"));

      ClassNode translator = transformed(root, loader, PB);
      for (String name : new String[]{"sendHeartbeat", "blockReport"}) {
        MethodNode method = method(translator, name);
        assertEquals(1, calls(method, HOOKS, "responseConsumerEnter"));
        String produced = name.equals("sendHeartbeat") ?
            "heartbeatResponseProduced" : "datanodeCommandProduced";
        assertTrue(calls(method, HOOKS, produced) >= 1);
        assertTrue(index(method, HOOKS, "responseConsumerEnter") <
            index(method, HOOKS, produced));
      }

      ClassNode worker = transformed(root, loader,
          DN + "BPServiceActor$CommandProcessingThread");
      MethodNode enqueue = method(worker, "enqueue");
      MethodNode processQueue = method(worker, "processQueue");
      assertEquals(1, calls(enqueue, HOOKS, "datanodeCommandSubmitted"));
      assertEquals(1, calls(processQueue, HOOKS, "datanodeCommandTaskEnter"));
      assertTrue(index(enqueue, HOOKS, "datanodeCommandSubmitted") <
          index(enqueue, "java/util/concurrent/BlockingQueue", "put"));
      assertTrue(index(processQueue, HOOKS, "datanodeCommandTaskEnter") <
          index(processQueue, "java/lang/Runnable", "run"));
    }
  }

  private static ClassNode transformed(Path root, ClassLoader loader, String name)
      throws Exception {
    byte[] original = Files.readAllBytes(root.resolve(name + ".class"));
    byte[] bytes = new HdfsMiniClusterTransformer().transform(
        loader, name, null, null, original);
    assertNotNull("not transformed: " + name, bytes);
    ClassNode parsed = new ClassNode();
    new ClassReader(bytes).accept(parsed, ClassReader.EXPAND_FRAMES);
    assertEquals(name, parsed.name);
    return parsed;
  }

  private static MethodNode method(ClassNode clazz, String name) {
    for (MethodNode method : clazz.methods) {
      if (method.name.equals(name)) return method;
    }
    throw new AssertionError("missing " + clazz.name + "#" + name);
  }

  private static int calls(MethodNode method, String owner, String name) {
    int count = 0;
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (instruction instanceof MethodInsnNode) {
        MethodInsnNode call = (MethodInsnNode) instruction;
        if (call.owner.equals(owner) && call.name.equals(name)) count++;
      }
    }
    return count;
  }

  private static int index(MethodNode method, String owner, String name) {
    int i = 0;
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (instruction instanceof MethodInsnNode) {
        MethodInsnNode call = (MethodInsnNode) instruction;
        if (call.owner.equals(owner) && call.name.equals(name)) return i;
      }
      i++;
    }
    throw new AssertionError("missing " + owner + "#" + name);
  }
}
