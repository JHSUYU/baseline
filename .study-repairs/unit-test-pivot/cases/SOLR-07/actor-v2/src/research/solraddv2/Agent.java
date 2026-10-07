package research.solraddv2;

import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.security.ProtectionDomain;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Original class bytecode hooks for the core-availability check and ZK I/O. */
public final class Agent {
  static final String CONTROLLER = "org/apache/solr/cloud/ZkController";
  static final String ZK = "org/apache/solr/common/cloud/SolrZkClient";
  static final String PROBE = "research/solraddv2/Probe";

  private Agent() {}

  public static void premain(String unused, Instrumentation instrumentation) {
    Probe.initialize();
    instrumentation.addTransformer(new ClassFileTransformer() {
      @Override public byte[] transform(ClassLoader loader, String name, Class<?> redefining,
                                        ProtectionDomain domain, byte[] original) {
        if (!CONTROLLER.equals(name) && !ZK.equals(name)) return null;
        try { return weave(name, original); }
        catch (Throwable failure) {
          System.err.println("SOLR07_V2_TRANSFORM_FAILED " + name);
          failure.printStackTrace(System.err);
          throw new IllegalStateException(failure);
        }
      }
    });
  }

  private static boolean zkOperation(String name, String desc) {
    if ("exists".equals(name)) return desc.equals(
        "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Z)Lorg/apache/zookeeper/data/Stat;")
        || desc.equals("(Ljava/lang/String;Z)Ljava/lang/Boolean;");
    if ("getChildren".equals(name)) return desc.equals(
        "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Z)Ljava/util/List;")
        || desc.equals("(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;"
                      + "Lorg/apache/zookeeper/data/Stat;Z)Ljava/util/List;");
    if ("getData".equals(name)) return desc.equals(
        "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;"
        + "Lorg/apache/zookeeper/data/Stat;Z)[B");
    return "setData".equals(name) && desc.equals(
        "(Ljava/lang/String;[BIZ)Lorg/apache/zookeeper/data/Stat;");
  }

  static byte[] weave(String className, byte[] original) {
    final int[] hooks = {0};
    ClassReader reader = new ClassReader(original);
    ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_FRAMES);
    reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
      @Override public MethodVisitor visitMethod(int access, String name, String desc,
                                                 String signature, String[] exceptions) {
        MethodVisitor base = super.visitMethod(access, name, desc, signature, exceptions);
        if (base == null) return null;
        if (ZK.equals(className) && zkOperation(name, desc)) {
          return new MethodVisitor(Opcodes.ASM9, base) {
            @Override public void visitCode() {
              super.visitCode();
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitLdcInsn(name + desc);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "io",
                  "(Ljava/lang/Object;Ljava/lang/String;Ljava/lang/String;)V", false);
              hooks[0]++;
            }
          };
        }
        if (CONTROLLER.equals(className) && "<init>".equals(name)) {
          return new MethodVisitor(Opcodes.ASM9, base) {
            @Override public void visitFieldInsn(int opcode, String owner, String field,
                                                 String descriptor) {
              super.visitFieldInsn(opcode, owner, field, descriptor);
              if (opcode == Opcodes.PUTFIELD && CONTROLLER.equals(owner)
                  && "zkClient".equals(field)
                  && "Lorg/apache/solr/common/cloud/SolrZkClient;".equals(descriptor)) {
                super.visitVarInsn(Opcodes.ALOAD, 0);
                super.visitVarInsn(Opcodes.ALOAD, 0);
                super.visitFieldInsn(Opcodes.GETFIELD, CONTROLLER, "zkClient", descriptor);
                super.visitVarInsn(Opcodes.ALOAD, 0);
                super.visitFieldInsn(Opcodes.GETFIELD, CONTROLLER, "nodeName",
                    "Ljava/lang/String;");
                super.visitVarInsn(Opcodes.ALOAD, 0);
                super.visitFieldInsn(Opcodes.GETFIELD, CONTROLLER, "cc",
                    "Lorg/apache/solr/core/CoreContainer;");
                super.visitMethodInsn(Opcodes.INVOKEVIRTUAL,
                    "org/apache/solr/core/CoreContainer", "getSolrHome",
                    "()Ljava/lang/String;", false);
                super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "bind",
                    "(Ljava/lang/Object;Ljava/lang/Object;Ljava/lang/String;"
                    + "Ljava/lang/String;)V", false);
                hooks[0]++;
              }
            }
          };
        }
        if (CONTROLLER.equals(className) && "register".equals(name)
            && "(Ljava/lang/String;Lorg/apache/solr/core/CoreDescriptor;ZZZ)"
               .concat("Ljava/lang/String;").equals(desc)) {
          return new MethodVisitor(Opcodes.ASM9, base) {
            int line;
            boolean guardInserted;
            @Override public void visitLineNumber(int value, Label start) {
              line = value;
              super.visitLineNumber(value, start);
              if (value == 1325 && !guardInserted) {
                guardInserted = true;
                super.visitVarInsn(Opcodes.ALOAD, 0);
                super.visitVarInsn(Opcodes.ALOAD, 2);
                super.visitVarInsn(Opcodes.ALOAD, 11);
                super.visitVarInsn(Opcodes.ALOAD, 16);
                super.visitVarInsn(Opcodes.ALOAD, 13);
                super.visitVarInsn(Opcodes.ALOAD, 14);
                super.visitVarInsn(Opcodes.ILOAD, 15);
                super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "guard",
                    "(Lorg/apache/solr/cloud/ZkController;"
                    + "Lorg/apache/solr/core/CoreDescriptor;"
                    + "Lorg/apache/solr/common/cloud/Replica;"
                    + "Lorg/apache/solr/core/SolrCore;"
                    + "Ljava/lang/String;Ljava/lang/String;Z)V", false);
                hooks[0]++;
              }
            }
            @Override public void visitInsn(int opcode) {
              if (opcode == Opcodes.ATHROW && line == 1326) {
                super.visitInsn(Opcodes.DUP);
                super.visitVarInsn(Opcodes.ALOAD, 0);
                super.visitVarInsn(Opcodes.ALOAD, 2);
                super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "targetThrow",
                    "(Ljava/lang/Throwable;Lorg/apache/solr/cloud/ZkController;"
                    + "Lorg/apache/solr/core/CoreDescriptor;)V", false);
                hooks[0]++;
              }
              super.visitInsn(opcode);
            }
          };
        }
        return base;
      }
    }, ClassReader.EXPAND_FRAMES);
    return hooks[0] == 0 ? null : writer.toByteArray();
  }
}
