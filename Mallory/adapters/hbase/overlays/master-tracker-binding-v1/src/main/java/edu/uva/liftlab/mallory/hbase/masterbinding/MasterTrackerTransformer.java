package edu.uva.liftlab.mallory.hbase.masterbinding;

import java.lang.instrument.ClassFileTransformer;
import java.security.ProtectionDomain;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.Type;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.InsnList;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.VarInsnNode;

/** One exact entry hook; the existing HBase adapter and target class remain unchanged. */
public final class MasterTrackerTransformer implements ClassFileTransformer {
  private static final String OWNER = "org/apache/hadoop/hbase/master/ActiveMasterManager";
  private static final String HOOKS = Type.getInternalName(MasterTrackerHooks.class);

  @Override public byte[] transform(ClassLoader loader, String className, Class<?> redefining,
                                    ProtectionDomain domain, byte[] original) {
    if (!OWNER.equals(className)) return null;
    try {
      ClassNode owner = new ClassNode();
      new ClassReader(original).accept(owner, 0);
      for (MethodNode method : owner.methods) {
        if (!"getActiveMasterInfoPort".equals(method.name) || !"()I".equals(method.desc))
          continue;
        InsnList entry = new InsnList();
        entry.add(new VarInsnNode(Opcodes.ALOAD, 0));
        entry.add(new MethodInsnNode(Opcodes.INVOKESTATIC, HOOKS,
            "bindWatcherFromManager", "(Ljava/lang/Object;)V", false));
        method.instructions.insert(entry);
        ClassWriter writer = new ClassWriter(ClassWriter.COMPUTE_MAXS);
        owner.accept(writer);
        return writer.toByteArray();
      }
      return null;
    } catch (Throwable failure) {
      System.err.println("Mallory HBase master tracker binding failed: " + failure);
      return null;
    }
  }
}
