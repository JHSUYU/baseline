package research.zkactor.zk1112;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.LinkedHashMap;
import java.util.Map;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.tree.AbstractInsnNode;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.MethodInsnNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.tree.analysis.Analyzer;
import org.objectweb.asm.tree.analysis.BasicInterpreter;

/** Offline original-bytecode transformation, exact-hook, and frame smoke. */
public final class TransformSmoke {
  public static void main(String[] args) throws Exception {
    if (args.length != 4) throw new IllegalArgumentException("testDir serverDir atomicDir outputDir");
    String[] names = {CaseAgent.TEST, CaseAgent.PEER, CaseAgent.ATOMIC};
    Map<String, Map<String, Integer>> calls = new LinkedHashMap<>();
    for (int i = 0; i < names.length; i++) {
      String name = names[i];
      byte[] original = Files.readAllBytes(Paths.get(args[i], name + ".class"));
      byte[] transformed = CaseAgent.transformBytes(name, original);
      Path output = Paths.get(args[3], name + ".class");
      Files.createDirectories(output.getParent());
      Files.write(output, transformed);
      ClassNode checked = new ClassNode(Opcodes.ASM9);
      new ClassReader(transformed).accept(checked, 0);
      Map<String, Integer> methods = new LinkedHashMap<>();
      for (MethodNode method : checked.methods) {
        int hooks = 0;
        for (AbstractInsnNode instruction : method.instructions) {
          if (instruction instanceof MethodInsnNode) {
            String owner = ((MethodInsnNode) instruction).owner;
            if (owner.equals(CaseAgent.BRIDGE)) hooks++;
          }
        }
        if (hooks != 0) {
          new Analyzer<>(new BasicInterpreter()).analyze(name, method);
          methods.put(method.name, hooks);
        }
      }
      calls.put(name, methods);
    }
    if (calls.get(CaseAgent.TEST).getOrDefault("testReadCurrentEpochFromAcceptedEpochTmpFile", 0) != 3 ||
        calls.get(CaseAgent.PEER).getOrDefault("loadDataBase", 0) != 6 ||
        calls.get(CaseAgent.PEER).getOrDefault("readLongFromFile", 0) != 1 ||
        calls.get(CaseAgent.PEER).getOrDefault("writeLongToFile", 0) != 1 ||
        calls.get(CaseAgent.ATOMIC).getOrDefault("<init>", 0) != 1 ||
        calls.get(CaseAgent.ATOMIC).getOrDefault("close", 0) != 4) {
      throw new AssertionError("wrong exact hook counts " + calls);
    }
    System.out.println("ZK1112_TRANSFORM_OK " + calls);
  }
}
