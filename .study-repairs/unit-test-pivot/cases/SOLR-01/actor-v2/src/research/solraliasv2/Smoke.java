package research.solraliasv2;

import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.Map;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Offline ASM and wrong actor smoke, with no cluster JVM. */
public final class Smoke {
  public static void main(String[] args) throws Exception {
    Map<String, Integer> counts = new HashMap<>();
    for (int i = 0; i < args.length; i += 2) {
      byte[] original = Files.readAllBytes(Paths.get(args[i + 1]));
      byte[] transformed = Agent.weave(args[i], original);
      if (transformed == null) throw new AssertionError("no hook for " + args[i]);
      final int[] hooks = {0};
      new ClassReader(transformed).accept(new ClassVisitor(Opcodes.ASM9) {
        @Override public MethodVisitor visitMethod(int access, String name, String desc,
                                                   String signature, String[] exceptions) {
          return new MethodVisitor(Opcodes.ASM9) {
            @Override public void visitMethodInsn(int opcode, String owner, String method,
                                                String descriptor, boolean isInterface) {
              if (owner.equals(Agent.PROBE)) hooks[0]++;
            }
          };
        }
      }, 0);
      counts.put(args[i], hooks[0]);
      if (hooks[0] < 1) throw new AssertionError("no Probe invocation for " + args[i]);
    }
    String actor = "CLIENT/CloudHttp2SolrClientTest.httpBasedCloudSolrClient";
    if (!Probe.smokeMatch(actor, "JETTY/node2", "IO_EXCEPTION"))
      throw new AssertionError("exact actor did not match");
    if (Probe.smokeMatch(actor, "JETTY/node3", "IO_EXCEPTION") ||
        Probe.smokeMatch("UNBOUND:HTTP_PROVIDER", "JETTY/node2", "IO_EXCEPTION") ||
        Probe.smokeMatch(actor, "JETTY/node2", "SOLR_SERVER_EXCEPTION"))
      throw new AssertionError("wrong actor, destination, or kind consumed fault");
    Probe.bindNode("127.0.0.1:12345_solr", "/tmp/cluster/node2");
    if (!"JETTY/node2".equals(Probe.smokeDestination("127.0.0.1:12345_solr",
        "http://127.0.0.1:12345/solr")))
      throw new AssertionError("exact endpoint did not resolve to its Jetty role");
    if (!Probe.smokeDestination("127.0.0.1:12345_solr",
        "http://127.0.0.1:12346/solr").startsWith("UNBOUND:"))
      throw new AssertionError("wrong physical endpoint was accepted");
    Probe.bindNode("127.0.0.1:54321_solr", "/tmp/cluster/node2");
    if (!Probe.smokeDestination("127.0.0.1:12345_solr",
        "http://127.0.0.1:12345/solr").startsWith("UNBOUND:"))
      throw new AssertionError("ambiguous logical node was accepted");
    System.out.println("SOLR01_V2_OFFLINE_OK " + counts);
  }
}
