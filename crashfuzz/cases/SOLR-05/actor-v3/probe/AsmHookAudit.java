package baseline.solr05v2;

import java.io.FileInputStream;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Inspect compiled hook call instructions without loading Solr or opening sockets. */
public final class AsmHookAudit {
  public static void main(String[] args) throws Exception {
    if (args.length != 3) throw new IllegalArgumentException("class-file method expected-count");
    final int[] count = {0};
    try (FileInputStream stream = new FileInputStream(args[0])) {
      new ClassReader(stream).accept(new ClassVisitor(Opcodes.ASM9) {
        @Override public MethodVisitor visitMethod(int access, String name, String descriptor,
                                                  String signature, String[] exceptions) {
          return new MethodVisitor(Opcodes.ASM9) {
            @Override public void visitMethodInsn(int opcode, String owner, String method,
                                                 String descriptor, boolean isInterface) {
              if (owner.equals("baseline/solr05v2/FeedbackProbe") && method.equals(args[1]))
                count[0]++;
            }
          };
        }
      }, 0);
    }
    int expected = Integer.parseInt(args[2]);
    if (count[0] != expected)
      throw new AssertionError(args[0] + " " + args[1] + ": " + count[0] + " != " + expected);
    System.out.println(count[0]);
  }
}
