package research.solrreload;

import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.security.ProtectionDomain;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Exact original CoreContainer.reload assertion recorder, without test edits. */
public final class Agent {
  private static final String TARGET = "org/apache/solr/core/CoreContainer";
  private static final String ZK = "org/apache/solr/common/cloud/SolrZkClient";
  private static final String PROPERTIES = "org/apache/solr/core/CorePropertiesLocator";
  private static final String PROBE = "research/solrreload/Probe";

  private Agent() {}

  public static void premain(String ignored, Instrumentation instrumentation) {
    Probe.initialize();
    instrumentation.addTransformer(new ClassFileTransformer() {
      @Override
      public byte[] transform(ClassLoader loader, String className, Class<?> redefining,
                              ProtectionDomain protection, byte[] original) {
        if (!TARGET.equals(className) && !ZK.equals(className)
            && !PROPERTIES.equals(className)) return null;
        try {
          final boolean[] changed = {false};
          ClassReader reader = new ClassReader(original);
          ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_FRAMES);
          ClassVisitor visitor = new ClassVisitor(Opcodes.ASM9, writer) {
            @Override
            public MethodVisitor visitMethod(int access, String name, String desc,
                                             String signature, String[] exceptions) {
              MethodVisitor base = super.visitMethod(access, name, desc, signature, exceptions);
              if (ZK.equals(className) && base != null) {
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
              if (PROPERTIES.equals(className) && base != null) {
                if (!"buildCoreDescriptor".equals(name) ||
                    !"(Ljava/nio/file/Path;Lorg/apache/solr/core/CoreContainer;)"
                    .concat("Lorg/apache/solr/core/CoreDescriptor;").equals(desc)) return base;
                return new MethodVisitor(Opcodes.ASM9, base) {
                  int line;

                  @Override
                  public void visitLineNumber(int number, Label start) {
                    line = number;
                    super.visitLineNumber(number, start);
                  }

                  @Override
                  public void visitMethodInsn(int opcode, String owner, String called,
                                              String descriptor, boolean isInterface) {
                    if (line == 187 && opcode == Opcodes.INVOKESTATIC
                        && owner.equals("java/nio/file/Files")
                        && called.equals("newInputStream")) {
                      // Stack: Path, OpenOption[]. Pass the same Path to the probe.
                      super.visitInsn(Opcodes.DUP2);
                      super.visitInsn(Opcodes.POP);
                      super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "fileRead",
                          "(Ljava/nio/file/Path;)V", false);
                      changed[0] = true;
                    }
                    super.visitMethodInsn(opcode, owner, called, descriptor, isInterface);
                  }
                };
              }
              if (base == null || !"reload".equals(name) ||
                  !"(Ljava/lang/String;Ljava/util/UUID;)V".equals(desc)) return base;
              return new MethodVisitor(Opcodes.ASM9, base) {
                int line;
                int lastAload = -1;
                int descriptorLocal = -1;
                int replicaLocal = -1;
                boolean pendingReplicaStore;

                @Override
                public void visitCode() {
                  super.visitCode();
                  super.visitVarInsn(Opcodes.ALOAD, 1);
                  super.visitVarInsn(Opcodes.ALOAD, 2);
                  super.visitVarInsn(Opcodes.ALOAD, 0);
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "targetEnter",
                      "(Ljava/lang/String;Ljava/util/UUID;Lorg/apache/solr/core/CoreContainer;)V",
                      false);
                  changed[0] = true;
                }

                @Override
                public void visitLineNumber(int number, Label start) {
                  line = number;
                  super.visitLineNumber(number, start);
                  if (number == 1765) {
                    if (descriptorLocal < 0 || replicaLocal < 0)
                      throw new IllegalStateException("reload assertion locals not resolved");
                    super.visitVarInsn(Opcodes.ALOAD, replicaLocal);
                    super.visitVarInsn(Opcodes.ALOAD, descriptorLocal);
                    super.visitVarInsn(Opcodes.ALOAD, 0);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "guard",
                        "(Lorg/apache/solr/common/cloud/Replica;"
                        + "Lorg/apache/solr/core/CoreDescriptor;"
                        + "Lorg/apache/solr/core/CoreContainer;)V", false);
                    changed[0] = true;
                  }
                }

                @Override
                public void visitVarInsn(int opcode, int index) {
                  if (opcode == Opcodes.ALOAD) lastAload = index;
                  if (pendingReplicaStore && opcode == Opcodes.ASTORE) {
                    replicaLocal = index;
                    pendingReplicaStore = false;
                  }
                  super.visitVarInsn(opcode, index);
                }

                @Override
                public void visitMethodInsn(int opcode, String owner, String called,
                                            String descriptor, boolean isInterface) {
                  if (line == 1764 && opcode == Opcodes.INVOKEVIRTUAL
                      && owner.equals("org/apache/solr/core/CoreDescriptor")
                      && called.equals("getCloudDescriptor")) {
                    descriptorLocal = lastAload;
                  }
                  if (line == 1764 && opcode == Opcodes.INVOKEVIRTUAL
                      && owner.equals("org/apache/solr/common/cloud/DocCollection")
                      && called.equals("getReplica")) {
                    pendingReplicaStore = true;
                  }
                  super.visitMethodInsn(opcode, owner, called, descriptor, isInterface);
                }

                @Override
                public void visitInsn(int opcode) {
                  if (opcode == Opcodes.ATHROW && line == 1765) {
                    super.visitInsn(Opcodes.DUP);
                    super.visitVarInsn(Opcodes.ALOAD, descriptorLocal);
                    super.visitVarInsn(Opcodes.ALOAD, 0);
                    super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "targetThrow",
                        "(Ljava/lang/Throwable;Lorg/apache/solr/core/CoreDescriptor;"
                        + "Lorg/apache/solr/core/CoreContainer;)V", false);
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
          System.err.println("SOLR reload target ASM transform failed");
          failure.printStackTrace(System.err);
          throw new IllegalStateException(failure);
        }
      }
    });
  }
}
