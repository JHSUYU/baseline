package edu.uva.liftlab.mallory.hbase.zkmonitor;

import java.io.IOException;
import java.io.InputStream;
import java.lang.instrument.ClassFileTransformer;
import java.security.ProtectionDomain;
import java.util.HashSet;
import java.util.Set;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.Type;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.FieldInsnNode;
import org.objectweb.asm.tree.InsnList;
import org.objectweb.asm.tree.InsnNode;
import org.objectweb.asm.tree.LabelNode;
import org.objectweb.asm.tree.LdcInsnNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.TryCatchBlockNode;
import org.objectweb.asm.tree.VarInsnNode;

/** Add only observed ZKNodeTracker monitor handoffs to the existing HBase adapter. */
public final class TrackerMonitorTransformer implements ClassFileTransformer {
  private static final String TRACKER = "org/apache/hadoop/hbase/zookeeper/ZKNodeTracker";
  private static final String FACTORY = "org/apache/hadoop/hbase/util/JVMClusterUtil";
  private static final String HOOKS = Type.getInternalName(TrackerMonitorHooks.class);
  private static final String SCOPE = Type.getInternalName(TrackerMonitorHooks.Scope.class);
  private static final String FACTORY_SCOPE =
      Type.getInternalName(TrackerMonitorHooks.FactoryScope.class);

  @Override public byte[] transform(ClassLoader loader, String className, Class<?> redefining,
                                    ProtectionDomain domain, byte[] original) {
    if (!TRACKER.equals(className) && !FACTORY.equals(className)) return null;
    try {
      ClassNode owner = new ClassNode();
      new ClassReader(original).accept(owner, ClassReader.EXPAND_FRAMES);
      boolean changed = false;
      for (MethodNode method : owner.methods) {
        if (FACTORY.equals(className)) {
          if ("createRegionServerThread".equals(method.name)
              && method.desc.equals("(Lorg/apache/hadoop/conf/Configuration;Ljava/lang/Class;I)"
                  + "Lorg/apache/hadoop/hbase/util/JVMClusterUtil$RegionServerThread;")) {
            wrapFactory(method, "rs");
            changed = true;
          } else if ("createMasterThread".equals(method.name)
              && method.desc.equals("(Lorg/apache/hadoop/conf/Configuration;Ljava/lang/Class;I)"
                  + "Lorg/apache/hadoop/hbase/util/JVMClusterUtil$MasterThread;")) {
            wrapFactory(method, "master");
            changed = true;
          }
        } else if ("start".equals(method.name) && "()V".equals(method.desc)) {
          wrapCallback(method);
          changed = true;
        } else if ("blockUntilAvailable".equals(method.name) && "(JZ)[B".equals(method.desc)) {
          changed |= instrumentWait(method);
        } else if ("nodeCreated".equals(method.name)
            && "(Ljava/lang/String;)V".equals(method.desc)) {
          changed |= instrumentNotify(method, "hbase:ZKNodeTracker.nodeCreated:data-published");
        } else if ("stop".equals(method.name) && "()V".equals(method.desc)) {
          changed |= instrumentNotify(method, "hbase:ZKNodeTracker.stop");
        } else if ("nodeDeleted".equals(method.name)
            && "(Ljava/lang/String;)V".equals(method.desc)) {
          changed |= instrumentNullWrite(method);
        }
      }
      if (!changed) return null;
      ClassWriter writer = new SafeWriter(ClassWriter.COMPUTE_FRAMES | ClassWriter.COMPUTE_MAXS,
          loader);
      owner.accept(writer);
      return writer.toByteArray();
    } catch (Throwable failure) {
      System.err.println("Mallory HBase ZK tracker overlay failed: " + failure);
      return null;
    }
  }

