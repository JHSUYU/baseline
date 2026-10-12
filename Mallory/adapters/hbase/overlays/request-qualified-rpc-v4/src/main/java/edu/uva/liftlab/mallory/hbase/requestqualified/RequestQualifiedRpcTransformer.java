package edu.uva.liftlab.mallory.hbase.requestqualified;

import java.lang.instrument.ClassFileTransformer;
import java.security.ProtectionDomain;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.Type;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.InsnList;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.VarInsnNode;

/** Inserts a request-qualified probe at the sole RpcServer.call service dispatch. */
public final class RequestQualifiedRpcTransformer implements ClassFileTransformer {
  private static final String RPC_SERVER = "org/apache/hadoop/hbase/ipc/RpcServer";
  private static final String BASE_HOOKS = "edu/uva/liftlab/mallory/hbase/HBaseHooks";
  private static final String BASE_SCOPE = BASE_HOOKS + "$Scope";
  private static final String BLOCKING_SERVICE =
      "org/apache/hbase/thirdparty/com/google/protobuf/BlockingService";
  private static final String CALL_DESC =
      "(Lorg/apache/hbase/thirdparty/com/google/protobuf/Descriptors$MethodDescriptor;"
      + "Lorg/apache/hbase/thirdparty/com/google/protobuf/RpcController;"
      + "Lorg/apache/hbase/thirdparty/com/google/protobuf/Message;)"
      + "Lorg/apache/hbase/thirdparty/com/google/protobuf/Message;";
  private static final String HOOKS = Type.getInternalName(RequestQualifiedRpcHooks.class);
  public static final String BASE_SITE =
      "org.apache.hadoop.hbase.ipc.RpcServer#call"
      + "(Lorg/apache/hadoop/hbase/ipc/RpcCall;"
      + "Lorg/apache/hadoop/hbase/monitoring/MonitoredRPCHandler;)"
      + "Lorg/apache/hadoop/hbase/util/Pair;@447:door:1";

  @Override public byte[] transform(ClassLoader loader, String className, Class<?> redefining,
                                    ProtectionDomain domain, byte[] original) {
    if (!RPC_SERVER.equals(className)) return null;
    try {
      ClassNode owner = new ClassNode();
      new ClassReader(original).accept(owner, ClassReader.EXPAND_FRAMES);
      MethodInsnNode dispatch = null;
      MethodNode selected = null;
      for (MethodNode method : owner.methods) {
        if (!"call".equals(method.name)
            || !"(Lorg/apache/hadoop/hbase/ipc/RpcCall;"
                .concat("Lorg/apache/hadoop/hbase/monitoring/MonitoredRPCHandler;)")
                .concat("Lorg/apache/hadoop/hbase/util/Pair;").equals(method.desc)) continue;
        for (AbstractInsnNode instruction : method.instructions.toArray()) {
          if (!(instruction instanceof MethodInsnNode)) continue;
          MethodInsnNode call = (MethodInsnNode) instruction;
          if (!BLOCKING_SERVICE.equals(call.owner)
              || !"callBlockingMethod".equals(call.name)
              || !CALL_DESC.equals(call.desc)) continue;
          if (dispatch != null) throw new IllegalStateException("Ambiguous RPC dispatch");
          dispatch = call;
          selected = method;
        }
      }
      if (dispatch == null) throw new IllegalStateException("RPC dispatch missing");
      int entries = 0;
      int closes = 0;
      for (AbstractInsnNode instruction : selected.instructions.toArray()) {
        if (!(instruction instanceof MethodInsnNode)) continue;
        MethodInsnNode call = (MethodInsnNode) instruction;
        if (BASE_HOOKS.equals(call.owner) && "enterServerCall".equals(call.name)) {
          AbstractInsnNode store = call.getNext();
          if (!(store instanceof VarInsnNode) || store.getOpcode() != Opcodes.ASTORE)
            throw new IllegalStateException("Base scope store is missing");
          selected.instructions.insert(store, new MethodInsnNode(Opcodes.INVOKESTATIC,
              HOOKS, "enterMethod", "()V", false));
          entries++;
        }
        if (BASE_SCOPE.equals(call.owner) && "close".equals(call.name)
            && "()V".equals(call.desc)) {
          call.setOpcode(Opcodes.INVOKESTATIC);
          call.owner = HOOKS;
          call.name = "closeServerScope";
          call.desc = "(Ljava/lang/Object;)V";
          call.itf = false;
          closes++;
        }
      }
      if (entries != 1 || closes < 2)
        throw new IllegalStateException("Base RPC scope entry/close not uniquely wrapped: "
            + entries + "/" + closes);
      InsnList probe = new InsnList();
      probe.add(new VarInsnNode(Opcodes.ALOAD, 1));
      probe.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "beforeDispatch",
          "(Ljava/lang/Object;)V", false));
      selected.instructions.insertBefore(dispatch, probe);
      // The inserted call consumes only the loaded RpcCall. Original stack maps
      // and operand stack at the service invocation remain unchanged.
      ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
      owner.accept(writer);
      return writer.toByteArray();
    } catch (Throwable failure) {
      System.err.println("Mallory request-qualified RPC overlay failed: " + failure);
      return null;
    }
  }

}
