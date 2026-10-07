package research.solrsubshardv2;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.lang.reflect.Proxy;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Offline check of the three exact production bytecode transformations. */
public final class SmokeTransform {
  private SmokeTransform() {}

  public static void main(String[] ignored) throws Exception {
    final ClassFileTransformer[] transform = new ClassFileTransformer[1];
    Instrumentation instrumentation = (Instrumentation) Proxy.newProxyInstance(
        SmokeTransform.class.getClassLoader(), new Class<?>[] {Instrumentation.class},
        (proxy, method, arguments) -> {
          if (method.getName().equals("addTransformer")) {
            transform[0] = (ClassFileTransformer) arguments[0];
          }
          if (method.getReturnType() == boolean.class) return false;
          if (method.getReturnType() == int.class) return 0;
          return null;
        });
    Agent.premain("", instrumentation);
    if (transform[0] == null) throw new AssertionError("transformer missing");
    check(transform[0], "org/apache/solr/cloud/ZkController", "bindServerClient");
    check(transform[0], "org/apache/solr/common/cloud/SolrZkClient", "nativeEntry");
    check(transform[0], "org/apache/solr/update/processor/DistributedZkUpdateProcessor",
        "targetEnter");
    System.out.println("ACTOR_V2_TRANSFORM_SMOKE_OK");
    Probe.close();
  }

  private static void check(ClassFileTransformer transformer, String className,
                            String expectedMethod) throws Exception {
    byte[] original;
    try (InputStream input = SmokeTransform.class.getClassLoader()
        .getResourceAsStream(className + ".class")) {
      if (input == null) throw new AssertionError("missing class " + className);
      ByteArrayOutputStream bytes = new ByteArrayOutputStream();
      byte[] buffer = new byte[8192];
      int count;
      while ((count = input.read(buffer)) >= 0) bytes.write(buffer, 0, count);
      original = bytes.toByteArray();
    }
    byte[] woven = transformer.transform(null, className, null, null, original);
    if (woven == null) throw new AssertionError("transform unchanged " + className);
    final int[] hooks = {0};
    new ClassReader(woven).accept(new ClassVisitor(Opcodes.ASM9) {
      @Override
      public MethodVisitor visitMethod(int access, String name, String descriptor,
                                       String signature, String[] exceptions) {
        return new MethodVisitor(Opcodes.ASM9) {
          @Override
          public void visitMethodInsn(int opcode, String owner, String method,
                                      String descriptor, boolean isInterface) {
            if (owner.equals("research/solrsubshardv2/Probe")
                && method.equals(expectedMethod)) hooks[0]++;
          }
        };
      }
    }, 0);
    if (hooks[0] == 0) throw new AssertionError("missing hook " + expectedMethod
        + " in " + className);
    System.out.println(className + " " + expectedMethod + " hooks=" + hooks[0]);
  }
}
