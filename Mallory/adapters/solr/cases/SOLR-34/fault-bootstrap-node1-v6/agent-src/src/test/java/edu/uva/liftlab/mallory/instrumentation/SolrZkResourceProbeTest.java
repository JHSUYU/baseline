package edu.uva.liftlab.mallory.instrumentation;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.List;
import org.junit.Test;
import static org.junit.Assert.*;

public final class SolrZkResourceProbeTest {
  private static final String CLASS = "org.apache.solr.common.cloud.SolrZkClient";
  private static final String EXISTS_DESCRIPTOR =
      "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;)Lorg/apache/zookeeper/data/Stat;";
  private static final String GETDATA_DESCRIPTOR =
      "(Ljava/lang/String;Lorg/apache/zookeeper/Watcher;Lorg/apache/zookeeper/data/Stat;)[B";

  @Test public void transformedZkReadsPreserveResultsAndRecordExactPaths() throws Exception {
    AgentConfig config = new AgentConfig();
    config.includes.add(CLASS.replace('.', '/'));
    config.siteCatalog = File.createTempFile("mallory-solr-path-catalog", ".jsonl");
    config.doors.add(rule("lambda$exists$2", EXISTS_DESCRIPTOR, "exists"));
    config.doors.add(rule("lambda$getData$6", GETDATA_DESCRIPTOR, "getData"));
    File events = File.createTempFile("mallory-solr-path-events", ".jsonl");
    Probe.install("solr-resource", events, new FaultPlan());
    Class<?> fixture = transformed(config);
    Object client = fixture.newInstance();
    Object first = fixture.getMethod("lookup", String.class)
        .invoke(client, "/live_nodes/leader-1");
    Object second = fixture.getMethod("lookup", String.class)
        .invoke(client, "/live_nodes/leader-2");
    byte[] data = (byte[]) fixture.getMethod("readData", String.class)
        .invoke(client, "/collections/collection1");
    assertEquals("/live_nodes/leader-1", first.getClass().getMethod("getPath").invoke(first));
    assertEquals("/live_nodes/leader-2", second.getClass().getMethod("getPath").invoke(second));
    assertEquals("/collections/collection1", new String(data, StandardCharsets.UTF_8));

    List<String> rows = Files.readAllLines(events.toPath(), StandardCharsets.UTF_8);
    int observed = 0;
    for (String line : rows) {
      JsonObject row = new JsonParser().parse(line).getAsJsonObject();
      if (!"DOOR_OBSERVED".equals(row.get("type").getAsString())) continue;
      String[] paths = {"/live_nodes/leader-1", "/live_nodes/leader-2",
          "/collections/collection1"};
      assertEquals(paths[observed++], row.get("resource").getAsString());
      assertEquals("org.apache.zookeeper.KeeperException$ConnectionLossException",
          row.get("exception_class").getAsString());
    }
    assertEquals(3, observed);
    List<String> catalog = Files.readAllLines(config.siteCatalog.toPath(), StandardCharsets.UTF_8);
    assertEquals(2, catalog.stream().filter(line ->
        line.contains("\"resource_argument\":\"first_string_parameter\"")).count());
  }

  @Test public void wrongResourceDoesNotConsumeExactFaultPlan() throws Exception {
    final String site = "SolrZkClient#getData@349:door:1";
    final String wanted = "/collections/.sys.COORDINATOR-COLL-conf/state.json";
    FaultPlan plan = new FaultPlan();
    FaultPlan.Fault fault = new FaultPlan.Fault();
    fault.fault_id = "synthetic-state";
    fault.fault_type = "EXCEPTION";
    fault.exception_class = "java.io.IOException";
    fault.point = new FaultPlan.Point();
    fault.point.site = site;
    fault.point.node = "node5";
    fault.point.epoch = 0;
    fault.point.door_ordinal = 1L;
    fault.point.resource = wanted;
    plan.faults.add(fault);

    File wrongEvents = File.createTempFile("mallory-wrong-path", ".jsonl");
    Probe.install("wrong-path", wrongEvents, plan);
    try (Probe.NodeScope node = Probe.withNode("node5", 0)) {
      Probe.beforeDoor(site, "java.io.IOException", "/collections/other/state.json");
    }
    assertFalse(Files.readAllLines(wrongEvents.toPath(), StandardCharsets.UTF_8)
        .stream().anyMatch(line -> line.contains("\"type\":\"FAULT_APPLIED\"")));

    File rightEvents = File.createTempFile("mallory-right-path", ".jsonl");
    Probe.install("right-path", rightEvents, plan);
    try (Probe.NodeScope node = Probe.withNode("node5", 0)) {
      Probe.beforeDoor(site, "java.io.IOException", wanted);
      fail("the exact resource should still be injectable");
    } catch (Throwable injected) {
      assertEquals(java.io.IOException.class, injected.getClass());
    }
    assertTrue(Files.readAllLines(rightEvents.toPath(), StandardCharsets.UTF_8)
        .stream().anyMatch(line -> line.contains("\"type\":\"FAULT_APPLIED\"")
            && line.contains("\"resource\":\"" + wanted + "\"")));
  }

  private static AgentConfig.SiteRule rule(String method, String descriptor, String callee) {
    AgentConfig.SiteRule rule = new AgentConfig.SiteRule();
    rule.clazz = CLASS;
    rule.method = method;
    rule.descriptor = descriptor;
    rule.callee = "org.apache.solr.common.cloud.SolrZooKeeper#" + callee + descriptor;
    rule.exceptionClass = "org.apache.zookeeper.KeeperException$ConnectionLossException";
    return rule;
  }

  private static Class<?> transformed(AgentConfig config) throws Exception {
    final MalloryTransformer transformer = new MalloryTransformer(config);
    ClassLoader loader = new ClassLoader(SolrZkResourceProbeTest.class.getClassLoader()) {
      @Override protected Class<?> loadClass(String name, boolean resolve)
          throws ClassNotFoundException {
        if (!CLASS.equals(name)) return super.loadClass(name, resolve);
        synchronized (getClassLoadingLock(name)) {
          Class<?> loaded = findLoadedClass(name);
          if (loaded == null) {
            String resource = name.replace('.', '/') + ".class";
            byte[] source;
            try (InputStream input = getParent().getResourceAsStream(resource)) {
              assertNotNull(input);
              ByteArrayOutputStream output = new ByteArrayOutputStream();
              byte[] buffer = new byte[4096];
              int n;
              while ((n = input.read(buffer)) != -1) output.write(buffer, 0, n);
              source = output.toByteArray();
            } catch (Exception failure) {
              throw new ClassNotFoundException(name, failure);
            }
            byte[] changed = transformer.transform(this, resource.substring(0, resource.length() - 6),
                null, null, source);
            assertNotNull(changed);
            loaded = defineClass(name, changed, 0, changed.length);
          }
          if (resolve) resolveClass(loaded);
          return loaded;
        }
      }
    };
    return loader.loadClass(CLASS);
  }
}
