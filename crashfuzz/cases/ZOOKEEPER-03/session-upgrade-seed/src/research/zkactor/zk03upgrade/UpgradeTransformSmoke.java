package research.zkactor.zk03upgrade;

import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.Map;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Offline bytecode check for the exact original test and target hooks. */
public final class UpgradeTransformSmoke {
  private UpgradeTransformSmoke() {}

  public static void main(String[] args) throws Exception {
    if (args.length != 2) throw new IllegalArgumentException("test.class target.class");
    check(UpgradeAgent.TEST, args[0], new String[] {
        "enterTest", "registerInitial", "bindUpgradedSession",
        "beginUpgradeReconnect", "registerReconnected", "endUpgradeReconnect"});
    check(UpgradeAgent.TRACKER, args[1], new String[] {"targetGuard", "targetThrow"});
  }

  private static void check(String name, String file, String[] hooks) throws Exception {
    byte[] original = Files.readAllBytes(Paths.get(file));
    byte[] transformed = UpgradeAgent.transformBytes(name, original);
    final Map<String, Integer> counts = new HashMap<>();
    new ClassReader(transformed).accept(new ClassVisitor(Opcodes.ASM9) {
      @Override public MethodVisitor visitMethod(int access, String method, String descriptor,
          String signature, String[] exceptions) {
        return new MethodVisitor(Opcodes.ASM9) {
          @Override public void visitMethodInsn(int opcode, String owner, String invoked,
              String calledDescriptor, boolean isInterface) {
            if (owner.equals(UpgradeAgent.BRIDGE)) {
              counts.put(invoked, counts.getOrDefault(invoked, 0) + 1);
            }
          }
        };
      }
    }, 0);
    for (String hook : hooks) {
      if (counts.getOrDefault(hook, 0) != 1) {
        throw new IllegalStateException(name + " hook " + hook + " count " + counts);
      }
    }
    System.out.println(name + " original=" + original.length + " transformed="
        + transformed.length + " hooks=" + counts);
  }
}
