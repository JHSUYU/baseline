package edu.uva.liftlab.mallory.solr.solr39;

import edu.uva.liftlab.mallory.solr.shaded.asm.ClassReader;
import edu.uva.liftlab.mallory.solr.shaded.asm.ClassVisitor;
import edu.uva.liftlab.mallory.solr.shaded.asm.ClassWriter;
import edu.uva.liftlab.mallory.solr.shaded.asm.MethodVisitor;
import edu.uva.liftlab.mallory.solr.shaded.asm.Opcodes;
import java.lang.instrument.ClassFileTransformer;
import java.security.ProtectionDomain;

/** Last transformer: wrap the exact Probe call with the real getData operands. */
public final class PreemptiveTransformer implements ClassFileTransformer {
  private static final String MANAGER = "org/apache/solr/common/cloud/ZkStateReader$AliasesManager";
  private static final String PROBE = "edu/uva/liftlab/mallory/instrumentation/Probe";
  private static final String GATE = "edu/uva/liftlab/mallory/solr/solr39/PreemptiveGate";
  private static final String DOOR = "org.apache.solr.common.cloud.ZkStateReader$AliasesManager#process"
      + "(Lorg/apache/zookeeper/WatchedEvent;)V@2312:door:1";
  private static final String GETTER = "()Lorg/apache/solr/common/cloud/Aliases;";

  @Override public byte[] transform(ClassLoader loader, String name, Class<?> redefined,
      ProtectionDomain domain, byte[] bytes) {
    if (!MANAGER.equals(name)) return null;
    ClassReader reader = new ClassReader(bytes);
    ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
    final int[] gates = {0};
    ClassVisitor visitor = new ClassVisitor(Opcodes.ASM9, writer) {
      @Override public MethodVisitor visitMethod(int access, String method, String descriptor,
          String signature, String[] exceptions) {
        MethodVisitor output = super.visitMethod(access, method, descriptor, signature, exceptions);
        if (output == null) return null;
        if ("setIfNewer".equals(method)
            && "(Lorg/apache/solr/common/cloud/Aliases;)Z".equals(descriptor)) {
          return new MethodVisitor(Opcodes.ASM9, output) {
            @Override public void visitInsn(int opcode) {
              if (opcode == Opcodes.IRETURN) {
                super.visitInsn(Opcodes.DUP);
                super.visitVarInsn(Opcodes.ALOAD, 0);
                super.visitMethodInsn(Opcodes.INVOKESTATIC, GATE, "published",
                    "(ZLjava/lang/Object;)V", false);
              }
              super.visitInsn(opcode);
            }
          };
        }
        if ("getAliases".equals(method) && GETTER.equals(descriptor)) {
          return new MethodVisitor(Opcodes.ASM9, output) {
            @Override public void visitInsn(int opcode) {
              if (opcode == Opcodes.ARETURN) {
                super.visitInsn(Opcodes.DUP);
                super.visitVarInsn(Opcodes.ALOAD, 0);
                super.visitMethodInsn(Opcodes.INVOKESTATIC, GATE, "read",
                    "(Ljava/lang/Object;Ljava/lang/Object;)V", false);
              }
              super.visitInsn(opcode);
            }
          };
        }
        if (!"process".equals(method)
            || !"(Lorg/apache/zookeeper/WatchedEvent;)V".equals(descriptor)) return output;
        return new MethodVisitor(Opcodes.ASM9, output) {
          private String previousString;
          private String latestString;
          @Override public void visitLdcInsn(Object constant) {
            if (constant instanceof String) {
              previousString = latestString;
              latestString = (String) constant;
            }
            super.visitLdcInsn(constant);
          }
          @Override public void visitMethodInsn(int opcode, String owner, String methodName,
              String desc, boolean itf) {
            if (opcode == Opcodes.INVOKESTATIC && PROBE.equals(owner)
                && "beforeDoor".equals(methodName)
                && "(Ljava/lang/String;Ljava/lang/String;)V".equals(desc)
                && DOOR.equals(previousString)) {
              // Stack at the core Probe call:
              // SolrZkClient, actual path, Watcher, Stat, boolean, site, exception.
              // Save all seven operands, call the gate with the actual path,
              // then restore getData's five original operands exactly.
              super.visitVarInsn(Opcodes.ASTORE, 70); // exception
              super.visitVarInsn(Opcodes.ASTORE, 69); // site
              super.visitVarInsn(Opcodes.ISTORE, 68); // boolean
              super.visitVarInsn(Opcodes.ASTORE, 67); // Stat
              super.visitVarInsn(Opcodes.ASTORE, 66); // Watcher
              super.visitVarInsn(Opcodes.ASTORE, 65); // actual path
              super.visitVarInsn(Opcodes.ASTORE, 64); // SolrZkClient
              super.visitVarInsn(Opcodes.ALOAD, 0);   // actual AliasesManager
              super.visitVarInsn(Opcodes.ALOAD, 65);
              super.visitVarInsn(Opcodes.ALOAD, 69);
              super.visitVarInsn(Opcodes.ALOAD, 70);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, GATE, "beforeDoor",
                  "(Ljava/lang/Object;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)V", false);
              super.visitVarInsn(Opcodes.ALOAD, 64);
              super.visitVarInsn(Opcodes.ALOAD, 65);
              super.visitVarInsn(Opcodes.ALOAD, 66);
              super.visitVarInsn(Opcodes.ALOAD, 67);
              super.visitVarInsn(Opcodes.ILOAD, 68);
              gates[0]++;
              return;
            }
            previousString = null;
            latestString = null;
            super.visitMethodInsn(opcode, owner, methodName, desc, itf);
          }
        };
      }
    };
    reader.accept(visitor, 0);
    if (gates[0] != 1) throw new IllegalStateException("SOLR-39 selected getData gate count " + gates[0]);
    return writer.toByteArray();
  }
}
