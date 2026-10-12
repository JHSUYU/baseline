package edu.uva.liftlab.mallory.hbase.hbase28;

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

/** Scope only HBase's indexed MiniCluster factories; no thread-name inference. */
public final class ConstructorActorTransformer implements ClassFileTransformer {
  private static final String CLUSTER = "org/apache/hadoop/hbase/util/JVMClusterUtil";
  private static final String HOOKS = Type.getInternalName(ConstructorActorHooks.class);
  private static final String SCOPE = "edu/uva/liftlab/mallory/instrumentation/Probe$NodeScope";

  @Override public byte[] transform(ClassLoader loader, String className, Class<?> redefining,
                                    ProtectionDomain domain, byte[] original) {
    if (!CLUSTER.equals(className)) return null;
    try {
      ClassNode owner = new ClassNode();
      new ClassReader(original).accept(owner, ClassReader.EXPAND_FRAMES);
      boolean changed = false;
      for (MethodNode method : owner.methods) {
        if ("createRegionServerThread".equals(method.name) &&
            method.desc.equals("(Lorg/apache/hadoop/conf/Configuration;Ljava/lang/Class;I)" +
                "Lorg/apache/hadoop/hbase/util/JVMClusterUtil$RegionServerThread;")) {
          scope(method, "enterRegionServer");
          changed = true;
        } else if ("createMasterThread".equals(method.name) &&
            method.desc.equals("(Lorg/apache/hadoop/conf/Configuration;Ljava/lang/Class;I)" +
                "Lorg/apache/hadoop/hbase/util/JVMClusterUtil$MasterThread;")) {
          scope(method, "enterMaster");
          changed = true;
        }
      }
      if (!changed) throw new IllegalStateException("HBase 2.6.6 indexed factory methods missing");
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
      System.err.println("Mallory HBASE-28 constructor actor overlay failed: " + failure);
      return null;
    }
  }

  private static void scope(MethodNode method, String hook) {
    int scopeLocal = method.maxLocals++;
    LabelNode start = new LabelNode();
    InsnList entry = new InsnList();
    entry.add(new VarInsnNode(Opcodes.ILOAD, 2));
    entry.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, hook,
        "(I)L" + SCOPE + ";", false));
    entry.add(new VarInsnNode(Opcodes.ASTORE, scopeLocal));
    entry.add(start);
    method.instructions.insert(entry);
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (instruction.getOpcode() == Opcodes.ARETURN)
        method.instructions.insertBefore(instruction, close(scopeLocal));
    }
    LabelNode end = new LabelNode();
    LabelNode handler = new LabelNode();
    method.instructions.add(end);
    method.instructions.add(handler);
    method.instructions.add(close(scopeLocal));
    method.instructions.add(new InsnNode(Opcodes.ATHROW));
    method.tryCatchBlocks.add(new TryCatchBlockNode(start, end, handler, null));
  }

  private static InsnList close(int scopeLocal) {
    InsnList close = new InsnList();
    close.add(new VarInsnNode(Opcodes.ALOAD, scopeLocal));
    close.add(new MethodInsnNode(Opcodes.INVOKEVIRTUAL, SCOPE, "close", "()V", false));
    return close;
  }
}
