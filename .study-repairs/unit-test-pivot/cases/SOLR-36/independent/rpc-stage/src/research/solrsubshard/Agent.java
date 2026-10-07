package research.solrsubshard;

import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.security.ProtectionDomain;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Exact guards of the original parent-forwarding defensive checks. */
public final class Agent {
  private static final String TARGET =
      "org/apache/solr/update/processor/DistributedZkUpdateProcessor";
  private static final String ZK = "org/apache/solr/common/cloud/SolrZkClient";
  private static final String RPC = "org/apache/solr/update/SolrCmdDistributor";
  private static final String PROBE = "research/solrsubshard/Probe";

  private Agent() {}

  public static void premain(String ignored, Instrumentation instrumentation) {
    Probe.initialize();
    instrumentation.addTransformer(new ClassFileTransformer() {
      @Override
      public byte[] transform(ClassLoader loader, String className, Class<?> redefining,
                              ProtectionDomain protection, byte[] original) {
        if (!TARGET.equals(className) && !ZK.equals(className)
            && !RPC.equals(className)) return null;
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
              if (RPC.equals(className)) {
                if (!"submit".equals(name) ||
                    !"(Lorg/apache/solr/update/SolrCmdDistributor$Req;Z)V"
                        .equals(desc)) return base;
                return new MethodVisitor(Opcodes.ASM9, base) {
                  @Override
                  public void visitMethodInsn(int opcode, String owner, String called,
                                              String descriptor, boolean isInterface) {
                    if (opcode == Opcodes.INVOKEVIRTUAL
                        && "org/apache/solr/client/solrj/impl/Http2SolrClient".equals(owner)
                        && "request".equals(called)) {
                      // The original client and request are already on the stack.
                      // Observe and fault immediately before the real HTTP call.
                      super.visitVarInsn(Opcodes.ALOAD, 1);
                      super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "rpcSend",
                          "(Lorg/apache/solr/update/SolrCmdDistributor$Req;)V", false);
                      changed[0] = true;
                    }
                    super.visitMethodInsn(opcode, owner, called, descriptor, isInterface);
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
                }

                @Override
                public void visitMethodInsn(int opcode, String owner, String called,
                                            String descriptor, boolean isInterface) {
                  if (line == 994 && opcode == Opcodes.INVOKEVIRTUAL &&
                      owner.equals("org/apache/solr/common/cloud/DocRouter$Range") &&
                      called.equals("isSubsetOf")) {
                    super.visitInsn(Opcodes.DUP2);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "rangeOperands",
                        "(Lorg/apache/solr/common/cloud/DocRouter$Range;"
                        + "Lorg/apache/solr/common/cloud/DocRouter$Range;)V", false);
                  }
                  super.visitMethodInsn(opcode, owner, called, descriptor, isInterface);
                  if (line == 986 && opcode == Opcodes.INVOKEVIRTUAL &&
                      owner.equals("org/apache/solr/common/cloud/Slice") &&
                      called.equals("getState")) {
                    super.visitInsn(Opcodes.DUP);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "guard36",
                        "(Lorg/apache/solr/common/cloud/Slice$State;)V", false);
                    changed[0] = true;
                  }
                  if (line == 994 && opcode == Opcodes.INVOKEVIRTUAL &&
                      owner.equals("org/apache/solr/common/cloud/DocRouter$Range") &&
                      called.equals("isSubsetOf")) {
                    super.visitInsn(Opcodes.DUP);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "guard37",
                        "(Z)V", false);
                    changed[0] = true;
                  }
                }

                @Override
                public void visitInsn(int opcode) {
                  if (opcode == Opcodes.ATHROW && (line == 987 || line == 995)) {
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
          System.err.println("SOLR subshard target ASM transform failed");
          failure.printStackTrace(System.err);
          throw new IllegalStateException(failure);
        }
      }
    });
  }
}
