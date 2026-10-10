package edu.uva.liftlab.mallory.solr.aliasref;

import edu.uva.liftlab.mallory.solr.shaded.asm.ClassReader;
import edu.uva.liftlab.mallory.solr.shaded.asm.ClassVisitor;
import edu.uva.liftlab.mallory.solr.shaded.asm.ClassWriter;
import edu.uva.liftlab.mallory.solr.shaded.asm.MethodVisitor;
import edu.uva.liftlab.mallory.solr.shaded.asm.Opcodes;
import java.lang.instrument.ClassFileTransformer;
import java.security.ProtectionDomain;

/** Case-local supplement to the pinned v38 Solr adapter. */
public final class AliasValueTransformer implements ClassFileTransformer {
  private static final String MANAGER = "org/apache/solr/common/cloud/ZkStateReader$AliasesManager";
  private static final String ALIASES = "Lorg/apache/solr/common/cloud/Aliases;";
  private static final String TRACE = "edu/uva/liftlab/mallory/solr/aliasref/AliasValueTrace";

  @Override
  public byte[] transform(ClassLoader loader, String name, Class<?> redefined,
      ProtectionDomain domain, byte[] bytes) {
    if (!MANAGER.equals(name)) return null;
    try {
      ClassReader reader = new ClassReader(bytes);
      ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
      ClassVisitor visitor = new ClassVisitor(Opcodes.ASM9, writer) {
        @Override public MethodVisitor visitMethod(int access, String method, String descriptor,
            String signature, String[] exceptions) {
          MethodVisitor delegate = super.visitMethod(access, method, descriptor, signature, exceptions);
          if (delegate == null) return null;
          final boolean read = "getAliases".equals(method) && ("()" + ALIASES).equals(descriptor);
          final boolean write = "setIfNewer".equals(method) && ("(" + ALIASES + ")Z").equals(descriptor);
          if (!read && !write) return delegate;
          return new MethodVisitor(Opcodes.ASM9, delegate) {
            @Override public void visitFieldInsn(int opcode, String owner, String field,
                String fieldDescriptor) {
              if (!MANAGER.equals(owner) || !"aliases".equals(field)
                  || !ALIASES.equals(fieldDescriptor)) {
                super.visitFieldInsn(opcode, owner, field, fieldDescriptor);
                return;
              }
              if (read && opcode == Opcodes.GETFIELD) {
                // owner -> owner,owner -> owner,value -> value,owner,value
                super.visitInsn(Opcodes.DUP);
                super.visitFieldInsn(opcode, owner, field, fieldDescriptor);
                super.visitInsn(Opcodes.DUP_X1);
                super.visitMethodInsn(Opcodes.INVOKESTATIC, TRACE, "read",
                    "(Ljava/lang/Object;Ljava/lang/Object;)V", false);
              } else if (write && opcode == Opcodes.PUTFIELD) {
                // Keep the exact reference consumed by the volatile write.
                super.visitInsn(Opcodes.DUP2);
                super.visitFieldInsn(opcode, owner, field, fieldDescriptor);
                super.visitMethodInsn(Opcodes.INVOKESTATIC, TRACE, "write",
                    "(Ljava/lang/Object;Ljava/lang/Object;)V", false);
              } else {
                super.visitFieldInsn(opcode, owner, field, fieldDescriptor);
              }
            }
          };
        }
      };
      reader.accept(visitor, 0);
      return writer.toByteArray();
    } catch (Throwable error) {
      System.err.println("MALLORY_ALIAS_REF_TRANSFORM_ERROR " + error);
      return null;
    }
  }
}
