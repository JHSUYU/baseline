package research.solrsplitnative;

import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.security.ProtectionDomain;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Inject within SolrZkClient's retry lambda, at the underlying keeper call. */
public final class Agent {
  private static final String TARGET = "org/apache/solr/cloud/api/collections/SplitShardCmd";
  private static final String ZK = "org/apache/solr/common/cloud/SolrZkClient";
  private static final String PROBE = "research/solrsplitnative/Probe";
  private static final String EXISTS_DESC = "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Z)Lorg/apache/zookeeper/data/Stat;";

  private Agent() {}

  public static void premain(String ignored, Instrumentation instrumentation) {
    Probe.initialize();
    instrumentation.addTransformer(new ClassFileTransformer() {
      @Override
      public byte[] transform(ClassLoader loader, String className, Class<?> redefining,
                              ProtectionDomain protection, byte[] original) {
        if (!TARGET.equals(className) && !ZK.equals(className)) return null;
        try {
          final boolean[] changed = {false};
          ClassReader reader = new ClassReader(original);
          ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_FRAMES);
          ClassVisitor visitor = new ClassVisitor(Opcodes.ASM9, writer) {
            @Override
            public MethodVisitor visitMethod(int access, String name, String desc,
                                             String signature, String[] exceptions) {
              MethodVisitor base = super.visitMethod(access, name, desc, signature, exceptions);
              if (base == null) return null;
              if (ZK.equals(className)) {
                if (!desc.startsWith("(Ljava/lang/String;") ||
                    !(name.startsWith("lambda$exists$") ||
                      name.startsWith("lambda$getChildren$") ||
                      name.startsWith("lambda$getData$") ||
                      name.startsWith("lambda$setData$"))) return base;
                return new MethodVisitor(Opcodes.ASM9, base) {
                  @Override
                  public void visitCode() {
                    super.visitCode();
                    super.visitVarInsn(Opcodes.ALOAD, 1);
                    super.visitLdcInsn(name + desc);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "nativeEntry",
                        "(Ljava/lang/String;Ljava/lang/String;)V", false);
                    changed[0] = true;
                  }
                };
              }
              if (!"split".equals(name) || !desc.endsWith(")Z")) return base;
              return new MethodVisitor(Opcodes.ASM9, base) {
                int line;
                int existsCall;

                @Override
                public void visitCode() {
                  super.visitCode();
                  super.visitVarInsn(Opcodes.ALOAD, 2);
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "splitEnter",
                      "(Lorg/apache/solr/common/cloud/ZkNodeProps;)V", false);
                  changed[0] = true;
                }

                @Override
                public void visitLineNumber(int number, Label start) {
                  line = number;
                  super.visitLineNumber(number, start);
                  if (number == 165 || number == 524 || number == 536 || number == 539) {
                    super.visitLdcInsn(number);
                    super.visitVarInsn(Opcodes.ALOAD, 2);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "guard",
                        "(ILorg/apache/solr/common/cloud/ZkNodeProps;)V", false);
                    changed[0] = true;
                  }
                }

                @Override
                public void visitMethodInsn(int opcode, String owner, String called,
                                            String descriptor, boolean isInterface) {
                  if (opcode == Opcodes.INVOKEVIRTUAL && ZK.equals(owner)
                      && "exists".equals(called) && EXISTS_DESC.equals(descriptor)) {
                    existsCall++;
                    String site = TARGET.replace('/', '.') + ".split#exists" + existsCall
                        + "@line" + line;
                    super.visitVarInsn(Opcodes.ALOAD, 2);
                    super.visitLdcInsn(site);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "exists",
                        "(Lorg/apache/solr/common/cloud/SolrZkClient;Ljava/lang/String;"
                        + "Lorg/apache/zookeeper/Watcher;ZLorg/apache/solr/common/cloud/ZkNodeProps;Ljava/lang/String;)"
                        + "Lorg/apache/zookeeper/data/Stat;", false);
                    changed[0] = true;
                  } else {
                    super.visitMethodInsn(opcode, owner, called, descriptor, isInterface);
                  }
                }

                @Override
                public void visitInsn(int opcode) {
                  if (opcode == Opcodes.ATHROW && (line == 167 || line == 538 || line == 543)) {
                    super.visitInsn(Opcodes.DUP);
                    super.visitVarInsn(Opcodes.ALOAD, 2);
                    super.visitLdcInsn(line);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "targetThrow",
                        "(Ljava/lang/Throwable;Lorg/apache/solr/common/cloud/ZkNodeProps;I)V", false);
                    changed[0] = true;
                  }
                  super.visitInsn(opcode);
                }
              };
            }
          };
          reader.accept(visitor, ClassReader.EXPAND_FRAMES);
          return changed[0] ? writer.toByteArray() : null;
        } catch (Throwable failure) {
          System.err.println("SOLR native split ASM transform failed");
          failure.printStackTrace(System.err);
          throw new IllegalStateException(failure);
        }
      }
    });
  }
}
