package edu.uva.liftlab.mallory.hbase32;

import java.lang.instrument.ClassFileTransformer;
import java.security.ProtectionDomain;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.InsnList;
import org.objectweb.asm.tree.InsnNode;
import org.objectweb.asm.tree.LabelNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.TryCatchBlockNode;
import org.objectweb.asm.tree.VarInsnNode;

/** A case-local scope around process(), including its call to the target function. */
public final class HBase32ActorTransformer implements ClassFileTransformer {
  private static final String CLASS =
      "org/apache/hadoop/hbase/regionserver/handler/RegionReplicaFlushHandler";
  private static final String HOOKS = "edu/uva/liftlab/mallory/hbase32/HBase32ActorHooks";
  private static final String SCOPE =
      "edu/uva/liftlab/mallory/instrumentation/Probe$NodeScope";

  @Override public byte[] transform(ClassLoader loader, String className, Class<?> redefined,
                                     ProtectionDomain domain, byte[] original) {
    if (!CLASS.equals(className)) return null;
    try {
      ClassNode node = new ClassNode();
      new ClassReader(original).accept(node, ClassReader.EXPAND_FRAMES);
      boolean changed = false;
      for (MethodNode method : node.methods) {
        if ("process".equals(method.name) && "()V".equals(method.desc)) {
          scope(method);
          changed = true;
        }
      }
      if (!changed) throw new IllegalStateException("RegionReplicaFlushHandler.process() missing");
      ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_FRAMES | ClassWriter.COMPUTE_MAXS);
      node.accept(writer);
      return writer.toByteArray();
    } catch (Throwable failure) {
      System.err.println("Mallory HBASE-32 actor overlay failed: " + failure);
      return null;
    }
  }

  private static void scope(MethodNode method) {
    int local = method.maxLocals++;
    LabelNode start = new LabelNode();
    InsnList entry = new InsnList();
    entry.add(new VarInsnNode(Opcodes.ALOAD, 0));
    entry.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "enter",
        "(Ljava/lang/Object;)L" + SCOPE + ";", false));
    entry.add(new VarInsnNode(Opcodes.ASTORE, local));
    entry.add(start);
    method.instructions.insert(entry);
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      int opcode = instruction.getOpcode();
      if (opcode >= Opcodes.IRETURN && opcode <= Opcodes.RETURN)
        method.instructions.insertBefore(instruction, close(local));
    }
    LabelNode end = new LabelNode();
    LabelNode handler = new LabelNode();
    method.instructions.add(end);
    method.instructions.add(handler);
    method.instructions.add(close(local));
    method.instructions.add(new InsnNode(Opcodes.ATHROW));
    method.tryCatchBlocks.add(new TryCatchBlockNode(start, end, handler, null));
  }

  private static InsnList close(int local) {
    InsnList result = new InsnList();
    result.add(new VarInsnNode(Opcodes.ALOAD, local));
    result.add(new MethodInsnNode(Opcodes.INVOKEVIRTUAL, SCOPE, "close", "()V", false));
    return result;
  }
}
