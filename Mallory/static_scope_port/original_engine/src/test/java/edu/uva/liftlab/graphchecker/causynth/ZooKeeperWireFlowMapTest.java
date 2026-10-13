package edu.uva.liftlab.graphchecker.causynth;

import org.junit.Test;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.options.Options;

import javax.tools.JavaCompiler;
import javax.tools.ToolProvider;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

/** Exercises the system-wide map through the original GraphChecker parser. */
public class ZooKeeperWireFlowMapTest {
    @Test public void bothQuorumDirectionsResolveAsTypedPorts() throws Exception {
        Path mapping = Paths.get("../communication/zookeeper-3.8.7.jsonl")
                .toAbsolutePath().normalize();
        assertTrue(Files.isRegularFile(mapping));
        Path root = Files.createTempDirectory("zk-wire-map-");
        Path sourceRoot = root.resolve("src/org/apache/zookeeper/server/quorum");
        Path classes = root.resolve("classes");
        Files.createDirectories(sourceRoot);
        Files.createDirectories(classes);
        Path packet = write(sourceRoot.resolve("QuorumPacket.java"),
                "package org.apache.zookeeper.server.quorum;\n"
                + "public class QuorumPacket {\n"
                + "  private long zxid;\n"
                + "  public QuorumPacket() {}\n"
                + "  public QuorumPacket(int type, long zxid, byte[] data, java.util.List info) { this.zxid=zxid; }\n"
                + "  public long getZxid() { return zxid; }\n"
                + "  public void setZxid(long value) { zxid=value; }\n"
                + "}\n");
        Path learner = write(sourceRoot.resolve("Learner.java"),
                "package org.apache.zookeeper.server.quorum;\n"
                + "public class Learner {\n"
                + "  protected long registerWithLeader(int packetType) {\n"
                + "    QuorumPacket p = new QuorumPacket();\n"
                + "    p.setZxid(7L);\n"
                + "    return p.getZxid();\n"
                + "  }\n"
                + "}\n");
        Path handler = write(sourceRoot.resolve("LearnerHandler.java"),
                "package org.apache.zookeeper.server.quorum;\n"
                + "public class LearnerHandler implements Runnable {\n"
                + "  public void run() {\n"
                + "    QuorumPacket p = new QuorumPacket(1, 9L, null, null);\n"
                + "    long seen = p.getZxid();\n"
                + "    if (seen < 0) throw new IllegalStateException();\n"
                + "  }\n"
                + "}\n");
        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        assertEquals(0, compiler.run(null, null, null, "-g", "-d",
                classes.toString(), packet.toString(), learner.toString(),
                handler.toString()));
        soot.G.reset();
        Options.v().set_prepend_classpath(true);
        Options.v().set_allow_phantom_refs(true);
        Options.v().set_process_dir(Collections.singletonList(classes.toString()));
        Options.v().set_soot_classpath(classes.toString());
        Options.v().set_output_format(Options.output_format_none);
        Scene.v().loadNecessaryClasses();
        Map<String, SootMethod> methods = new LinkedHashMap<>();
        for (SootClass type : Scene.v().getApplicationClasses()) {
            for (SootMethod method : type.getMethods()) {
                methods.put(method.getSignature(), method);
            }
        }
        String previous = System.getProperty(WireFlowCatalog.PROPERTY);
        try {
            System.setProperty(WireFlowCatalog.PROPERTY, mapping.toString());
            resetCachedRows();
            List<WireFlowCatalog.WireFlow> flows = WireFlowCatalog
                    .fromConfiguration(methods).flows();
            assertEquals(2, flows.size());
            assertEquals("zk-quorum-followerinfo-zxid", flows.get(0).id);
            assertEquals("zk-quorum-leaderinfo-zxid", flows.get(1).id);
            for (WireFlowCatalog.WireFlow flow : flows) {
                assertEquals("long", flow.javaType);
                assertEquals(1, flow.producers.size());
                assertEquals(1, flow.consumers.size());
                assertTrue(flow.producers.get(0).unitIndex >= 0);
                assertTrue(flow.consumers.get(0).unitIndex >= 0);
                assertTrue(!flow.producers.get(0).site().equals(
                        flow.consumers.get(0).site()));
            }
            assertTrue(!flows.get(0).portId.equals(flows.get(1).portId));
        } finally {
            if (previous == null) System.clearProperty(WireFlowCatalog.PROPERTY);
            else System.setProperty(WireFlowCatalog.PROPERTY, previous);
            resetCachedRows();
        }
    }

    private static Path write(Path path, String contents) throws Exception {
        Files.write(path, contents.getBytes(StandardCharsets.UTF_8));
        return path;
    }

    private static void resetCachedRows() throws Exception {
        Field field = WireFlowCatalog.class.getDeclaredField("rows");
        field.setAccessible(true);
        field.set(null, null);
    }
}
