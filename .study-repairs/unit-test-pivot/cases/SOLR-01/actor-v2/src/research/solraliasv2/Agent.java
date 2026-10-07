package research.solraliasv2;

import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.security.ProtectionDomain;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Label;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Bytecode hooks in unchanged Solr and original JUnit classes. */
public final class Agent {
  static final String BASE = "org/apache/solr/client/solrj/impl/BaseHttpClusterStateProvider";
  static final String CLOUD = "org/apache/solr/client/solrj/impl/BaseCloudSolrClient";
  static final String TEST = "org/apache/solr/client/solrj/impl/CloudHttp2SolrClientTest";
  static final String JETTY = "org/apache/solr/client/solrj/embedded/JettySolrRunner";
  static final String PROBE = "research/solraliasv2/Probe";

  private Agent() {}

  public static void premain(String unused, Instrumentation instrumentation) {
    Probe.initialize();
    instrumentation.addTransformer(new ClassFileTransformer() {
      @Override public byte[] transform(ClassLoader loader, String name, Class<?> redefining,
                                        ProtectionDomain domain, byte[] original) {
        if (!BASE.equals(name) && !CLOUD.equals(name)
            && !TEST.equals(name) && !JETTY.equals(name)) return null;
        try { return weave(name, original); }
        catch (Throwable failure) {
          System.err.println("SOLR01_V2_TRANSFORM_FAILED " + name);
          failure.printStackTrace(System.err);
          throw new IllegalStateException(failure);
        }
      }
    });
  }

  static byte[] weave(String name, byte[] original) {
    final int[] hooks = {0};
    ClassReader reader = new ClassReader(original);
    ClassWriter writer = new ClassWriter(reader, ClassWriter.COMPUTE_FRAMES);
    reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
      @Override public MethodVisitor visitMethod(int access, String method, String desc,
                                                 String signature, String[] exceptions) {
        MethodVisitor base = super.visitMethod(access, method, desc, signature, exceptions);
        if (base == null) return null;
        if (CLOUD.equals(name) && "request".equals(method)
            && "(Lorg/apache/solr/client/solrj/SolrRequest;Ljava/lang/String;)"
               .concat("Lorg/apache/solr/common/util/NamedList;").equals(desc)) {
          return new MethodVisitor(Opcodes.ASM9, base) {
            @Override public void visitCode() {
              super.visitCode();
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ALOAD, 1);
              super.visitVarInsn(Opcodes.ALOAD, 2);
              super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "requestEnter",
                  "(Ljava/lang/Object;Lorg/apache/solr/client/solrj/SolrRequest;"
                  + "Ljava/lang/String;)V", false);
              hooks[0]++;
            }
          };
        }
        if (TEST.equals(name) && "getRandomClient".equals(method)) {
          return new MethodVisitor(Opcodes.ASM9, base) {
            @Override public void visitInsn(int opcode) {
              if (opcode == Opcodes.ARETURN) {
                super.visitInsn(Opcodes.DUP);
                super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "bindSelectedClient",
                    "(Lorg/apache/solr/client/solrj/impl/CloudHttp2SolrClient;)V", false);
                hooks[0]++;
              }
              super.visitInsn(opcode);
            }
          };
        }
        if (JETTY.equals(name) && "getNodeName".equals(method)) {
          return new MethodVisitor(Opcodes.ASM9, base) {
            @Override public void visitInsn(int opcode) {
              if (opcode == Opcodes.ARETURN) {
                super.visitInsn(Opcodes.DUP);
                super.visitVarInsn(Opcodes.ALOAD, 0);
                super.visitMethodInsn(Opcodes.INVOKEVIRTUAL, JETTY, "getSolrHome",
                    "()Ljava/lang/String;", false);
                super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "bindNode",
                    "(Ljava/lang/String;Ljava/lang/String;)V", false);
                hooks[0]++;
              }
              super.visitInsn(opcode);
            }
          };
        }
        if (BASE.equals(name) && "getAliases".equals(method)
            && "(Z)Ljava/util/Map;".equals(desc)) {
          return new MethodVisitor(Opcodes.ASM9, base) {
            int line;
            @Override public void visitCode() {
              super.visitCode();
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitVarInsn(Opcodes.ILOAD, 1);
              super.visitVarInsn(Opcodes.ALOAD, 0);
              super.visitFieldInsn(Opcodes.GETFIELD, BASE, "liveNodes", "Ljava/util/Set;");
              super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "begin",
                  "(Ljava/lang/Object;ZLjava/util/Set;)V", false);
              hooks[0]++;
            }
            @Override public void visitLineNumber(int line, Label start) {
              this.line = line;
              super.visitLineNumber(line, start);
              if (line == 247) {
                super.visitVarInsn(Opcodes.ALOAD, 0);
                super.visitVarInsn(Opcodes.ALOAD, 3);
                super.visitVarInsn(Opcodes.ALOAD, 4);
                super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "io",
                    "(Ljava/lang/Object;Ljava/lang/String;Ljava/lang/String;)V", false);
                hooks[0]++;
              } else if (line == 267) {
                super.visitVarInsn(Opcodes.ALOAD, 0);
                super.visitInsn(Opcodes.ICONST_1);
                super.visitInsn(Opcodes.ACONST_NULL);
                super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "check",
                    "(Ljava/lang/Object;ZLjava/lang/String;)V", false);
                hooks[0]++;
              }
            }
            @Override public void visitInsn(int opcode) {
              if (opcode == Opcodes.ARETURN && (line == 251 || line == 273)) {
                super.visitVarInsn(Opcodes.ALOAD, 0);
                super.visitInsn(Opcodes.ICONST_0);
                if (line == 251) super.visitVarInsn(Opcodes.ALOAD, 3);
                else super.visitInsn(Opcodes.ACONST_NULL);
                super.visitMethodInsn(Opcodes.INVOKESTATIC, PROBE, "check",
                    "(Ljava/lang/Object;ZLjava/lang/String;)V", false);
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
