package edu.uva.liftlab.mallory.adapters.hdfs;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import edu.uva.liftlab.mallory.instrumentation.FaultPlan;
import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.io.File;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.junit.Test;

/** Exact HDFS-12 key-map observations, using source-shaped fake receivers. */
public class Hdfs14KeyStateTest {
  static final class Manager {
    final boolean isMaster = false;
    final String blockPoolId = "BP-test";
    final Map<Integer, Object> allKeys = new HashMap<Integer, Object>();
  }
  static final class Key {
    final int id;
    Key(int id) { this.id = id; }
    public int getKeyId() { return id; }
  }
  static final class Exported {
    final Object[] keys;
    Exported(Object key) { keys = new Object[] {key}; }
    public Object[] getAllKeys() { return keys; }
  }
  static final class Identifier {
    public int getKeyId() { return 42; }
  }
  static final class Bpos {
    String getBlockPoolId() { return "BP-test"; } // Hadoop getter is package-private.
  }
  static final class Dn {
    public String getDatanodeUuid() { return "dn-uuid"; }
  }
  static final class Actor {
    final Bpos bpos = new Bpos();
    final Dn dn = new Dn();
  }

  private static File trace() throws Exception {
    File file = File.createTempFile("hdfs12-key-state", ".jsonl");
    Method install = Probe.class.getDeclaredMethod("install", String.class,
        File.class, FaultPlan.class);
    install.setAccessible(true);
    install.invoke(null, "hdfs12-test", file, new FaultPlan());
    return file;
  }

  @Test public void exactReadFromTracksManagerKeyValueAndVersion() throws Exception {
    File file = trace();
    Manager manager = new Manager();
    Key first = new Key(42);
    Key second = new Key(42);
    try (Probe.NodeScope node = Probe.withNode("hdfs-cluster-1/dn0", 0)) {
      manager.allKeys.put(42, first);
      Hdfs12KeyHooks.added(manager, new Exported(first));
      Hdfs12KeyHooks.lookupResult(first, manager, new Identifier());
      manager.allKeys.put(42, second);
      Hdfs12KeyHooks.added(manager, new Exported(second));
      Hdfs12KeyHooks.lookupResult(second, manager, new Identifier());
      Hdfs12KeyHooks.lookupResult(first, manager, new Identifier());
    }
    List<String> rows = Files.readAllLines(file.toPath(), StandardCharsets.UTF_8);
    String joined = String.join("\n", rows);
    assertEquals(2, rows.stream().filter(x -> x.contains("\"phase\":\"write\"")).count());
    assertEquals(2, rows.stream().filter(x -> x.contains("\"phase\":\"read\"")).count());
    assertEquals(1, rows.stream().filter(x -> x.contains("\"phase\":\"read_gap\"")).count());
    assertTrue(joined.contains("manager:1:key:42:version:1"));
    assertTrue(joined.contains("manager:1:key:42:version:2"));
    assertEquals(2, rows.stream().filter(x -> x.contains("\"type\":\"STATE_WRITE\"")
        && x.contains("\"version_confidence\":\"exact\"")).count());
    assertEquals(2, rows.stream().filter(x -> x.contains("\"type\":\"STATE_READ\"")
        && x.contains("\"version_confidence\":\"exact\"")).count());
  }

  static final class MiniCluster {
    final java.util.List<Object> dataNodes = new java.util.ArrayList<Object>();
  }
  static final class StartingDn {
    final Object storage = new Object();
    final Object blockPoolManager = new Object();
  }

  @Test public void preRefreshBindsConcreteReceiverBeforeActorsStart() throws Exception {
    trace();
    MiniCluster cluster = new MiniCluster();
    StartingDn first = new StartingDn();
    try (HdfsHooks.DataNodeCreationScope startup = HdfsHooks.dataNodeCreationEnter(cluster)) {
      HdfsHooks.dataNodeBeforeRefresh(first);
      try (Probe.NodeScope bound = Probe.withRegisteredNode(first)) {
        assertEquals("hdfs-cluster-1/dn0", Probe.currentNode());
        assertEquals(0, Probe.currentEpoch());
      }
      HdfsHooks.dataNodeStarting(first, cluster);
      try (Probe.NodeScope bound = Probe.withRegisteredNode(first)) {
        assertEquals(0, Probe.currentEpoch());
      }
    }
    cluster.dataNodes.add(first);
    StartingDn second = new StartingDn();
    try (HdfsHooks.DataNodeCreationScope startup = HdfsHooks.dataNodeCreationEnter(cluster)) {
      HdfsHooks.dataNodeBeforeRefresh(second);
      try (Probe.NodeScope bound = Probe.withRegisteredNode(second)) {
        assertEquals("hdfs-cluster-1/dn1", Probe.currentNode());
      }
    }
  }

  @Test public void packagePrivateHeartbeatGetterProducesNamedAttempt() throws Exception {
    File file = trace();
    Actor actor = new Actor();
    Probe.registerNode(actor.dn, "hdfs-cluster-1/dn0", 0);
    try (Probe.NodeScope node = Probe.withRegisteredNode(actor.dn)) {
      Hdfs12KeyHooks.heartbeatAttempt(actor);
    }
    String text = new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8);
    assertTrue(text.contains("\"phase\":\"dn_heartbeat_attempt\""));
    assertTrue(text.contains("\"node\":\"hdfs-cluster-1/dn0\""));
    assertTrue(!text.contains("identity_gap_dn_heartbeat_attempt"));
  }
}
