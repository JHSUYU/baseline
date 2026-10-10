package edu.uva.liftlab.mallory.hbase.tokenmanager;

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

/** Entry and exit scope for the exact token-check receiver, including SASL event-loop calls. */
public final class TokenManagerActorTransformer implements ClassFileTransformer {
  private static final String OWNER =
      "org/apache/hadoop/hbase/security/token/AuthenticationTokenSecretManager";
  private static final String METHOD = "retrievePassword";
  private static final String DESCRIPTOR =
      "(Lorg/apache/hadoop/hbase/security/token/AuthenticationTokenIdentifier;)[B";
  private static final String HOOKS = Type.getInternalName(TokenManagerActorHooks.class);
  private static final String SCOPE = "edu/uva/liftlab/mallory/instrumentation/Probe$NodeScope";

  @Override public byte[] transform(ClassLoader loader, String className, Class<?> redefining,
                                    ProtectionDomain domain, byte[] original) {
    if (!OWNER.equals(className)) return null;
    try {
      ClassNode owner = new ClassNode();
      new ClassReader(original).accept(owner, ClassReader.EXPAND_FRAMES);
      for (MethodNode method : owner.methods) {
        if (!METHOD.equals(method.name) || !DESCRIPTOR.equals(method.desc)) continue;
        scope(method);
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
      }
      throw new IllegalStateException("Exact HBase 2.6.6 retrievePassword method missing");
    } catch (Throwable failure) {
      System.err.println("Mallory token manager actor binding failed: " + failure);
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
