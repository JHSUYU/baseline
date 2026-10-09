package research.solr13stage2;

import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.security.ProtectionDomain;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Observe the original routed-alias visibility check and Solr ZooKeeper calls. */
public final class Agent {
  private static final String TARGET =
      "org/apache/solr/cloud/api/collections/RoutedAlias";
  private static final String ZK = "org/apache/solr/common/cloud/SolrZkClient";
  private static final String MAINTAIN =
      "org/apache/solr/cloud/api/collections/MaintainRoutedAliasCmd";
  private static final String PROBE = "research/solr13stage2/Probe";

  private Agent() {}

  public static void premain(String ignored, Instrumentation instrumentation) {
    Probe.initialize();
    instrumentation.addTransformer(new ClassFileTransformer() {
      @Override
      public byte[] transform(ClassLoader loader, String className, Class<?> redefining,
                              ProtectionDomain protection, byte[] original) {
        if (!TARGET.equals(className) && !ZK.equals(className)
            && !MAINTAIN.equals(className)) return null;
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
              if (MAINTAIN.equals(className)) {
                if (name.equals("remoteInvoke") && desc.equals(
                    "(Lorg/apache/solr/handler/admin/CollectionsHandler;"
                    + "Ljava/lang/String;Ljava/lang/String;)V")) {
                  return new MethodVisitor(Opcodes.ASM9, base) {
                    @Override public void visitCode() {
                      super.visitCode();
                      super.visitVarInsn(Opcodes.ALOAD, 1);
                      super.visitVarInsn(Opcodes.ALOAD, 2);
                      super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE,
                          "rpcSend", "(Ljava/lang/String;Ljava/lang/String;)V", false);
                      changed[0] = true;
                    }
                  };
                }
                if (name.equals("call") && desc.equals(
                    "(Lorg/apache/solr/common/cloud/ClusterState;"
                    + "Lorg/apache/solr/common/cloud/ZkNodeProps;"
                    + "Lorg/apache/solr/common/util/NamedList;)V")) {
                  return new MethodVisitor(Opcodes.ASM9, base) {
                    @Override public void visitCode() {
                      super.visitCode();
                      super.visitVarInsn(Opcodes.ALOAD, 2);
                      super.visitLdcInsn("name");
                      super.visitMethodInsn(Opcodes.INVOKEVIRTUAL,
                          "org/apache/solr/common/cloud/ZkNodeProps", "getStr",
                          "(Ljava/lang/String;)Ljava/lang/String;", false);
                      super.visitVarInsn(Opcodes.ALOAD, 2);
                      super.visitLdcInsn("routedAliasTargetCol");
                      super.visitMethodInsn(Opcodes.INVOKEVIRTUAL,
                          "org/apache/solr/common/cloud/ZkNodeProps", "getStr",
                          "(Ljava/lang/String;)Ljava/lang/String;", false);
                      super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE,
                          "overseerReceive", "(Ljava/lang/String;Ljava/lang/String;)V", false);
                      changed[0] = true;
                    }
                  };
                }
                if (name.equals("addCollectionToAlias") && desc.equals(
                    "(Ljava/lang/String;"
                    + "Lorg/apache/solr/common/cloud/ZkStateReader$AliasesManager;"
                    + "Ljava/lang/String;)V")) {
                  return new MethodVisitor(Opcodes.ASM9, base) {
                    @Override public void visitCode() {
                      super.visitCode();
                      super.visitVarInsn(Opcodes.ALOAD, 1);
                      super.visitVarInsn(Opcodes.ALOAD, 3);
                      super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE,
                          "aliasWriteContext", "(Ljava/lang/String;Ljava/lang/String;)V", false);
                      changed[0] = true;
                    }
                  };
                }
                return base;
              }
              if (!"doSynchronous".equals(name) ||
                  !("(Lorg/apache/solr/update/AddUpdateCommand;"
                  + "Lorg/apache/solr/cloud/api/collections/RoutedAlias$CandidateCollection;"
                  + "Lorg/apache/solr/core/CoreContainer;)"
                  + "Lorg/apache/solr/cloud/api/collections/RoutedAlias$CandidateCollection;")
                  .equals(desc)) return base;
              return new MethodVisitor(Opcodes.ASM9, base) {
                int line;

                @Override
                public void visitCode() {
                  super.visitCode();
                  super.visitVarInsn(Opcodes.ALOAD, 0);
                  super.visitMethodInsn(Opcodes.INVOKEVIRTUAL, TARGET,
                      "getAliasName", "()Ljava/lang/String;", false);
                  super.visitVarInsn(Opcodes.ALOAD, 2);
                  super.visitMethodInsn(Opcodes.INVOKEVIRTUAL,
                      TARGET + "$CandidateCollection", "getCreationCollection",
                      "()Ljava/lang/String;", false);
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "targetEnter",
                      "(Ljava/lang/String;Ljava/lang/String;)V", false);
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
                  super.visitMethodInsn(opcode, owner, called, descriptor, isInterface);
                  if (line == 348 && opcode == Opcodes.INVOKEINTERFACE &&
                      owner.equals("java/util/List") &&
                      called.equals("contains") && descriptor.equals("(Ljava/lang/Object;)Z")) {
                    super.visitInsn(Opcodes.DUP);
                    super.visitVarInsn(Opcodes.ALOAD, 0);
                    super.visitMethodInsn(Opcodes.INVOKEVIRTUAL, TARGET,
                        "getAliasName", "()Ljava/lang/String;", false);
                    super.visitVarInsn(Opcodes.ALOAD, 2);
                    super.visitMethodInsn(Opcodes.INVOKEVIRTUAL,
                        TARGET + "$CandidateCollection", "getCreationCollection",
                        "()Ljava/lang/String;", false);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "targetGuard",
                        "(ZLjava/lang/String;Ljava/lang/String;)V", false);
                    changed[0] = true;
                  }
                }

                @Override
                public void visitInsn(int opcode) {
                  if (opcode == Opcodes.ATHROW && line == 350) {
                    super.visitInsn(Opcodes.DUP);
                    super.visitVarInsn(Opcodes.ALOAD, 0);
                    super.visitMethodInsn(Opcodes.INVOKEVIRTUAL, TARGET,
                        "getAliasName", "()Ljava/lang/String;", false);
                    super.visitVarInsn(Opcodes.ALOAD, 2);
                    super.visitMethodInsn(Opcodes.INVOKEVIRTUAL,
                        TARGET + "$CandidateCollection", "getCreationCollection",
                        "()Ljava/lang/String;", false);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "targetThrow",
                        "(Ljava/lang/Throwable;Ljava/lang/String;Ljava/lang/String;)V", false);
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
          System.err.println("SOLR-13 ASM transform failed");
          failure.printStackTrace(System.err);
          throw new IllegalStateException(failure);
        }
      }
    });
  }
}