  private static boolean instrumentWait(MethodNode method) {
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (!(instruction instanceof MethodInsnNode)) continue;
      MethodInsnNode call = (MethodInsnNode) instruction;
      if (!"wait".equals(call.name) || !"(J)V".equals(call.desc)
          || !"java/lang/Object".equals(call.owner)) continue;
      InsnList before = new InsnList();
      before.add(new VarInsnNode(Opcodes.ALOAD, 0));
      before.add(hook("beforeWait", "(Ljava/lang/Object;)V"));
      LabelNode start = new LabelNode();
      before.add(start);
      method.instructions.insertBefore(call, before);
      LabelNode end = new LabelNode();
      InsnList after = new InsnList();
      after.add(end);
      after.add(new VarInsnNode(Opcodes.ALOAD, 0));
      after.add(hook("afterWait", "(Ljava/lang/Object;)Z"));
      after.add(new InsnNode(Opcodes.POP));
      method.instructions.insert(call, after);
      int throwable = method.maxLocals++;
      LabelNode handler = new LabelNode();
      method.instructions.add(handler);
      method.instructions.add(new VarInsnNode(Opcodes.ASTORE, throwable));
      method.instructions.add(new VarInsnNode(Opcodes.ALOAD, 0));
      method.instructions.add(hook("cancelledWait", "(Ljava/lang/Object;)V"));
      method.instructions.add(new VarInsnNode(Opcodes.ALOAD, throwable));
      method.instructions.add(new InsnNode(Opcodes.ATHROW));
      method.tryCatchBlocks.add(0, new TryCatchBlockNode(start, end, handler,
          "java/lang/InterruptedException"));
      return true;
    }
    return false;
  }

  private static boolean instrumentNotify(MethodNode method, String site) {
    boolean changed = false;
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (!(instruction instanceof MethodInsnNode)) continue;
      MethodInsnNode call = (MethodInsnNode) instruction;
      if (!"notifyAll".equals(call.name) || !"()V".equals(call.desc)
          || !"java/lang/Object".equals(call.owner)) continue;
      method.instructions.insert(call, publish(site));
      changed = true;
    }
    if (changed) wrapCallback(method);
    return changed;
  }

  private static boolean instrumentNullWrite(MethodNode method) {
    boolean changed = false;
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (!(instruction instanceof FieldInsnNode)) continue;
      FieldInsnNode field = (FieldInsnNode) instruction;
      if (field.getOpcode() != Opcodes.PUTFIELD || !TRACKER.equals(field.owner)
          || !"data".equals(field.name) || !"[B".equals(field.desc)) continue;
      method.instructions.insert(instruction,
          publish("hbase:ZKNodeTracker.nodeDeleted:data-null"));
      changed = true;
    }
    if (changed) wrapCallback(method);
    return changed;
  }

  private static InsnList publish(String site) {
    InsnList probe = new InsnList();
    probe.add(new VarInsnNode(Opcodes.ALOAD, 0));
    probe.add(new LdcInsnNode(site));
    probe.add(hook("publish", "(Ljava/lang/Object;Ljava/lang/String;)V"));
    return probe;
  }

  private static void wrapCallback(MethodNode method) {
    int local = method.maxLocals++;
    LabelNode start = new LabelNode();
    InsnList entry = new InsnList();
    entry.add(new VarInsnNode(Opcodes.ALOAD, 0));
    entry.add(hook("enterCallback", "(Ljava/lang/Object;)L" + SCOPE + ";"));
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

  private static void wrapFactory(MethodNode method, String role) {
    int local = method.maxLocals++;
    LabelNode start = new LabelNode();
    InsnList entry = new InsnList();
    entry.add(new VarInsnNode(Opcodes.ILOAD, 2));
    entry.add(new LdcInsnNode(role));
    entry.add(hook("enterConstruction", "(ILjava/lang/String;)L" + FACTORY_SCOPE + ";"));
    entry.add(new VarInsnNode(Opcodes.ASTORE, local));
    entry.add(start);
    method.instructions.insert(entry);
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      int op = instruction.getOpcode();
      if (op >= Opcodes.IRETURN && op <= Opcodes.RETURN)
        method.instructions.insertBefore(instruction, close(local, FACTORY_SCOPE));
    }
    LabelNode end = new LabelNode();
    LabelNode handler = new LabelNode();
    method.instructions.add(end);
    method.instructions.add(handler);
    method.instructions.add(close(local, FACTORY_SCOPE));
    method.instructions.add(new InsnNode(Opcodes.ATHROW));
    method.tryCatchBlocks.add(new TryCatchBlockNode(start, end, handler, null));
  }

  private static InsnList close(int local) {
    return close(local, SCOPE);
  }

  private static InsnList close(int local, String scope) {
    InsnList close = new InsnList();
    close.add(new VarInsnNode(Opcodes.ALOAD, local));
    close.add(new MethodInsnNode(Opcodes.INVOKEVIRTUAL, scope, "close", "()V", false));
    return close;
  }

  private static MethodInsnNode hook(String name, String desc) {
    return new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, name, desc, false);
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
      } catch (IOException ignored) { }
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
      InputStream stream = loader == null ? null : loader.getResourceAsStream(name + ".class");
      if (stream == null) stream = ClassLoader.getSystemResourceAsStream(name + ".class");
      if (stream == null) return null;
      try { return new ClassReader(stream); } finally { stream.close(); }
    }
  }
}
