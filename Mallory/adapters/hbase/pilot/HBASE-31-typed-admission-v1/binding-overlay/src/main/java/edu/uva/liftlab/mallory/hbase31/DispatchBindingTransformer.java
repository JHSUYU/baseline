package edu.uva.liftlab.mallory.hbase31;

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

/** Wrap only HBASE-31's compiled ExecuteProcedures send boundary. */
public final class DispatchBindingTransformer implements ClassFileTransformer {
  private static final String OWNER =
      "org/apache/hadoop/hbase/master/procedure/RSProcedureDispatcher$ExecuteProceduresRemoteCall";
  private static final String METHOD = "sendRequest";
  private static final String DESCRIPTOR =
      "(Lorg/apache/hadoop/hbase/ServerName;"
      + "Lorg/apache/hadoop/hbase/shaded/protobuf/generated/AdminProtos$ExecuteProceduresRequest;)"
      + "Lorg/apache/hadoop/hbase/shaded/protobuf/generated/AdminProtos$ExecuteProceduresResponse;";
  private static final String HOOKS = Type.getInternalName(DispatchBindingHooks.class);
  private static final String SCOPE = Type.getInternalName(
      edu.uva.liftlab.mallory.instrumentation.Probe.NodeScope.class);

  @Override public byte[] transform(ClassLoader loader, String className, Class<?> redefining,
                                    ProtectionDomain domain, byte[] original) {
    if (!OWNER.equals(className)) return null;
    try {
      ClassNode owner = new ClassNode();
      new ClassReader(original).accept(owner, ClassReader.EXPAND_FRAMES);
      for (MethodNode method : owner.methods) {
        if (!METHOD.equals(method.name) || !DESCRIPTOR.equals(method.desc)) continue;
        wrap(method);
        ClassWriter writer = new SafeWriter(ClassWriter.COMPUTE_FRAMES
            | ClassWriter.COMPUTE_MAXS, loader);
        owner.accept(writer);
        return writer.toByteArray();
      }
      return null;
    } catch (Throwable failure) {
      System.err.println("Mallory HBASE-31 dispatch binding failed: " + failure);
      return null;
    }
  }

  private static void wrap(MethodNode method) {
    int scope = method.maxLocals++;
    LabelNode start = new LabelNode();
    InsnList entry = new InsnList();
    entry.add(new VarInsnNode(Opcodes.ALOAD, 0));
    entry.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "enterSendRequest",
        "(Ljava/lang/Object;)L" + SCOPE + ";", false));
    entry.add(new VarInsnNode(Opcodes.ASTORE, scope));
    entry.add(start);
    method.instructions.insert(entry);
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      int op = instruction.getOpcode();
      if (op >= Opcodes.IRETURN && op <= Opcodes.RETURN)
        method.instructions.insertBefore(instruction, close(scope));
    }
    LabelNode end = new LabelNode();
    LabelNode handler = new LabelNode();
    method.instructions.add(end);
    method.instructions.add(handler);
    method.instructions.add(close(scope));
    method.instructions.add(new InsnNode(Opcodes.ATHROW));
    method.tryCatchBlocks.add(new TryCatchBlockNode(start, end, handler, null));
  }

  private static InsnList close(int scope) {
    InsnList result = new InsnList();
    result.add(new VarInsnNode(Opcodes.ALOAD, scope));
    result.add(new MethodInsnNode(Opcodes.INVOKEVIRTUAL, SCOPE, "close", "()V", false));
    return result;
  }

  private static final class SafeWriter extends ClassWriter {
    private final ClassLoader loader;
    SafeWriter(int flags, ClassLoader loader) { super(flags); this.loader = loader; }
    @Override protected String getCommonSuperClass(String first, String second) {
      if (first.equals(second)) return first;
      try {
        Class<?> left = Class.forName(first.replace('/', '.'), false, loader);
        Class<?> right = Class.forName(second.replace('/', '.'), false, loader);
        if (left.isAssignableFrom(right)) return first;
        if (right.isAssignableFrom(left)) return second;
        if (left.isInterface() || right.isInterface()) return "java/lang/Object";
        while ((left = left.getSuperclass()) != null)
          if (left.isAssignableFrom(right)) return Type.getInternalName(left);
      } catch (ClassNotFoundException | LinkageError ignored) { }
      return "java/lang/Object";
    }
  }
}
