package research.zkactor.zk04;

import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.LinkedHashMap;
import java.util.Map;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.analysis.Analyzer;
import org.objectweb.asm.tree.analysis.BasicInterpreter;

/** Check exact rewritten bytecode offline; build script also runs JVM -Xverify:all. */
public final class TransformSmoke {
  public static void main(String[] args) throws Exception {
    String[] names = {CaseAgent.TEST, CaseAgent.CLIENT, CaseAgent.SERVER,
        CaseAgent.TARGET, CaseAgent.PEER};
    Map<String, Integer> calls = new LinkedHashMap<>();
    for (int i = 0; i < names.length; i++) {
      String name = names[i];
      byte[] original = Files.readAllBytes(Paths.get(args[i], name + ".class"));
      byte[] transformed = CaseAgent.transformBytes(name, original);
      java.nio.file.Path output = Paths.get(args[5], name + ".class");
      Files.createDirectories(output.getParent());
      Files.write(output, transformed);
      ClassNode node = new ClassNode(Opcodes.ASM9);
      new ClassReader(transformed).accept(node, 0);
      for (MethodNode method : node.methods) {
        boolean injected = false;
        for (AbstractInsnNode instruction : method.instructions) {
          if (instruction instanceof MethodInsnNode) {
            String owner = ((MethodInsnNode) instruction).owner;
            injected |= owner.equals(CaseAgent.BRIDGE) || owner.equals(CaseAgent.PROBE);
          }
        }
        if (injected) new Analyzer<>(new BasicInterpreter()).analyze(name, method);
      }
      int[] count = {0};
      new ClassReader(transformed).accept(new ClassVisitor(Opcodes.ASM9) {
        @Override public MethodVisitor visitMethod(int access, String method,
            String descriptor, String signature, String[] exceptions) {
          return new MethodVisitor(Opcodes.ASM9) {
            @Override public void visitMethodInsn(int opcode, String owner, String called,
                String calledDesc, boolean itf) {
              if (owner.equals(CaseAgent.BRIDGE)) count[0]++;
            }
          };
        }
      }, 0);
      if (count[0] < (name.equals(CaseAgent.TEST) || name.equals(CaseAgent.TARGET) ? 2 : 1)) {
        throw new AssertionError(name + " lacks exact case hooks: " + count[0]);
      }
      calls.put(name, count[0]);
    }
    System.out.println(calls);
  }
}
