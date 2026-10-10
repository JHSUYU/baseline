package edu.uva.liftlab.mallory.hbase.clientowner;

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

/** HBase 2.6.6 source-specific ownership handoff, separate from the base adapter. */
public final class ClientRpcOwnerTransformer implements ClassFileTransformer {
  private static final String UTILITY = "org/apache/hadoop/hbase/HBaseTestingUtility";
  private static final String CLIENT = "org/apache/hadoop/hbase/ipc/AbstractRpcClient";
  private static final String HOOKS = Type.getInternalName(ClientRpcOwnerHooks.class);
  private static final String SCOPE = "edu/uva/liftlab/mallory/instrumentation/Probe$NodeScope";
  private static final String CALL_METHOD_DESC =
      "(Lorg/apache/hbase/thirdparty/com/google/protobuf/Descriptors$MethodDescriptor;"
      + "Lorg/apache/hadoop/hbase/ipc/HBaseRpcController;"
      + "Lorg/apache/hbase/thirdparty/com/google/protobuf/Message;"
      + "Lorg/apache/hbase/thirdparty/com/google/protobuf/Message;"
      + "Lorg/apache/hadoop/hbase/security/User;"
      + "Lorg/apache/hadoop/hbase/net/Address;"
      + "Lorg/apache/hbase/thirdparty/com/google/protobuf/RpcCallback;)"
      + "Lorg/apache/hadoop/hbase/ipc/Call;";
  private static final String BLOCKING_DESC =
      "(Lorg/apache/hbase/thirdparty/com/google/protobuf/Descriptors$MethodDescriptor;"
      + "Lorg/apache/hadoop/hbase/ipc/HBaseRpcController;"
      + "Lorg/apache/hbase/thirdparty/com/google/protobuf/Message;"
      + "Lorg/apache/hbase/thirdparty/com/google/protobuf/Message;"
      + "Lorg/apache/hadoop/hbase/security/User;"
      + "Lorg/apache/hadoop/hbase/net/Address;)"
      + "Lorg/apache/hbase/thirdparty/com/google/protobuf/Message;";

  @Override public byte[] transform(ClassLoader loader, String className, Class<?> redefining,
                                    ProtectionDomain domain, byte[] original) {
    if (!UTILITY.equals(className) && !CLIENT.equals(className)) return null;
    try {
      ClassNode owner = new ClassNode();
      new ClassReader(original).accept(owner, ClassReader.EXPAND_FRAMES);
      int patched = 0;
      for (MethodNode method : owner.methods) {
        if (UTILITY.equals(className) && "getConnection".equals(method.name)
            && "()Lorg/apache/hadoop/hbase/client/Connection;".equals(method.desc)) {
          registerReturnedConnection(method);
          patched++;
        } else if (CLIENT.equals(className) &&
                   (("callMethod".equals(method.name) && CALL_METHOD_DESC.equals(method.desc))
                   || ("callBlockingMethod".equals(method.name)
                       && BLOCKING_DESC.equals(method.desc)))) {
          scopeRpcClient(method);
          patched++;
        }
      }
      if (patched != (UTILITY.equals(className) ? 1 : 2))
        throw new IllegalStateException("HBase 2.6.6 client ownership sites missing: " + patched);
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
      System.err.println("Mallory HBase client RpcClient owner overlay failed: " + failure);
      return null;
    }
  }

  private static void registerReturnedConnection(MethodNode method) {
    int returns = 0;
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (instruction.getOpcode() != Opcodes.ARETURN) continue;
      InsnList probe = new InsnList();
      probe.add(new InsnNode(Opcodes.DUP));
      probe.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "registerTestConnection",
          "(Ljava/lang/Object;)V", false));
      method.instructions.insertBefore(instruction, probe);
      returns++;
    }
    if (returns != 1)
      throw new IllegalStateException("Expected one HBaseTestingUtility.getConnection return");
  }

  private static void scopeRpcClient(MethodNode method) {
    int local = method.maxLocals++;
    LabelNode start = new LabelNode();
    InsnList entry = new InsnList();
    entry.add(new VarInsnNode(Opcodes.ALOAD, 0));
    entry.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "enterKnownRpcClient",
        "(Ljava/lang/Object;)L" + SCOPE + ";", false));
    entry.add(new VarInsnNode(Opcodes.ASTORE, local));
    entry.add(start);
    method.instructions.insert(entry);
    int returns = 0;
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (instruction.getOpcode() != Opcodes.ARETURN) continue;
      method.instructions.insertBefore(instruction, close(local));
      returns++;
    }
    if (returns == 0) throw new IllegalStateException("RPC method has no reference return");
    LabelNode end = new LabelNode();
    LabelNode handler = new LabelNode();
    method.instructions.add(end);
    method.instructions.add(handler);
    method.instructions.add(close(local));
    method.instructions.add(new InsnNode(Opcodes.ATHROW));
    method.tryCatchBlocks.add(new TryCatchBlockNode(start, end, handler, null));
  }

  private static InsnList close(int local) {
    InsnList insns = new InsnList();
    insns.add(new VarInsnNode(Opcodes.ALOAD, local));
    insns.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "closeScope",
        "(L" + SCOPE + ";)V", false));
    return insns;
  }
}
