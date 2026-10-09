package edu.uva.liftlab.mallory.hbase;

import java.lang.instrument.ClassFileTransformer;
import java.io.IOException;
import java.io.InputStream;
import java.security.ProtectionDomain;
import java.util.HashSet;
import java.util.Set;
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
import org.objectweb.asm.tree.TypeInsnNode;
import org.objectweb.asm.tree.VarInsnNode;

/** Selective HBase 2.6.x bytecode hooks; no HBase source modification is required. */
public final class HBaseAdapterTransformer implements ClassFileTransformer {
  private static final String HOOKS = Type.getInternalName(HBaseHooks.class);
  private static final String SCOPE = Type.getInternalName(HBaseHooks.Scope.class);

  @Override public byte[] transform(ClassLoader loader, String className, Class<?> redefining,
                                    ProtectionDomain domain, byte[] original) {
    if (!isHBaseHookClass(className)) return null;
    try {
      ClassNode owner = new ClassNode();
      new ClassReader(original).accept(owner, ClassReader.EXPAND_FRAMES);
      boolean changed = false;
      for (MethodNode method : owner.methods) changed |= transformMethod(className, method);
      if (!changed) return null;
      ClassWriter out = new SafeWriter(ClassWriter.COMPUTE_FRAMES | ClassWriter.COMPUTE_MAXS,
          loader);
      owner.accept(out);
      return out.toByteArray();
    } catch (Throwable failure) {
      System.err.println("Mallory HBase adapter failed for " + className + ": " + failure);
      return null;
    }
  }

  private static boolean isHBaseHookClass(String name) {
    return "org/apache/hadoop/hbase/ipc/Call".equals(name)
        || "org/apache/hadoop/hbase/ipc/IPCUtil".equals(name)
        || "org/apache/hadoop/hbase/ipc/RpcConnection".equals(name)
        || "org/apache/hadoop/hbase/ipc/AbstractRpcClient".equals(name)
        || "org/apache/hadoop/hbase/ipc/RpcServer".equals(name)
        || "org/apache/hadoop/hbase/procedure2/ProcedureExecutor".equals(name)
        || "org/apache/hadoop/hbase/procedure2/AbstractProcedureScheduler".equals(name)
        || "org/apache/hadoop/hbase/master/procedure/MasterProcedureScheduler".equals(name)
        || "org/apache/hadoop/hbase/master/procedure/MasterProcedureEnv".equals(name)
        || "org/apache/hadoop/hbase/client/ResultBoundedCompletionService".equals(name)
        || "org/apache/hadoop/hbase/client/ResultBoundedCompletionService$QueueingFuture".equals(name)
        || "org/apache/hadoop/hbase/client/ConnectionImplementation".equals(name)
        || "org/apache/hadoop/hbase/client/HBaseAdmin".equals(name)
        || isMasterProcedureClass(name)
        || "org/apache/hadoop/hbase/procedure/ZKProcedureMemberRpcs".equals(name)
        || "org/apache/hadoop/hbase/procedure/ZKProcedureCoordinator".equals(name)
        || "org/apache/hadoop/hbase/procedure/ProcedureCoordinator".equals(name)
        || "org/apache/hadoop/hbase/zookeeper/MasterAddressTracker".equals(name)
        || "org/apache/hadoop/hbase/util/JVMClusterUtil$RegionServerThread".equals(name)
        || "org/apache/hadoop/hbase/util/JVMClusterUtil$MasterThread".equals(name)
        || "org/apache/hadoop/hbase/regionserver/HRegionServer".equals(name)
        || "org/apache/hadoop/hbase/master/HMaster".equals(name)
        || "org/apache/hadoop/hbase/HBaseTestingUtility".equals(name);
  }

  private static boolean isMasterProcedureClass(String name) {
    return name != null && name.startsWith("org/apache/hadoop/hbase/master/procedure/")
        && name.endsWith("Procedure");
  }

