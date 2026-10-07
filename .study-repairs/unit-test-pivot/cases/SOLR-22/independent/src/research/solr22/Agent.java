package research.solr22;

import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.security.ProtectionDomain;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Case-local ASM probes; no GraphChecker classes, scope maps, or region skeletons. */
public final class Agent {
  private static final String PROBE = "research/solr22/Probe";
  private static final String POLICY = "org/apache/solr/core/IndexDeletionPolicyWrapper";
  private static final String DIR = "org/apache/lucene/store/Directory";
  private static final String CONTEXT = "org/apache/lucene/store/IOContext";

  private Agent() {}

  public static void premain(String ignored, Instrumentation instrumentation) {
    Probe.initialize();
    instrumentation.addTransformer(new Transformer());
  }

  private static final class Transformer implements ClassFileTransformer {
    @Override
    public byte[] transform(ClassLoader loader, String className, Class<?> redefining,
                            ProtectionDomain protection, byte[] original) {
      if (className == null || !(className.startsWith("org/apache/solr/")
          || className.startsWith("org/apache/lucene/"))) return null;
      try {
        final boolean[] changed = {false};
        ClassReader reader = new ClassReader(original);
        ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_MAXS);
        ClassVisitor visitor = new ClassVisitor(Opcodes.ASM9, writer) {
          @Override
          public MethodVisitor visitMethod(int access, String name, String desc,
                                           String signature, String[] exceptions) {
            MethodVisitor base = super.visitMethod(access, name, desc, signature, exceptions);
            if (base == null) return null;
            boolean target = POLICY.equals(className)
                && "getAndSaveCommitPoint".equals(name)
                && "(Ljava/lang/Long;)Lorg/apache/lucene/index/IndexCommit;".equals(desc);
            boolean onCommit = POLICY.equals(className)
                && "onCommit".equals(name)
                && "(Ljava/util/List;)V".equals(desc);
            boolean directoryFactoryGet = "org/apache/solr/core/CachingDirectoryFactory".equals(className)
                && "get".equals(name)
                && desc.startsWith("(Ljava/lang/String;Lorg/apache/solr/core/DirectoryFactory$DirContext;")
                && desc.endsWith(")Lorg/apache/lucene/store/Directory;");
            boolean policyGet = "org/apache/solr/core/SolrCore".equals(className)
                && "getDeletionPolicy".equals(name)
                && "()Lorg/apache/solr/core/IndexDeletionPolicyWrapper;".equals(desc);
            return new MethodVisitor(Opcodes.ASM9, base) {
              int invocation = 0;
              boolean checkInserted = false;

              @Override
              public void visitCode() {
                super.visitCode();
                if (target) {
                  super.visitVarInsn(Opcodes.ALOAD, 0);
                  super.visitVarInsn(Opcodes.ALOAD, 1);
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "targetEnter",
                      "(Ljava/lang/Object;Ljava/lang/Long;)V", false);
                  changed[0] = true;
                } else if (onCommit) {
                  super.visitVarInsn(Opcodes.ALOAD, 0);
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "onCommitEnter",
                      "(Ljava/lang/Object;)V", false);
                  changed[0] = true;
                }
              }

              @Override
              public void visitLineNumber(int line, Label label) {
                super.visitLineNumber(line, label);
                if (target && line == 175 && !checkInserted) {
                  super.visitVarInsn(Opcodes.ALOAD, 0);
                  super.visitVarInsn(Opcodes.ALOAD, 1);
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "targetCheck",
                      "(Ljava/lang/Object;Ljava/lang/Long;)V", false);
                  checkInserted = true;
                  changed[0] = true;
                }
              }

              @Override
              public void visitInsn(int opcode) {
                if (directoryFactoryGet && opcode == Opcodes.ARETURN) {
                  super.visitInsn(Opcodes.DUP);
                  super.visitVarInsn(Opcodes.ALOAD, 1);
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "registerDirectory",
                      "(Lorg/apache/lucene/store/Directory;Ljava/lang/String;)V", false);
                  changed[0] = true;
                }
                if (policyGet && opcode == Opcodes.ARETURN) {
                  super.visitInsn(Opcodes.DUP);
                  super.visitVarInsn(Opcodes.ALOAD, 0);
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "registerPolicy",
                      "(Ljava/lang/Object;Ljava/lang/Object;)V", false);
                  changed[0] = true;
                }
                if (target && opcode == Opcodes.ATHROW) {
                  super.visitInsn(Opcodes.DUP);
                  super.visitVarInsn(Opcodes.ALOAD, 0);
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "targetThrow",
                      "(Ljava/lang/Throwable;Ljava/lang/Object;)V", false);
                  changed[0] = true;
                }
                if (onCommit && opcode == Opcodes.RETURN) {
                  super.visitVarInsn(Opcodes.ALOAD, 0);
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "onCommitReturn",
                      "(Ljava/lang/Object;)V", false);
                  changed[0] = true;
                }
                super.visitInsn(opcode);
              }

              @Override
              public void visitMethodInsn(int opcode, String owner, String called,
                                          String descriptor, boolean isInterface) {
                invocation++;
                if (onCommit && POLICY.equals(owner)
                    && "updateKnownCommitPoints".equals(called)) {
                  super.visitVarInsn(Opcodes.ALOAD, 0);
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "windowEnd",
                      "(Ljava/lang/Object;)V", false);
                  changed[0] = true;
                }
                String operation = directoryOperation(owner, called, descriptor);
                if (operation != null && opcode != Opcodes.INVOKESTATIC) {
                  String site = className.replace('/', '.') + "." + name + desc
                      + "#call" + invocation;
                  super.visitLdcInsn(site);
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, operation,
                      wrapperDescriptor(operation), false);
                  changed[0] = true;
                } else {
                  super.visitMethodInsn(opcode, owner, called, descriptor, isInterface);
                }
                if (onCommit && POLICY.equals(owner)
                    && "updateLatestCommit".equals(called)) {
                  super.visitVarInsn(Opcodes.ALOAD, 0);
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "windowStart",
                      "(Ljava/lang/Object;)V", false);
                  changed[0] = true;
                }
              }
            };
          }
        };
        reader.accept(visitor, ClassReader.EXPAND_FRAMES);
        return changed[0] ? writer.toByteArray() : null;
      } catch (Throwable failure) {
        System.err.println("SOLR22 probe transform failed for " + className);
        failure.printStackTrace(System.err);
        throw new IllegalStateException(failure);
      }
    }
  }

  private static String directoryOperation(String owner, String name, String desc) {
    if (!owner.startsWith("org/apache/lucene/store/")) return null;
    if ("deleteFile".equals(name) && "(Ljava/lang/String;)V".equals(desc)) return "deleteFile";
    if ("openInput".equals(name) && ("(Ljava/lang/String;L" + CONTEXT
        + ";)Lorg/apache/lucene/store/IndexInput;").equals(desc)) return "openInput";
    if ("createOutput".equals(name) && ("(Ljava/lang/String;L" + CONTEXT
        + ";)Lorg/apache/lucene/store/IndexOutput;").equals(desc)) return "createOutput";
    return null;
  }

  private static String wrapperDescriptor(String operation) {
    if ("deleteFile".equals(operation)) return "(L" + DIR + ";Ljava/lang/String;Ljava/lang/String;)V";
    if ("openInput".equals(operation)) return "(L" + DIR + ";Ljava/lang/String;L"
        + CONTEXT + ";Ljava/lang/String;)Lorg/apache/lucene/store/IndexInput;";
    return "(L" + DIR + ";Ljava/lang/String;L" + CONTEXT
        + ";Ljava/lang/String;)Lorg/apache/lucene/store/IndexOutput;";
  }
}
