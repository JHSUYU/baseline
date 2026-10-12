package edu.uva.liftlab.mallory.hbase.hbckconsume;

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
import org.objectweb.asm.tree.VarInsnNode;

/** Exact bytecode hooks for HBase 2.6.6 future result consumption by scanMeta. */
public final class HbckScannerConsumeTransformer implements ClassFileTransformer {
  private static final String FUTURE =
      "org/apache/hadoop/hbase/client/ResultBoundedCompletionService$QueueingFuture";
  private static final String META = "org/apache/hadoop/hbase/MetaTableAccessor";
  private static final String VISITOR = META + "$Visitor";
  private static final String HOOKS = Type.getInternalName(HbckScannerConsumeHooks.class);
  private static final String SCOPE = "edu/uva/liftlab/mallory/instrumentation/Probe$ContextScope";

  @Override public byte[] transform(ClassLoader loader, String className, Class<?> redefining,
                                    ProtectionDomain domain, byte[] original) {
    if (!FUTURE.equals(className) && !META.equals(className)) return null;
    try {
      ClassNode node = new ClassNode();
      new ClassReader(original).accept(node, ClassReader.EXPAND_FRAMES);
      boolean changed = false;
      for (MethodNode method : node.methods) {
        if (FUTURE.equals(className) && "get".equals(method.name)
            && "()Ljava/lang/Object;".equals(method.desc))
          changed |= instrumentFutureGet(method);
        if (META.equals(className) && "scanMeta".equals(method.name)
            && method.desc.contains("L" + VISITOR + ";"))
          changed |= instrumentVisit(method);
      }
      if (!changed) return null;
      ClassWriter writer = new SafeWriter(ClassWriter.COMPUTE_FRAMES | ClassWriter.COMPUTE_MAXS,
          loader);
      node.accept(writer);
      return writer.toByteArray();
    } catch (Throwable failure) {
      System.err.println("Mallory HBCK scanner consume overlay failed for " + className
          + ": " + failure);
      return null;
    }
  }

  private static boolean instrumentFutureGet(MethodNode method) {
    boolean changed = false;
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (instruction.getOpcode() != Opcodes.ARETURN) continue;
      InsnList probe = new InsnList();
      probe.add(new InsnNode(Opcodes.DUP));
      probe.add(new VarInsnNode(Opcodes.ALOAD, 0));
      probe.add(new InsnNode(Opcodes.SWAP));
      probe.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "futureValueReturned",
          "(Ljava/lang/Object;Ljava/lang/Object;)V", false));
      method.instructions.insertBefore(instruction, probe);
      changed = true;
    }
    return changed;
  }

  private static boolean instrumentVisit(MethodNode method) {
    MethodInsnNode visit = null;
    for (AbstractInsnNode instruction : method.instructions.toArray()) {
      if (!(instruction instanceof MethodInsnNode)) continue;
      MethodInsnNode call = (MethodInsnNode) instruction;
      if (VISITOR.equals(call.owner) && "visit".equals(call.name)
          && "(Lorg/apache/hadoop/hbase/client/Result;)Z".equals(call.desc)) {
        if (visit != null) return false; // refuse an ambiguous implementation variant
        visit = call;
      }
    }
    if (visit == null) return false;
    int row = method.maxLocals++;
    int visitor = method.maxLocals++;
    int scope = method.maxLocals++;
    LabelNode start = new LabelNode();
    LabelNode end = new LabelNode();
    LabelNode handler = new LabelNode();
    LabelNode after = new LabelNode();
    InsnList before = new InsnList();
    // Original stack: [visitor, data]. Keep neither in a thread-local state.
    before.add(new VarInsnNode(Opcodes.ASTORE, row));
    before.add(new VarInsnNode(Opcodes.ASTORE, visitor));
    before.add(new VarInsnNode(Opcodes.ALOAD, row));
    before.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "enterConsumedResult",
        "(Ljava/lang/Object;)L" + SCOPE + ";", false));
    before.add(new VarInsnNode(Opcodes.ASTORE, scope));
    before.add(start);
    before.add(new VarInsnNode(Opcodes.ALOAD, visitor));
    before.add(new VarInsnNode(Opcodes.ALOAD, row));
    method.instructions.insertBefore(visit, before);
    InsnList afterVisit = new InsnList();
    afterVisit.add(end);
    afterVisit.add(new VarInsnNode(Opcodes.ALOAD, scope));
    afterVisit.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "leaveConsumedResult",
        "(L" + SCOPE + ";)V", false));
    afterVisit.add(new org.objectweb.asm.tree.JumpInsnNode(Opcodes.GOTO, after));
    afterVisit.add(handler);
    afterVisit.add(new VarInsnNode(Opcodes.ALOAD, scope));
    afterVisit.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS, "leaveConsumedResult",
        "(L" + SCOPE + ";)V", false));
    afterVisit.add(new InsnNode(Opcodes.ATHROW));
    afterVisit.add(after);
    method.instructions.insert(visit, afterVisit);
    // HBase's try-with-resources handlers also cover this invocation. Our narrower
    // handler must run first so the consumed token cannot leak into scanner cleanup.
    method.tryCatchBlocks.add(0, new TryCatchBlockNode(start, end, handler, null));
    return true;
  }

  private static final class SafeWriter extends ClassWriter {
    private final ClassLoader loader;
    SafeWriter(int flags, ClassLoader loader) { super(flags); this.loader = loader; }
    @Override protected String getCommonSuperClass(String left, String right) {
      if (left.equals(right)) return left;
      if (left.startsWith("[") || right.startsWith("[")) return "java/lang/Object";
      try {
        if (assignable(left, right, new HashSet<String>())) return left;
        if (assignable(right, left, new HashSet<String>())) return right;
        ClassReader current = reader(left);
        ClassReader other = reader(right);
        if (current == null || other == null
            || (current.getAccess() & Opcodes.ACC_INTERFACE) != 0
            || (other.getAccess() & Opcodes.ACC_INTERFACE) != 0) return "java/lang/Object";
        String parent = current.getSuperName();
        while (parent != null) {
          if (assignable(parent, right, new HashSet<String>())) return parent;
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
      InputStream resource = loader == null ? null : loader.getResourceAsStream(name + ".class");
      if (resource == null) resource = ClassLoader.getSystemResourceAsStream(name + ".class");
      if (resource == null) return null;
      try { return new ClassReader(resource); }
      finally { resource.close(); }
    }
  }
}
