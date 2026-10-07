package research.zkactor.zk03;

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
public final class QuorumResponseTransformSmoke {
  public static void main(String[] args) throws Exception {
    String[] names = {QuorumResponseAgent.TEST, QuorumResponseAgent.CLIENT, QuorumResponseAgent.SERVER,
        QuorumResponseAgent.TRACKER, QuorumResponseAgent.PEER, QuorumResponseAgent.HANDLER};
    Map<String, Integer> calls = new LinkedHashMap<>();
    for (int i = 0; i < names.length; i++) {
      String name = names[i];
      byte[] original = Files.readAllBytes(Paths.get(args[i], name + ".class"));
      byte[] transformed = QuorumResponseAgent.transformBytes(name, original);
      java.nio.file.Path output = Paths.get(args[6], name + ".class");
      Files.createDirectories(output.getParent());
      Files.write(output, transformed);
      ClassNode checked = new ClassNode(Opcodes.ASM9);
      new ClassReader(transformed).accept(checked, 0);
      for (MethodNode method : checked.methods) {
        boolean adapterCode = false;
        for (AbstractInsnNode instruction : method.instructions) {
          if (instruction instanceof MethodInsnNode) {
            String owner = ((MethodInsnNode) instruction).owner;
            adapterCode |= owner.equals(QuorumResponseAgent.BRIDGE) || owner.equals(QuorumResponseAgent.PROBE);
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
      int[] afterCalls = {0};
      new ClassReader(transformed).accept(new ClassVisitor(Opcodes.ASM9) {
        @Override public MethodVisitor visitMethod(int access, String method,
            String descriptor, String signature, String[] exceptions) {
          return new MethodVisitor(Opcodes.ASM9) {
            @Override public void visitMethodInsn(int opcode, String owner, String called,
                String calledDesc, boolean itf) {
              if (owner.equals(QuorumResponseAgent.BRIDGE)) bridgeCalls[0]++;
              if (owner.equals(QuorumResponseAgent.AFTER_BRIDGE)
                  && (called.equals("clientWriteAfter")
                      || called.equals("serverResponseAfter")
                      || called.equals("quorumPacketWritten")
                      || called.equals("quorumAfterFlush"))) afterCalls[0]++;
            }
          };
        }
      }, 0);
      if (bridgeCalls[0] < (name.equals(QuorumResponseAgent.TEST) ? 3 :
          name.equals(QuorumResponseAgent.HANDLER) ? 0 : 1)) {
        throw new AssertionError(name + " missing adapter calls: " + bridgeCalls[0]);
      }
      if (name.equals(QuorumResponseAgent.CLIENT) && afterCalls[0] != 1) {
        throw new AssertionError("client write must have exactly one post-I/O hook: "
            + afterCalls[0]);
      }
      if (name.equals(QuorumResponseAgent.SERVER) && afterCalls[0] != 2) {
        throw new AssertionError("server response needs both complete-send hooks: "
            + afterCalls[0]);
      }
      if (name.equals(QuorumResponseAgent.HANDLER) && afterCalls[0] != 2) {
        throw new AssertionError("quorum response needs write and flush hooks: " + afterCalls[0]);
      }
      calls.put(name, bridgeCalls[0]);
    }
    System.out.println(calls);
  }
}