  private static boolean transformMethod(String owner, MethodNode method) {
    if ("org/apache/hadoop/hbase/util/JVMClusterUtil$RegionServerThread".equals(owner)
        && "<init>".equals(method.name)
        && "(Lorg/apache/hadoop/hbase/regionserver/HRegionServer;I)V".equals(method.desc)) {
      registerMiniClusterActorAfterConstruction(method, "registerRegionServer");
      return true;
    }
    if ("org/apache/hadoop/hbase/util/JVMClusterUtil$MasterThread".equals(owner)
        && "<init>".equals(method.name)
        && "(Lorg/apache/hadoop/hbase/master/HMaster;I)V".equals(method.desc)) {
      registerMiniClusterActorAfterConstruction(method, "registerMaster");
      return true;
    }
    if (("org/apache/hadoop/hbase/regionserver/HRegionServer".equals(owner)
        || "org/apache/hadoop/hbase/master/HMaster".equals(owner))
        && "run".equals(method.name) && "()V".equals(method.desc)) {
      wrapScope(method, "enterMiniClusterActor", false);
      return true;
    }
    if ("org/apache/hadoop/hbase/master/HMaster".equals(owner)
        && "getActiveMasterInfoPort".equals(method.name)
        && "()I".equals(method.desc)) {
      wrapScope(method, "enterMiniClusterActor", false);
      return true;
    }
    if ("org/apache/hadoop/hbase/ipc/Call".equals(owner)
        && "<init>".equals(method.name)) {
      afterConstructor(method);
      return true;
    }
    if ("org/apache/hadoop/hbase/ipc/IPCUtil".equals(owner)
        && "buildRequestHeader".equals(method.name)
        && Type.getArgumentTypes(method.desc).length == 2
        && method.desc.contains("Lorg/apache/hadoop/hbase/ipc/Call;")) {
      decorateHeader(method);
      return true;
    }
    if ("org/apache/hadoop/hbase/ipc/RpcServer".equals(owner)
        && "call".equals(method.name)
        && method.desc.startsWith("(Lorg/apache/hadoop/hbase/ipc/RpcCall;")) {
      wrapScope(method, "enterServerCall");
      return true;
    }
    if ("org/apache/hadoop/hbase/ipc/RpcConnection".equals(owner)
        && "readResponse".equals(method.name)) {
      return instrumentClientResponse(method);
    }
    if ("org/apache/hadoop/hbase/ipc/AbstractRpcClient".equals(owner)
        && "callBlockingMethod".equals(method.name)) {
      wrapScope(method, "enterBlockingCall", false);
      return true;
    }
    if ("org/apache/hadoop/hbase/master/procedure/MasterProcedureEnv".equals(owner)
        && "<init>".equals(method.name)) {
      registerProcedureSchedulerAfterConstruction(method);
      return true;
    }
    if ("org/apache/hadoop/hbase/procedure2/AbstractProcedureScheduler".equals(owner)
        && "push".equals(method.name)
        && "(Lorg/apache/hadoop/hbase/procedure2/Procedure;ZZ)V".equals(method.desc)) {
      return instrumentProcedureEnqueue(method);
    }
    if ("org/apache/hadoop/hbase/procedure2/AbstractProcedureScheduler".equals(owner)
        && "poll".equals(method.name)
        && "(J)Lorg/apache/hadoop/hbase/procedure2/Procedure;".equals(method.desc)) {
      return instrumentProcedurePoll(method);
    }
    if ("org/apache/hadoop/hbase/master/procedure/MasterProcedureScheduler".equals(owner)
        && "clear".equals(method.name) && "()V".equals(method.desc)) {
      invalidateProcedureQueueAtReturn(method);
      return true;
    }
    if ("org/apache/hadoop/hbase/procedure2/ProcedureExecutor".equals(owner)
        && "executeProcedure".equals(method.name)
        && Type.getArgumentTypes(method.desc).length == 1) {
      wrapScope(method, "enterProcedure");
      return true;
    }
    if ("org/apache/hadoop/hbase/HBaseTestingUtility".equals(owner)
        && ("getConnection".equals(method.name) || "getAdmin".equals(method.name))
        && Type.getArgumentTypes(method.desc).length == 0) {
      registerReturnedClient(method);
      return true;
    }
    if ("org/apache/hadoop/hbase/procedure/ZKProcedureMemberRpcs".equals(owner)
        && "start".equals(method.name)
        && method.desc.startsWith("(Ljava/lang/String;")) {
      InsnList entry = new InsnList();
      entry.add(new VarInsnNode(Opcodes.ALOAD, 0));
      entry.add(new VarInsnNode(Opcodes.ALOAD, 1));
      entry.add(hook("registerZkMember", "(Ljava/lang/Object;Ljava/lang/String;)V"));
      method.instructions.insert(entry);
      return true;
    }
    if ("org/apache/hadoop/hbase/procedure/ZKProcedureCoordinator".equals(owner)
        && "<init>".equals(method.name)
        && method.desc.startsWith("(Lorg/apache/hadoop/hbase/zookeeper/ZKWatcher;Ljava/lang/String;Ljava/lang/String;)")) {
      registerZkCoordinatorAfterConstruction(method);
      return true;
    }
    if ("org/apache/hadoop/hbase/procedure/ProcedureCoordinator".equals(owner)
        && "submitProcedure".equals(method.name)
        && "(Lorg/apache/hadoop/hbase/procedure/Procedure;)Z".equals(method.desc)) {
      return instrumentCoordinatorSubmit(method);
    }
    if (("org/apache/hadoop/hbase/procedure/ZKProcedureMemberRpcs".equals(owner)
        || "org/apache/hadoop/hbase/procedure/ZKProcedureCoordinator".equals(owner))
        && (method.access & Opcodes.ACC_STATIC) == 0
        && entersSelectedRegion(method)) {
      wrapScope(method, "enterZkActor", false);
      return true;
    }
    if ("org/apache/hadoop/hbase/zookeeper/MasterAddressTracker".equals(owner)
        && (method.access & Opcodes.ACC_STATIC) != 0
        && Type.getArgumentTypes(method.desc).length > 0
        && "org/apache/hadoop/hbase/zookeeper/ZKWatcher".equals(
            Type.getArgumentTypes(method.desc)[0].getInternalName())
        && entersSelectedRegion(method)) {
      wrapScope(method, "enterZkWatcher", false);
      return true;
    }
    if (("org/apache/hadoop/hbase/client/ConnectionImplementation".equals(owner)
        || "org/apache/hadoop/hbase/client/HBaseAdmin".equals(owner))
        && (method.access & Opcodes.ACC_STATIC) == 0
        && entersSelectedRegion(method)) {
      wrapScope(method, "enterClientConnection", false);
      return true;
    }
    if (isMasterProcedureClass(owner)
        && (method.access & Opcodes.ACC_STATIC) == 0
        && !"<init>".equals(method.name)
        && Type.getArgumentTypes(method.desc).length > 0
        && Type.getArgumentTypes(method.desc)[0].getSort() == Type.OBJECT
        && "org/apache/hadoop/hbase/master/procedure/MasterProcedureEnv".equals(
            Type.getArgumentTypes(method.desc)[0].getInternalName())
        && entersSelectedRegion(method)) {
      wrapScope(method, "enterMasterEnvironment", true);
      return true;
    }
    if ("org/apache/hadoop/hbase/client/ResultBoundedCompletionService".equals(owner)
        && "submit".equals(method.name)) {
      return instrumentScannerSubmit(method);
    }
    if ("org/apache/hadoop/hbase/client/ResultBoundedCompletionService".equals(owner)
        && ("poll".equals(method.name) || "take".equals(method.name))
        && Type.getReturnType(method.desc).getSort() == Type.OBJECT) {
      return instrumentScannerResult(method);
    }
    if ("org/apache/hadoop/hbase/client/ResultBoundedCompletionService$QueueingFuture".equals(owner)
        && "run".equals(method.name) && "()V".equals(method.desc)) {
      instrumentScannerCompletion(method);
      wrapScope(method, "enterScannerTask", false);
      return true;
    }
    if ("org/apache/hadoop/hbase/HBaseTestingUtility".equals(owner)
        && "startMiniCluster".equals(method.name)
        && Type.getReturnType(method.desc).getInternalName() != null
        && Type.getReturnType(method.desc).getInternalName()
            .equals("org/apache/hadoop/hbase/MiniHBaseCluster")) {
      registerReturnedCluster(method);
      return true;
    }
    return false;
  }

