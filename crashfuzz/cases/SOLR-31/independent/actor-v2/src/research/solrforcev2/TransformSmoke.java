package research.solrforcev2;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.lang.reflect.Proxy;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Verify both release classes acquire the exact V2 hooks before a JUnit run. */
public final class TransformSmoke {
  public static void main(String[] args) throws Exception {
    final ClassFileTransformer[] holder = new ClassFileTransformer[1];
    Instrumentation instrumentation = (Instrumentation) Proxy.newProxyInstance(
        TransformSmoke.class.getClassLoader(), new Class<?>[]{Instrumentation.class},
        (proxy, method, arguments) -> {
          if (method.getName().equals("addTransformer")) holder[0] = (ClassFileTransformer) arguments[0];
          return null;
        });
    Agent.premain("", instrumentation);
    if (holder[0] == null) throw new AssertionError("transformer not installed");
    verify(holder[0], "org/apache/solr/handler/admin/CollectionsHandler", "targetEnter",
        "(Lorg/apache/solr/request/SolrQueryRequest;"
        + "Lorg/apache/solr/handler/admin/CollectionsHandler;)V");
    verify(holder[0], "org/apache/solr/common/cloud/SolrZkClient", "nativeEntry",
        "(Lorg/apache/solr/common/cloud/SolrZkClient;Ljava/lang/String;Ljava/lang/String;)V");
    Probe.close();
    System.out.println("SOLR31_ACTOR_V2_TRANSFORM_SMOKE passed=2");
  }

  private static void verify(ClassFileTransformer transformer, String name,
                             String hook, String descriptor) throws Exception {
    byte[] original;
    try (InputStream input = ClassLoader.getSystemResourceAsStream(name + ".class")) {
      if (input == null) throw new AssertionError("release class absent: " + name);
      ByteArrayOutputStream bytes = new ByteArrayOutputStream();
      byte[] buffer = new byte[8192];
      int length;
      while ((length = input.read(buffer)) != -1) bytes.write(buffer, 0, length);
      original = bytes.toByteArray();
    }
    byte[] transformed = transformer.transform(null, name, null, null, original);
    if (transformed == null) throw new AssertionError("class not transformed: " + name);
    final int[] calls = {0};
    new ClassReader(transformed).accept(new ClassVisitor(Opcodes.ASM9) {
      @Override
      public MethodVisitor visitMethod(int access, String method, String desc,
                                       String signature, String[] exceptions) {
        return new MethodVisitor(Opcodes.ASM9) {
          @Override
          public void visitMethodInsn(int opcode, String owner, String called,
                                      String callDesc, boolean itf) {
            if (owner.equals("research/solrforcev2/Probe")
                && called.equals(hook) && callDesc.equals(descriptor)) calls[0]++;
          }
        };
      }
    }, 0);
    if (calls[0] < 1) throw new AssertionError("hook not emitted: " + name + " / " + hook);
  }
}
