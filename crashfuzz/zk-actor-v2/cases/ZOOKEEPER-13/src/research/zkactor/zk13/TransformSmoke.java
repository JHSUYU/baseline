package research.zkactor.zk13;

import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.LinkedHashMap;
import java.util.Map;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.analysis.Analyzer;
import org.objectweb.asm.tree.analysis.BasicInterpreter;

/** Transform original bytecode and check the target hooks without a cluster JVM. */
public final class TransformSmoke {
  public static void main(String[] args) throws Exception {
    String[] names = {CaseAgent.TEST, CaseAgent.CLIENT, CaseAgent.SERVER, CaseAgent.TARGET};
    Map<String, Integer> hooks = new LinkedHashMap<>();
    for (int i = 0; i < names.length; i++) {
      String name = names[i];
      byte[] original = Files.readAllBytes(Paths.get(args[i], name + ".class"));
      byte[] changed = CaseAgent.transformBytes(name, original);
      java.nio.file.Path output = Paths.get(args[4], name + ".class");
      Files.createDirectories(output.getParent());
      Files.write(output, changed);
      ClassNode node = new ClassNode(Opcodes.ASM9);
      new ClassReader(changed).accept(node, 0);
      int bridge = 0;
      for (MethodNode method : node.methods) {
        int guard = 0, thrown = 0;
        boolean instrumented = false;
        for (AbstractInsnNode instruction : method.instructions) {
          if (!(instruction instanceof MethodInsnNode)) continue;
          MethodInsnNode call = (MethodInsnNode) instruction;
          if (call.owner.equals(CaseAgent.BRIDGE)) {
            instrumented = true;
            bridge++;
            if (call.name.equals("targetGuard")) guard++;
            if (call.name.equals("targetThrow")) thrown++;
          }
          if (call.owner.equals(CaseAgent.PROBE)) instrumented = true;
        }
        if (name.equals(CaseAgent.TARGET) && method.name.equals("validateSession")
            && (guard != 1 || thrown != 1)) {
          throw new AssertionError("read-only target hooks missing or duplicated");
        }
        if (instrumented) new Analyzer<>(new BasicInterpreter()).analyze(name, method);
      }
      if (bridge < (name.equals(CaseAgent.TEST) ? 4 : 1)) {
        throw new AssertionError(name + " lacks receiver hook");
      }
      hooks.put(name, bridge);
    }
    System.out.println(hooks);
  }
}
