package research.solrleadership;

import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.security.ProtectionDomain;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Exact final leader-identity guard and real Solr ZooKeeper retry-call I/O. */
public final class Agent {
  private static final String TARGET =
      "org/apache/solr/update/processor/DistributedZkUpdateProcessor";
  private static final String ZK = "org/apache/solr/common/cloud/SolrZkClient";
  private static final String PROBE = "research/solrleadership/Probe";

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
                      name.startsWith("lambda$setData$") ||
                      name.startsWith("lambda$create$") ||
                      name.startsWith("lambda$delete$") ||
                      name.startsWith("lambda$makePath$"))) return base;
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
              if (!"doDefensiveChecks".equals(name) ||
                  !"(Lorg/apache/solr/update/processor/DistributedUpdateProcessor$DistribPhase;)V"
                  .equals(desc)) return base;
              return new MethodVisitor(Opcodes.ASM9, base) {
                int line;

                @Override
                public void visitCode() {
                  super.visitCode();
                  super.visitVarInsn(Opcodes.ALOAD, 0);
                  super.visitFieldInsn(Opcodes.GETFIELD, TARGET, "collection", "Ljava/lang/String;");
                  super.visitVarInsn(Opcodes.ALOAD, 0);
                  super.visitFieldInsn(Opcodes.GETFIELD, TARGET, "cloudDesc",
                      "Lorg/apache/solr/cloud/CloudDescriptor;");
                  super.visitMethodInsn(Opcodes.INVOKEVIRTUAL,
                      "org/apache/solr/cloud/CloudDescriptor", "getShardId",
                      "()Ljava/lang/String;", false);
                  super.visitVarInsn(Opcodes.ALOAD, 0);
                  super.visitFieldInsn(Opcodes.GETFIELD, TARGET, "cloudDesc",
                      "Lorg/apache/solr/cloud/CloudDescriptor;");
                  super.visitMethodInsn(Opcodes.INVOKEVIRTUAL,
                      "org/apache/solr/cloud/CloudDescriptor", "getCoreNodeName",
                      "()Ljava/lang/String;", false);
                  super.visitVarInsn(Opcodes.ALOAD, 0);
                  super.visitFieldInsn(Opcodes.GETFIELD, TARGET, "zkController",
                      "Lorg/apache/solr/cloud/ZkController;");
                  super.visitMethodInsn(Opcodes.INVOKEVIRTUAL,
                      "org/apache/solr/cloud/ZkController", "getNodeName",
                      "()Ljava/lang/String;", false);
                  super.visitVarInsn(Opcodes.ALOAD, 1);
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "targetEnter",
                      "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;"
                      + "Ljava/lang/String;Ljava/lang/Object;)V", false);
                  changed[0] = true;
                }

                @Override
                public void visitLineNumber(int number, Label start) {
                  line = number;
                  super.visitLineNumber(number, start);
                  if (number == 1021) {
                    super.visitVarInsn(Opcodes.ALOAD, 0);
                    super.visitFieldInsn(Opcodes.GETFIELD, TARGET, "isLeader", "Z");
                    super.visitVarInsn(Opcodes.ALOAD, 0);
                    super.visitFieldInsn(Opcodes.GETFIELD, TARGET, "isSubShardLeader", "Z");
                    super.visitVarInsn(Opcodes.ILOAD, 6);
                    super.visitVarInsn(Opcodes.ILOAD, 7);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "leaderCheck",
                        "(ZZZI)V", false);
                    changed[0] = true;
                  }
                }

                @Override
                public void visitInsn(int opcode) {
                  if (opcode == Opcodes.ATHROW && line == 1025) {
                    super.visitInsn(Opcodes.DUP);
                    super.visitLdcInsn(line);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "targetThrow",
                        "(Ljava/lang/Throwable;I)V", false);
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
          System.err.println("SOLR leader-identity target ASM transform failed");
          failure.printStackTrace(System.err);
          throw new IllegalStateException(failure);
        }
      }
    });
  }
}