  private static boolean entersSelectedRegion(MethodNode method) {
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (!(instruction instanceof MethodInsnNode)) continue;
      MethodInsnNode call = (MethodInsnNode) instruction;
      if ("edu/uva/liftlab/mallory/instrumentation/Probe".equals(call.owner)
          && "regionEnter".equals(call.name)) return true;
    }
    return false;
  }

  private static void registerZkCoordinatorAfterConstruction(MethodNode method) {
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (instruction.getOpcode() != Opcodes.RETURN) continue;
      InsnList probe = new InsnList();
      probe.add(new VarInsnNode(Opcodes.ALOAD, 0));
      probe.add(new VarInsnNode(Opcodes.ALOAD, 3));
      probe.add(hook("registerZkCoordinator", "(Ljava/lang/Object;Ljava/lang/String;)V"));
      method.instructions.insertBefore(instruction, probe);
    }
  }

  private static void registerMiniClusterActorAfterConstruction(MethodNode method,
                                                                  String registrationHook) {
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (instruction.getOpcode() != Opcodes.RETURN) continue;
      InsnList probe = new InsnList();
      probe.add(new VarInsnNode(Opcodes.ALOAD, 1));
      probe.add(new VarInsnNode(Opcodes.ILOAD, 2));
      probe.add(hook(registrationHook, "(Ljava/lang/Object;I)V"));
      method.instructions.insertBefore(instruction, probe);
    }
  }

  private static void registerProcedureSchedulerAfterConstruction(MethodNode method) {
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (instruction.getOpcode() != Opcodes.RETURN) continue;
      InsnList probe = new InsnList();
      probe.add(new VarInsnNode(Opcodes.ALOAD, 0));
      probe.add(hook("registerProcedureScheduler", "(Ljava/lang/Object;)V"));
      method.instructions.insertBefore(instruction, probe);
    }
  }

  private static boolean instrumentProcedureEnqueue(MethodNode method) {
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (!(instruction instanceof MethodInsnNode)) continue;
      MethodInsnNode call = (MethodInsnNode) instruction;
      if (!"enqueue".equals(call.name)
          || !"(Lorg/apache/hadoop/hbase/procedure2/Procedure;Z)V".equals(call.desc))
        continue;
      InsnList probe = new InsnList();
      probe.add(new VarInsnNode(Opcodes.ALOAD, 0));
      probe.add(new VarInsnNode(Opcodes.ALOAD, 1));
      probe.add(new VarInsnNode(Opcodes.ILOAD, 2));
      probe.add(hook("procedureEnqueued", "(Ljava/lang/Object;Ljava/lang/Object;Z)V"));
      method.instructions.insert(instruction, probe);
      return true;
    }
    return false;
  }

  private static boolean instrumentCoordinatorSubmit(MethodNode method) {
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (!(instruction instanceof MethodInsnNode)) continue;
      MethodInsnNode call = (MethodInsnNode) instruction;
      if (!"java/util/concurrent/ExecutorService".equals(call.owner)
          || !"submit".equals(call.name)
          || !"(Ljava/util/concurrent/Callable;)Ljava/util/concurrent/Future;".equals(call.desc))
        continue;
      // The original stack is [pool, procedure]. Keep pool in place and replace
      // only the Callable argument with an exact token-carrying wrapper.
      InsnList probe = new InsnList();
      probe.add(new VarInsnNode(Opcodes.ALOAD, 0));
      probe.add(new InsnNode(Opcodes.SWAP));
      probe.add(hook("coordinatorCallable",
          "(Ljava/lang/Object;Ljava/util/concurrent/Callable;)Ljava/util/concurrent/Callable;"));
      method.instructions.insertBefore(call, probe);
      return true;
    }
    return false;
  }

  private static boolean instrumentProcedurePoll(MethodNode method) {
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (!(instruction instanceof MethodInsnNode)) continue;
      MethodInsnNode call = (MethodInsnNode) instruction;
      if (!"dequeue".equals(call.name)
          || !"()Lorg/apache/hadoop/hbase/procedure2/Procedure;".equals(call.desc))
        continue;
      // dequeue() still holds the scheduler lock here. Pair before another addFront can race.
      InsnList probe = new InsnList();
      probe.add(new InsnNode(Opcodes.DUP));
      probe.add(new VarInsnNode(Opcodes.ALOAD, 0));
      probe.add(new InsnNode(Opcodes.SWAP));
      probe.add(hook("procedurePolled", "(Ljava/lang/Object;Ljava/lang/Object;)V"));
      method.instructions.insert(instruction, probe);
      return true;
    }
    return false;
  }

  private static void invalidateProcedureQueueAtReturn(MethodNode method) {
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (instruction.getOpcode() != Opcodes.RETURN) continue;
      InsnList probe = new InsnList();
      probe.add(new VarInsnNode(Opcodes.ALOAD, 0));
      probe.add(hook("procedureQueueCleared", "(Ljava/lang/Object;)V"));
      method.instructions.insertBefore(instruction, probe);
    }
  }

  private static void afterConstructor(MethodNode method) {
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (instruction.getOpcode() != Opcodes.RETURN) continue;
      InsnList probe = new InsnList();
      probe.add(new VarInsnNode(Opcodes.ALOAD, 0));
      probe.add(hook("clientCallCreated", "(Ljava/lang/Object;)V"));
      method.instructions.insertBefore(instruction, probe);
    }
  }

  private static void decorateHeader(MethodNode method) {
    String returnType = Type.getReturnType(method.desc).getInternalName();
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (instruction.getOpcode() != Opcodes.ARETURN) continue;
      InsnList probe = new InsnList();
      probe.add(new VarInsnNode(Opcodes.ALOAD, 0));
      probe.add(hook("decorateHeader", "(Ljava/lang/Object;Ljava/lang/Object;)Ljava/lang/Object;"));
      probe.add(new TypeInsnNode(Opcodes.CHECKCAST, returnType));
      method.instructions.insertBefore(instruction, probe);
    }
  }

  private static void registerReturnedCluster(MethodNode method) {
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (instruction.getOpcode() != Opcodes.ARETURN) continue;
      InsnList probe = new InsnList();
      probe.add(new InsnNode(Opcodes.DUP));
      probe.add(hook("registerCluster", "(Ljava/lang/Object;)V"));
      method.instructions.insertBefore(instruction, probe);
    }
  }

  private static void registerReturnedClient(MethodNode method) {
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (instruction.getOpcode() != Opcodes.ARETURN) continue;
      InsnList probe = new InsnList();
      probe.add(new InsnNode(Opcodes.DUP));
      probe.add(hook("registerClient", "(Ljava/lang/Object;)V"));
      method.instructions.insertBefore(instruction, probe);
    }
  }

  private static boolean instrumentScannerSubmit(MethodNode method) {
    boolean changed = false;
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (!(instruction instanceof MethodInsnNode)) continue;
      MethodInsnNode call = (MethodInsnNode) instruction;
      if (!"execute".equals(call.name) || !"(Ljava/lang/Runnable;)V".equals(call.desc))
        continue;
      InsnList probe = new InsnList();
      probe.add(new InsnNode(Opcodes.DUP));
      probe.add(hook("scannerTaskSubmitted", "(Ljava/lang/Object;)V"));
      method.instructions.insertBefore(call, probe);
      changed = true;
    }
    return changed;
  }

  private static boolean instrumentClientResponse(MethodNode method) {
    // `Call call = id2Call.remove(id)` is the unique point after a real response header
    // has been decoded. Local timeouts and connection errors bypass this hook.
    boolean afterRemove = false;
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (instruction instanceof MethodInsnNode) {
        MethodInsnNode call = (MethodInsnNode) instruction;
        if ("java/util/Map".equals(call.owner) && "remove".equals(call.name)
            && "(Ljava/lang/Object;)Ljava/lang/Object;".equals(call.desc)) afterRemove = true;
      } else if (afterRemove && instruction instanceof VarInsnNode
          && instruction.getOpcode() == Opcodes.ASTORE) {
        int slot = ((VarInsnNode) instruction).var;
        InsnList probe = new InsnList();
        probe.add(new VarInsnNode(Opcodes.ALOAD, slot));
        probe.add(hook("clientResponse", "(Ljava/lang/Object;)V"));
        method.instructions.insert(instruction, probe);
        return true;
      }
    }
    return false;
  }

  private static boolean instrumentScannerResult(MethodNode method) {
    boolean changed = false;
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (instruction.getOpcode() != Opcodes.ARETURN) continue;
      InsnList probe = new InsnList();
      probe.add(new InsnNode(Opcodes.DUP));
      probe.add(hook("scannerResultReceived", "(Ljava/lang/Object;)V"));
      method.instructions.insertBefore(instruction, probe);
      changed = true;
    }
    return changed;
  }

  private static void instrumentScannerCompletion(MethodNode method) {
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (!(instruction instanceof MethodInsnNode)) continue;
      MethodInsnNode call = (MethodInsnNode) instruction;
      if (!"notify".equals(call.name) || !"()V".equals(call.desc)) continue;
      InsnList probe = new InsnList();
      probe.add(new VarInsnNode(Opcodes.ALOAD, 0));
      probe.add(hook("scannerTaskCompleted", "(Ljava/lang/Object;)V"));
      method.instructions.insertBefore(call, probe);
    }
  }

  private static void wrapScope(MethodNode method, String entryHook) {
    wrapScope(method, entryHook, true);
  }

  private static void wrapScope(MethodNode method, String entryHook, boolean twoArguments) {
    int scopeLocal = method.maxLocals++;
    LabelNode start = new LabelNode();
    InsnList entry = new InsnList();
    entry.add(new VarInsnNode(Opcodes.ALOAD, 0));
    if (twoArguments) entry.add(new VarInsnNode(Opcodes.ALOAD, 1));
    entry.add(hook(entryHook, "(Ljava/lang/Object;" +
        (twoArguments ? "Ljava/lang/Object;" : "") + ")L" + SCOPE + ";"));
    entry.add(new VarInsnNode(Opcodes.ASTORE, scopeLocal));
    entry.add(start);
    method.instructions.insert(entry);
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      int op = instruction.getOpcode();
      if (op >= Opcodes.IRETURN && op <= Opcodes.RETURN) {
        method.instructions.insertBefore(instruction, close(scopeLocal));
      }
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

  private static MethodInsnNode hook(String method, String descriptor) {
    return new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, method, descriptor, false);
  }

  private static final class SafeWriter extends ClassWriter {
    private final ClassLoader loader;
    SafeWriter(int flags, ClassLoader loader) { super(flags); this.loader = loader; }
    @Override protected String getCommonSuperClass(String a, String b) {
      if (a.equals(b)) return a;
      if (a.startsWith("[") || b.startsWith("[")) return "java/lang/Object";
      try {
        if (assignable(a, b, new HashSet<String>())) return a;
        if (assignable(b, a, new HashSet<String>())) return b;
        ClassReader left = reader(a);
        ClassReader right = reader(b);
        if (left == null || right == null ||
            (left.getAccess() & Opcodes.ACC_INTERFACE) != 0 ||
            (right.getAccess() & Opcodes.ACC_INTERFACE) != 0) return "java/lang/Object";
        String parent = left.getSuperName();
        while (parent != null) {
          if (assignable(parent, b, new HashSet<String>())) return parent;
          ClassReader next = reader(parent);
          parent = next == null ? null : next.getSuperName();
        }
      } catch (IOException ignored) {
        // Missing bytecode means we cannot assert a more specific hierarchy.
      }
      return "java/lang/Object";
    }

    private boolean assignable(String target, String source, Set<String> visited)
        throws IOException {
      if (target.equals(source)) return true;
      if (!visited.add(source)) return false;
      ClassReader current = reader(source);
      if (current == null) return false;
      String parent = current.getSuperName();
      if (parent != null && assignable(target, parent, visited)) return true;
      for (String face : current.getInterfaces())
        if (assignable(target, face, visited)) return true;
      return false;
    }

    private ClassReader reader(String name) throws IOException {
      InputStream resource = loader == null ? null : loader.getResourceAsStream(name + ".class");
      if (resource == null) resource = ClassLoader.getSystemResourceAsStream(name + ".class");
      if (resource == null) return null;
      try {
        return new ClassReader(resource);
      } finally {
        resource.close();
      }
    }
  }
}
