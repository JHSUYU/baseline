package edu.uva.liftlab.mallory.hbase.ctoractor;

import java.lang.instrument.ClassFileTransformer;
import java.security.ProtectionDomain;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.Type;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.InsnList;
import org.objectweb.asm.tree.InsnNode;
import org.objectweb.asm.tree.LabelNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.TryCatchBlockNode;
import org.objectweb.asm.tree.VarInsnNode;

/** Scope only the indexed HBase MiniCluster factories, including reflective construction. */
public final class CtorActorTransformer implements ClassFileTransformer {
  private static final String OWNER = "org/apache/hadoop/hbase/util/JVMClusterUtil";
  private static final String REGION_METHOD = "createRegionServerThread";
  private static final String REGION_DESC =
      "(Lorg/apache/hadoop/conf/Configuration;Ljava/lang/Class;I)Lorg/apache/hadoop/hbase/util/JVMClusterUtil$RegionServerThread;";
  private static final String MASTER_METHOD = "createMasterThread";
  private static final String MASTER_DESC =
      "(Lorg/apache/hadoop/conf/Configuration;Ljava/lang/Class;I)Lorg/apache/hadoop/hbase/util/JVMClusterUtil$MasterThread;";
  private static final String HOOKS = Type.getInternalName(CtorActorHooks.class);
  private static final String SCOPE = "edu/uva/liftlab/mallory/instrumentation/Probe$NodeScope";

  @Override public byte[] transform(ClassLoader loader, String className, Class<?> redefining,
                                    ProtectionDomain domain, byte[] original) {
    if (!OWNER.equals(className)) return null;
    try {
      ClassNode owner = new ClassNode();
      new ClassReader(original).accept(owner, ClassReader.EXPAND_FRAMES);
      int transformed = 0;
      for (MethodNode method : owner.methods) {
        if (REGION_METHOD.equals(method.name) && REGION_DESC.equals(method.desc)) {
          scope(method, "enterRegionServer");
          transformed++;
        } else if (MASTER_METHOD.equals(method.name) && MASTER_DESC.equals(method.desc)) {
          scope(method, "enterMaster");
          transformed++;
        }
      }
      if (transformed != 2) throw new IllegalStateException("Expected both indexed MiniCluster factories");
      ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_FRAMES | ClassWriter.COMPUTE_MAXS) {
        @Override protected String getCommonSuperClass(String left, String right) {
          if (left.equals(right)) return left;
          try {
            Class<?> a = Class.forName(left.replace('/', '.'), false, loader);
            Class<?> b = Class.forName(right.replace('/', '.'), false, loader);
            if (a.isAssignableFrom(b)) return left;
            if (b.isAssignableFrom(a)) return right;
            if (a.isInterface() || b.isInterface()) return "java/lang/Object";
            do { a = a.getSuperclass(); } while (a != null && !a.isAssignableFrom(b));
            return a == null ? "java/lang/Object" : Type.getInternalName(a);
          } catch (Throwable ignored) {
            return "java/lang/Object";
          }
        }
      };
      owner.accept(writer);
      return writer.toByteArray();
    } catch (Throwable failure) {
      System.err.println("Mallory HBase constructor actor binding failed: " + failure);
      return null;
    }
  }

  private static void scope(MethodNode method, String hookName) {
    int local = method.maxLocals++;
    LabelNode start = new LabelNode();
    InsnList entry = new InsnList();
    entry.add(new VarInsnNode(Opcodes.ILOAD, 2));
    entry.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, hookName,
        "(I)L" + SCOPE + ";", false));
    entry.add(new VarInsnNode(Opcodes.ASTORE, local));
    entry.add(start);
    method.instructions.insert(entry);
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      int op = instruction.getOpcode();
      if (op >= Opcodes.IRETURN && op <= Opcodes.RETURN)
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
    InsnList code = new InsnList();
    code.add(new VarInsnNode(Opcodes.ALOAD, local));
    code.add(new MethodInsnNode(Opcodes.INVOKEVIRTUAL, SCOPE, "close", "()V", false));
    return code;
  }
}
