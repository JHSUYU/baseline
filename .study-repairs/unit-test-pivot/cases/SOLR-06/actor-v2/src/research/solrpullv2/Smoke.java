package research.solrpullv2;

import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.Map;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Transform unchanged classes without running a cluster. */
public final class Smoke {
  public static void main(String[] args) throws Exception {
    Map<String, Integer> hooks = new HashMap<>();
    final int[] guard = {0};
    final int[] thrown = {0};
    final int[] assertion = {0};
    for (int i = 0; i < args.length; i += 2) {
      String name = args[i];
      byte[] transformed = Agent.weave(name, Files.readAllBytes(Paths.get(args[i + 1])));
      if (transformed == null) throw new AssertionError("missing transform " + name);
      final int[] count = {0};
      new ClassReader(transformed).accept(new ClassVisitor(Opcodes.ASM9) {
        @Override public MethodVisitor visitMethod(int access, String method, String desc,
                                                   String signature, String[] exceptions) {
          return new MethodVisitor(Opcodes.ASM9) {
            @Override public void visitMethodInsn(int opcode, String owner, String called,
                                                 String descriptor, boolean isInterface) {
              if (owner.equals(Agent.PROBE)) {
                count[0]++;
                if (called.equals("guard")) guard[0]++;
                if (called.equals("targetThrow")) thrown[0]++;
              }
            }
            @Override public void visitLdcInsn(Object value) {
              if ("Pull replica became leader!".equals(value)) assertion[0]++;
            }
          };
        }
      }, 0);
      hooks.put(name, count[0]);
    }
    if (hooks.get(Agent.CONTROLLER) < 3 || hooks.get(Agent.ZK) != 6 ||
        guard[0] != 1 || thrown[0] != 1 || assertion[0] != 1)
      throw new AssertionError("target/IO hooks or original assertion missing: " + hooks
          + " guard=" + guard[0] + " throw=" + thrown[0]
          + " assertion=" + assertion[0]);
    String path = "/collections/pull_replica_test_create_delete/leaders/shard1/leader";
    if (!Probe.smokeMatch("JETTY/node2", path) ||
        Probe.smokeMatch("JETTY/node1", path) ||
        Probe.smokeMatch("UNBOUND:SOLRZKCLIENT", path) ||
        Probe.smokeMatch("JETTY/node2", path + "-other"))
      throw new AssertionError("wrong actor/path consumed a fault");
    Object controller = new Object();
    Object client = new Object();
    Probe.bind(controller, client, "127.0.0.1:12345_solr", "/tmp/test/node1");
    boolean rejected = false;
    try {
      Probe.bind(new Object(), new Object(), "127.0.0.1:54321_solr", "/tmp/test/node1");
    } catch (IllegalStateException expected) { rejected = true; }
    if (!rejected) throw new AssertionError("ambiguous logical node was accepted");
    System.out.println("SOLR06_V2_OFFLINE_OK " + hooks);
  }
}
