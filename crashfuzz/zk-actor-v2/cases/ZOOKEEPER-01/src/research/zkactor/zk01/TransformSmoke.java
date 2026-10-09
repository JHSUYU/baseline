package research.zkactor.zk01;

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

/** Inspects transformed original bytecode without loading the cluster or running JUnit. */
public final class TransformSmoke {
  public static void main(String[] args) throws Exception {
    String[] names = {CaseAgent.TEST, CaseAgent.CLIENT, CaseAgent.SERVER,
        CaseAgent.TRACKER, CaseAgent.PEER};
    Map<String, Integer> calls = new LinkedHashMap<>();
    for (int i = 0; i < names.length; i++) {
      String name = names[i];
      byte[] original = Files.readAllBytes(Paths.get(args[i], name + ".class"));
      byte[] transformed = CaseAgent.transformBytes(name, original);
      java.nio.file.Path output = Paths.get(args[5], name + ".class");
      Files.createDirectories(output.getParent());
      Files.write(output, transformed);
      ClassNode checked = new ClassNode(Opcodes.ASM9);
      new ClassReader(transformed).accept(checked, 0);
      for (MethodNode method : checked.methods) {
        boolean adapterCode = false;
        for (AbstractInsnNode instruction : method.instructions) {
          if (instruction instanceof MethodInsnNode) {
            String owner = ((MethodInsnNode) instruction).owner;
            adapterCode |= owner.equals(CaseAgent.BRIDGE) || owner.equals(CaseAgent.PROBE);
          }
        }
        if (adapterCode) {
          try { new Analyzer<>(new BasicInterpreter()).analyze(name, method); }
          catch (Exception failure) {
            throw new AssertionError(name + "#" + method.name + method.desc
                + " maxStack=" + method.maxStack, failure);
          }
        }
      }
      int[] bridgeCalls = {0};
      new ClassReader(transformed).accept(new ClassVisitor(Opcodes.ASM9) {
        @Override public MethodVisitor visitMethod(int access, String method,
            String descriptor, String signature, String[] exceptions) {
          return new MethodVisitor(Opcodes.ASM9) {
            @Override public void visitMethodInsn(int opcode, String owner, String called,
                String calledDesc, boolean itf) {
              if (owner.equals(CaseAgent.BRIDGE)) bridgeCalls[0]++;
            }
          };
        }
      }, 0);
      if (bridgeCalls[0] < (name.equals(CaseAgent.TEST) ? 3 : 1)) {
        throw new AssertionError(name + " missing adapter calls: " + bridgeCalls[0]);
      }
      calls.put(name, bridgeCalls[0]);
    }
    System.out.println(calls);
  }
}
