package research.solrcoord;

import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.security.ProtectionDomain;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Observe the original coordinator guard and retry-internal ZooKeeper I/O. */
public final class Agent {
  private static final String TARGET = "org/apache/solr/servlet/CoordinatorHttpSolrCall";
  private static final String ZK = "org/apache/solr/common/cloud/SolrZkClient";
  private static final String PROBE = "research/solrcoord/Probe";

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
              if (!"getCore".equals(name) ||
                  !"(Lorg/apache/solr/servlet/CoordinatorHttpSolrCall$Factory;"
                  .concat("Lorg/apache/solr/servlet/HttpSolrCall;Ljava/lang/String;Z)")
                  .concat("Lorg/apache/solr/core/SolrCore;").equals(desc)) return base;
              return new MethodVisitor(Opcodes.ASM9, base) {
                int line;
                int syntheticLocal = -1;
                boolean pendingSyntheticStore;

                @Override
                public void visitCode() {
                  super.visitCode();
                  super.visitVarInsn(Opcodes.ALOAD, 2);
                  super.visitVarInsn(Opcodes.ALOAD, 1);
                  super.visitFieldInsn(Opcodes.GETFIELD,
                      "org/apache/solr/servlet/HttpSolrCall", "cores",
                      "Lorg/apache/solr/core/CoreContainer;");
                  super.visitMethodInsn(Opcodes.INVOKEVIRTUAL,
                      "org/apache/solr/core/CoreContainer", "getZkController",
                      "()Lorg/apache/solr/cloud/ZkController;", false);
                  super.visitMethodInsn(Opcodes.INVOKEVIRTUAL,
                      "org/apache/solr/cloud/ZkController", "getNodeName",
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
                public void visitVarInsn(int opcode, int index) {
                  super.visitVarInsn(opcode, index);
                  if (pendingSyntheticStore && opcode == Opcodes.ASTORE) {
                    syntheticLocal = index;
                    pendingSyntheticStore = false;
                  }
                  if (line == 138 && opcode == Opcodes.ALOAD &&
                      index == syntheticLocal) {
                    // Copy the original syntheticColl load, identified from
                    // its store after getCollectionOrNull, before the jump.
                    super.visitInsn(Opcodes.DUP);
                    super.visitVarInsn(Opcodes.ALOAD, 2);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "guard",
                        "(Lorg/apache/solr/common/cloud/DocCollection;"
                        + "Ljava/lang/String;)V", false);
                    changed[0] = true;
                  }
                }

                @Override
                public void visitMethodInsn(int opcode, String owner, String called,
                                            String descriptor, boolean isInterface) {
                  if (line == 132 && opcode == Opcodes.INVOKEVIRTUAL &&
                      owner.equals("org/apache/solr/common/cloud/ClusterState") &&
                      called.equals("getCollectionOrNull") &&
                      descriptor.equals("(Ljava/lang/String;)Lorg/apache/solr/common/cloud/DocCollection;"))
                    pendingSyntheticStore = true;
                  super.visitMethodInsn(opcode, owner, called, descriptor, isInterface);
                }

                @Override
                public void visitInsn(int opcode) {
                  if (opcode == Opcodes.ATHROW && (line == 140 || line == 143)) {
                    super.visitInsn(Opcodes.DUP);
                    super.visitVarInsn(Opcodes.ALOAD, 2);
                    super.visitLdcInsn(line);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "targetThrow",
                        "(Ljava/lang/Throwable;Ljava/lang/String;I)V", false);
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
          System.err.println("SOLR coordinator ASM transform failed");
          failure.printStackTrace(System.err);
          throw new IllegalStateException(failure);
        }
      }
    });
  }
}
