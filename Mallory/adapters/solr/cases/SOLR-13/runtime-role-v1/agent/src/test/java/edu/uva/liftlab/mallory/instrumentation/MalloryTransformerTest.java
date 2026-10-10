package edu.uva.liftlab.mallory.instrumentation;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.lang.reflect.InvocationTargetException;
import java.security.MessageDigest;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.junit.Test;
import static org.junit.Assert.*;

public final class MalloryTransformerTest {
  private static final String FIXTURE =
      "edu.uva.liftlab.mallory.instrumentation.fixture.SampleClusterOperation";
  private static final String STATE_FIXTURE =
      "edu.uva.liftlab.mallory.instrumentation.fixture.StateOperation";
  private static final String NODE_FIXTURE =
      "edu.uva.liftlab.mallory.instrumentation.fixture.NodePeer";
  private static final String ASYNC_FIXTURE =
      "edu.uva.liftlab.mallory.instrumentation.fixture.AsyncOperation";
  private static final String CALL_FIXTURE =
      "edu.uva.liftlab.mallory.instrumentation.fixture.CallGuardOperation";
  private static final String SELF_MERGE_FIXTURE =
      "edu.uva.liftlab.mallory.instrumentation.fixture.SelfMergeOperation";
  private static final String DATANODE_DUPLICATE_FIXTURE =
      "org.apache.hadoop.hdfs.server.datanode.DataNode";

  @Test public void transformsDataNodeWithoutEagerDuplicateClassDefinition() throws Exception {
    AgentConfig config = new AgentConfig();
    config.includes.add(DATANODE_DUPLICATE_FIXTURE.replace('.', '/'));
    MalloryTransformer transformer = new MalloryTransformer(config);
    final int[] duplicateDefinitionAttempts = {0};
    ClassLoader loader = new ClassLoader(MalloryTransformerTest.class.getClassLoader()) {
      private boolean transforming;
      @Override protected Class<?> loadClass(String name, boolean resolve)
          throws ClassNotFoundException {
        if (!DATANODE_DUPLICATE_FIXTURE.equals(name)) return super.loadClass(name, resolve);
        synchronized (getClassLoadingLock(name)) {
          if (transforming) {
            duplicateDefinitionAttempts[0]++;
            throw new LinkageError("attempted duplicate DataNode definition during transform");
          }
          Class<?> loaded = findLoadedClass(name);
          if (loaded == null) {
            byte[] original;
            try { original = readResource(name.replace('.', '/') + ".class"); }
            catch (Exception failure) { throw new ClassNotFoundException(name, failure); }
            transforming = true;
            byte[] changed;
            try { changed = transformer.transform(this, name.replace('.', '/'), null, null, original); }
            finally { transforming = false; }
            assertNotNull("resource-based hierarchy lookup must preserve DataNode probes", changed);
            loaded = defineClass(name, changed, 0, changed.length);
          }
          if (resolve) resolveClass(loaded);
          return loaded;
        }
      }
    };
    Class<?> dataNode = loader.loadClass(DATANODE_DUPLICATE_FIXTURE);
    Object instance = dataNode.newInstance();
    assertSame(instance, dataNode.getMethod("choose", boolean.class).invoke(instance, true));
    assertTrue(dataNode.getMethod("choose", boolean.class).invoke(instance, false)
        instanceof ArrayList);
    assertEquals("transformer must not eager-load a second DataNode", 0,
        duplicateDefinitionAttempts[0]);
  }

  @Test public void computesFramesWithoutLoadingClassBeingTransformed() throws Exception {
    final AgentConfig config = new AgentConfig();
    config.includes.add(SELF_MERGE_FIXTURE.replace('.', '/'));
    final MalloryTransformer transformer = new MalloryTransformer(config);
    final int[] recursiveLoads = {0};
    ClassLoader loader = new ClassLoader(MalloryTransformerTest.class.getClassLoader()) {
      private boolean transforming;
      @Override protected Class<?> loadClass(String name, boolean resolve)
          throws ClassNotFoundException {
        if (!SELF_MERGE_FIXTURE.equals(name)) return super.loadClass(name, resolve);
        synchronized (getClassLoadingLock(name)) {
          if (transforming) {
            recursiveLoads[0]++;
            throw new ClassNotFoundException("recursive target load during frame computation");
          }
          Class<?> loaded = findLoadedClass(name);
          if (loaded == null) {
            byte[] original;
            try { original = readResource(name.replace('.', '/') + ".class"); }
            catch (Exception failure) { throw new ClassNotFoundException(name, failure); }
            transforming = true;
            byte[] changed;
            try { changed = transformer.transform(this, name.replace('.', '/'), null, null, original); }
            finally { transforming = false; }
            assertNotNull("frame computation should retain instrumentation", changed);
            loaded = defineClass(name, changed, 0, changed.length);
          }
          if (resolve) resolveClass(loaded);
          return loaded;
        }
      }
    };
    Class<?> fixture = loader.loadClass(SELF_MERGE_FIXTURE);
    Object operation = fixture.newInstance();
    assertSame(operation, fixture.getMethod("choose", boolean.class).invoke(operation, true));
    assertTrue(fixture.getMethod("choose", boolean.class).invoke(operation, false)
        instanceof ArrayList);
    assertTrue(fixture.getMethod("chooseArray", boolean.class).invoke(operation, true)
        instanceof String[]);
    assertTrue(fixture.getMethod("chooseArray", boolean.class).invoke(operation, false)
        instanceof Integer[]);
    assertEquals("transformer must never recursively define its target", 0, recursiveLoads[0]);
  }

  @Test public void recordsExactTargetAndInjectsAtObservedDoor() throws Exception {
    File healthy = File.createTempFile("mallory-healthy", ".jsonl");
    AgentConfig config = config();
    Probe.install("healthy", healthy, new FaultPlan());
    Class<?> testClass = transformed(config);
    Object operation = testClass.newInstance();
    assertEquals(8, testClass.getMethod("run", int.class).invoke(operation, 1));
    try {
      testClass.getMethod("run", int.class).invoke(operation, -1);
      fail("selected target should throw");
    } catch (InvocationTargetException expected) {
      assertEquals(IllegalStateException.class, expected.getCause().getClass());
    }
    List<JsonObject> events = readEvents(healthy);
    for (JsonObject event : events) {
      String type = event.get("type").getAsString();
      if (type.startsWith("COVERAGE_")) continue; // Aggregate rows have no single event thread.
      assertEquals("every healthy causal event needs a numeric thread identity",
          Thread.currentThread().getId(), event.get("thread_id").getAsLong());
    }
    assertTrue(hasType(events, "COVERAGE_SUMMARY"));
    assertTrue(hasType(events, "TARGET_CHECK"));
    assertTrue(hasType(events, "TARGET_THROW"));
    assertTrue(hasType(events, "REGION_ENTER"));
    assertTrue(hasType(events, "REGION_EXIT"));
    JsonObject door = firstType(events, "DOOR_OBSERVED");
    assertNotNull(door);
    String site = door.get("site").getAsString();
    assertTrue(site.contains(":door:"));
    assertEquals(door.get("occurrence").getAsString(),
        firstType(events, "TARGET_CHECK").get("occurrence").getAsString());

    FaultPlan plan = new FaultPlan();
    FaultPlan.Fault fault = new FaultPlan.Fault();
    fault.fault_id = "f-1";
    fault.fault_type = "EXCEPTION";
    fault.exception_class = "java.io.IOException";
    fault.point = new FaultPlan.Point();
    fault.point.site = site;
    fault.point.hit = 1L;
    plan.faults.add(fault);
    File faulted = File.createTempFile("mallory-faulted", ".jsonl");
    Probe.install("faulted", faulted, plan);
    Class<?> faultedClass = transformed(config);
    try {
      faultedClass.getMethod("run", int.class).invoke(faultedClass.newInstance(), 1);
      fail("I/O exception should be injected before the selected call");
    } catch (InvocationTargetException expected) {
      assertEquals(java.io.IOException.class, expected.getCause().getClass());
    }
    List<JsonObject> faultedEvents = readEvents(faulted);
    for (JsonObject event : faultedEvents) {
      if (event.get("type").getAsString().startsWith("COVERAGE_")) continue;
      assertEquals("fault matching and application need a numeric thread identity",
          Thread.currentThread().getId(), event.get("thread_id").getAsLong());
    }
    assertNotNull(firstType(faultedEvents, "FAULT_MATCHED"));
    assertNotNull(firstType(faultedEvents, "FAULT_APPLIED"));
    assertEquals("f-1", firstType(faultedEvents, "FAULT_APPLIED").get("fault_id").getAsString());
    assertFalse(hasType(faultedEvents, "TARGET_THROW"));
    assertEquals("REGION_EXIT", lastRuntimeEvent(faultedEvents).get("type").getAsString());
  }

  @Test public void wrongSiteDoesNotApplyFault() throws Exception {
    FaultPlan plan = new FaultPlan();
    FaultPlan.Fault fault = new FaultPlan.Fault();
    fault.fault_id = "wrong";
    fault.fault_type = "EXCEPTION";
    fault.point = new FaultPlan.Point();
    fault.point.site = "absent#door";
    plan.faults.add(fault);
    File events = File.createTempFile("mallory-unmatched", ".jsonl");
    Probe.install("unmatched", events, plan);
    Class<?> fixture = transformed(config());
    assertEquals(8, fixture.getMethod("run", int.class).invoke(fixture.newInstance(), 1));
    assertFalse(hasType(readEvents(events), "FAULT_APPLIED"));
  }

  @Test public void replaysDoorByNodeSiteOrdinalAcrossDifferentCausalTokens() throws Exception {
    File healthy = File.createTempFile("mallory-ordinal-healthy", ".jsonl");
    Probe.install("ordinal-healthy", healthy, new FaultPlan());
    try (Probe.NodeScope node = Probe.withNode("nn0", 0);
         Probe.ContextScope context = Probe.taskClaim("unstable-client-id-1", "rpc")) {
      Probe.beforeDoor("hdfs:read");
    }
    JsonObject first = firstType(readEvents(healthy), "DOOR_OBSERVED");
    assertEquals(1L, first.get("door_ordinal").getAsLong());

    FaultPlan plan = new FaultPlan();
    FaultPlan.Fault fault = new FaultPlan.Fault();
    fault.fault_id = "ordinal-fault";
    fault.fault_type = "EXCEPTION";
    fault.point = new FaultPlan.Point();
    fault.point.site = "hdfs:read";
    fault.point.node = "nn0";
    fault.point.epoch = 0;
    fault.point.door_ordinal = 1L;
    plan.faults.add(fault);
    File faulted = File.createTempFile("mallory-ordinal-faulted", ".jsonl");
    Probe.install("ordinal-faulted", faulted, plan);
    try (Probe.NodeScope node = Probe.withNode("nn0", 0);
         Probe.ContextScope context = Probe.taskClaim("unstable-client-id-2", "rpc")) {
      Probe.beforeDoor("hdfs:read");
      fail("ordinal-based replay should inject");
    } catch (Throwable expected) {
      assertEquals(java.io.IOException.class, expected.getClass());
      assertTrue(expected.getMessage().contains("ordinal-fault"));
    }
    JsonObject applied = firstType(readEvents(faulted), "FAULT_APPLIED");
    assertNotNull(applied);
    assertEquals(1L, applied.get("door_ordinal").getAsLong());
    assertNotEquals(first.get("occurrence").getAsString(),
        firstType(readEvents(faulted), "DOOR_OBSERVED").get("occurrence").getAsString());
  }

  @Test public void observesSynchronousTaskCompletionInCurrentOccurrence() throws Exception {
    File eventsFile = File.createTempFile("mallory-task-observe", ".jsonl");
    Probe.install("observe", eventsFile, new FaultPlan());
    try (Probe.NodeScope node = Probe.withNode("client", 0)) {
      Probe.regionEnter("scanner");
      Probe.taskObserve("response-token", "rpc-response");
      Probe.method("scanner-after-response");
      Probe.regionExit("scanner");
    }
    List<JsonObject> events = readEvents(eventsFile);
    JsonObject claim = firstType(events, "TASK_CLAIM");
    JsonObject method = firstType(events, "COVERAGE_SUMMARY");
    assertNotNull(claim);
    assertEquals(claim.get("occurrence"), method.get("occurrence"));
    assertTrue(coverageIds(events, method).toString().contains("scanner-after-response"));
    assertEquals("response-token", claim.get("correlation").getAsString());
  }

  @Test public void explicitDoorAdvertisesAndDefaultsToDeclaredException() throws Exception {
    AgentConfig config = new AgentConfig();
    config.includes.add(FIXTURE.replace('.', '/'));
    config.siteCatalog = File.createTempFile("mallory-door-catalog", ".jsonl");
    AgentConfig.SiteRule door = new AgentConfig.SiteRule();
    door.clazz = FIXTURE;
    door.method = "run";
    door.callee = "java.io.ByteArrayInputStream#read()I";
    door.exceptionClass = "java.net.SocketTimeoutException";
    config.doors.add(door);
    File healthy = File.createTempFile("mallory-typed-door", ".jsonl");
    Probe.install("typed-healthy", healthy, new FaultPlan());
    Class<?> fixture = transformed(config);
    assertEquals(8, fixture.getMethod("run", int.class).invoke(fixture.newInstance(), 1));
    JsonObject observed = firstType(readEvents(healthy), "DOOR_OBSERVED");
    assertNotNull(observed);
    assertEquals("java.net.SocketTimeoutException", observed.get("exception_class").getAsString());
    assertEquals("java.net.SocketTimeoutException",
        firstType(readEvents(config.siteCatalog), "DOOR_OBSERVED")
            .get("exception_class").getAsString());

    FaultPlan plan = new FaultPlan();
    FaultPlan.Fault fault = new FaultPlan.Fault();
    fault.fault_id = "typed-fault";
    fault.fault_type = "EXCEPTION";
    fault.point = new FaultPlan.Point();
    fault.point.site = observed.get("site").getAsString();
    fault.point.hit = 1L;
    plan.faults.add(fault);
    File faulted = File.createTempFile("mallory-typed-fault", ".jsonl");
    Probe.install("typed-faulted", faulted, plan);
    fixture = transformed(config);
    try {
      fixture.getMethod("run", int.class).invoke(fixture.newInstance(), 1);
      fail("typed I/O exception should be applied");
    } catch (InvocationTargetException expected) {
      assertEquals(java.net.SocketTimeoutException.class, expected.getCause().getClass());
    }
    assertEquals("java.net.SocketTimeoutException", firstType(readEvents(faulted), "FAULT_APPLIED")
        .get("exception_class").getAsString());
  }

  @Test public void observesGuardCallExceptionBeforeOriginalCatchAndPreservesIdentity() throws Exception {
    AgentConfig config = new AgentConfig();
    config.includes.add(CALL_FIXTURE.replace('.', '/'));
    config.siteCatalog = File.createTempFile("mallory-callthrow-catalog", ".jsonl");
    AgentConfig.SiteRule rule = ruleWithoutCallee(CALL_FIXTURE, "run");
    rule.callee = CALL_FIXTURE + "#requirePositive(Z)V";
    rule.exceptionClass = "java.lang.IllegalArgumentException";
    config.targets.add(rule);
    config.regions.add(ruleWithoutCallee(CALL_FIXTURE, "run"));
    File eventsFile = File.createTempFile("mallory-callthrow", ".jsonl");
    Probe.install("callthrow", eventsFile, new FaultPlan());
    Class<?> fixture = transformed(config, CALL_FIXTURE);
    assertEquals(-1, fixture.getMethod("run", int.class).invoke(fixture.newInstance(), -1));
    assertSame(fixture.getField("EXPECTED").get(null), fixture.getField("caught").get(null));
    JsonObject targetThrow = firstType(readEvents(eventsFile), "TARGET_THROW");
    assertNotNull(targetThrow);
    assertTrue(targetThrow.get("site").getAsString().contains(":callthrow:"));
    assertEquals("java.lang.IllegalArgumentException",
        targetThrow.get("exception_class").getAsString());
    JsonObject row = firstType(readEvents(config.siteCatalog), "TARGET_THROW");
    assertEquals(targetThrow.get("site"), row.get("site"));
    assertEquals("java.lang.IllegalArgumentException", row.get("exception_class").getAsString());
  }

  @Test public void observesGuardCallInConstructorAfterSuperInitialization() throws Exception {
    String constructed = CALL_FIXTURE + "$Constructed";
    AgentConfig config = new AgentConfig();
    config.includes.add(constructed.replace('.', '/'));
    AgentConfig.SiteRule rule = ruleWithoutCallee(constructed, "<init>");
    rule.callee = CALL_FIXTURE + "#requirePositive(Z)V";
    config.targets.add(rule);
    config.regions.add(ruleWithoutCallee(constructed, "<init>"));
    File eventsFile = File.createTempFile("mallory-ctor-callthrow", ".jsonl");
    Probe.install("constructor", eventsFile, new FaultPlan());
    Class<?> fixture = transformed(config, constructed);
    try {
      fixture.getConstructor(int.class).newInstance(-1);
      fail("selected constructor guard should throw");
    } catch (InvocationTargetException expected) {
      assertEquals(IllegalArgumentException.class, expected.getCause().getClass());
    }
    List<JsonObject> events = readEvents(eventsFile);
    assertNotNull(firstType(events, "REGION_ENTER"));
    assertNotNull(firstType(events, "TARGET_THROW"));
    assertNotNull(firstType(events, "REGION_EXIT"));
    assertEquals("REGION_EXIT", lastRuntimeEvent(events).get("type").getAsString());
  }

  @Test public void recordsSelectedFieldAndMapVersions() throws Exception {
    AgentConfig config = new AgentConfig();
    config.includes.add(STATE_FIXTURE.replace('.', '/'));
    config.fieldState = true;
    config.mapState = true;
    File eventsFile = File.createTempFile("mallory-state", ".jsonl");
    Probe.install("state", eventsFile, new FaultPlan());
    Class<?> fixture = transformed(config, STATE_FIXTURE);
    assertEquals(3, fixture.getMethod("run", String.class).invoke(fixture.newInstance(), "key"));
    List<JsonObject> events = readEvents(eventsFile);
    int fieldWrites = 0;
    int matchedFieldReads = 0;
    int mapWrites = 0;
    int matchedMapReads = 0;
    for (JsonObject event : events) {
      String type = event.get("type").getAsString();
      if (!type.equals("STATE_READ") && !type.equals("STATE_WRITE")) continue;
      String key = event.get("key").getAsString();
      long version = event.get("version").getAsLong();
      if (key.endsWith("#number") && type.equals("STATE_WRITE")) fieldWrites++;
      if (key.endsWith("#number") && type.equals("STATE_READ") && version == 1) matchedFieldReads++;
      if (key.equals("key") && type.equals("STATE_WRITE")) mapWrites++;
      if (key.equals("key") && type.equals("STATE_READ") && version == 1) matchedMapReads++;
    }
    assertEquals(1, fieldWrites);
    assertEquals(1, matchedFieldReads);
    assertEquals(1, mapWrites);
    assertEquals(1, matchedMapReads);
  }

  @Test public void coversSwitchCasesWithoutFabricatingOtherCases() throws Exception {
    File eventsFile = File.createTempFile("mallory-switch", ".jsonl");
    Probe.install("switch", eventsFile, new FaultPlan());
    Class<?> fixture = transformed(config());
    Object object = fixture.newInstance();
    assertEquals(11, fixture.getMethod("choose", int.class).invoke(object, 1));
    assertEquals(-1, fixture.getMethod("choose", int.class).invoke(object, 9));
    List<JsonObject> events = readEvents(eventsFile);
    int cases = 0;
    for (JsonObject event : events) {
      if (!event.get("type").getAsString().equals("COVERAGE_SUMMARY")) continue;
      for (String coverageId : coverageIds(events, event)) {
        if (coverageId.endsWith(":CASE:1") || coverageId.endsWith(":DEFAULT")) cases++;
        assertFalse(coverageId.endsWith(":CASE:2"));
      }
    }
    assertEquals(2, cases);
  }

  @Test public void catalogListsTargetThrowEvenWhenHealthyRunDoesNotThrow() throws Exception {
    AgentConfig config = config();
    config.siteCatalog = File.createTempFile("mallory-catalog", ".jsonl");
    File eventsFile = File.createTempFile("mallory-catalog-run", ".jsonl");
    Probe.install("catalog", eventsFile, new FaultPlan());
    Class<?> fixture = transformed(config);
    assertEquals(8, fixture.getMethod("run", int.class).invoke(fixture.newInstance(), 1));
    assertFalse(hasType(readEvents(eventsFile), "TARGET_THROW"));
    JsonObject dormantThrow = firstType(readEvents(config.siteCatalog), "TARGET_THROW");
    assertNotNull(dormantThrow);
    assertTrue(dormantThrow.get("site").getAsString().contains(":throw:1"));
    assertEquals(FIXTURE, dormantThrow.get("class_name").getAsString());
    assertEquals(sha256(readResource(FIXTURE.replace('.', '/') + ".class")),
        dormantThrow.get("bytecode_sha256").getAsString());
    assertNotEquals(dormantThrow.get("bytecode_sha256").getAsString(),
        dormantThrow.get("instrumented_sha256").getAsString());
    assertTrue(dormantThrow.get("class_loader_id").getAsString().contains("@"));
  }

  @Test public void bindsNodeFromConcreteReceiverAndAdvancesEpochForNewReceiver() throws Exception {
    AgentConfig config = new AgentConfig();
    config.includes.add(NODE_FIXTURE.replace('.', '/'));
    AgentConfig.NodeBinding binding = new AgentConfig.NodeBinding();
    binding.clazz = NODE_FIXTURE;
    binding.method = "run";
    binding.field = "myid";
    binding.prefix = "zk";
    config.nodeBindings.add(binding);
    File eventsFile = File.createTempFile("mallory-nodes", ".jsonl");
    Probe.install("nodes", eventsFile, new FaultPlan());
    Class<?> fixture = transformed(config, NODE_FIXTURE);
    Object first = fixture.getConstructor(long.class).newInstance(5L);
    Object second = fixture.getConstructor(long.class).newInstance(5L);
    assertEquals(3, fixture.getMethod("run", int.class).invoke(first, 3));
    assertEquals(3, fixture.getMethod("run", int.class).invoke(first, -3));
    assertEquals(4, fixture.getMethod("run", int.class).invoke(second, 4));
    List<JsonObject> events = readEvents(eventsFile);
    List<Integer> epochs = new ArrayList<Integer>();
    java.util.Set<String> rootOccurrences = new java.util.HashSet<String>();
    for (JsonObject event : events) {
      if (!"COVERAGE_SUMMARY".equals(event.get("type").getAsString())) continue;
      if (!coverageIds(events, event).toString().contains("#run(I)I")) continue;
      assertEquals("zk5", event.get("node").getAsString());
      epochs.add(event.get("epoch").getAsInt());
      rootOccurrences.add(event.get("occurrence").getAsString());
    }
    assertEquals(java.util.Arrays.asList(0, 0, 1), epochs);
    assertEquals(3, rootOccurrences.size());
  }

  @Test public void bindsNodeFromExplicitNumericGetterBeforeRegion() throws Exception {
    AgentConfig config = new AgentConfig();
    config.includes.add(NODE_FIXTURE.replace('.', '/'));
    AgentConfig.NodeBinding binding = new AgentConfig.NodeBinding();
    binding.clazz = NODE_FIXTURE;
    binding.method = "run";
    binding.getter = "getServerId";
    binding.prefix = "zk";
    config.nodeBindings.add(binding);
    config.regions.add(ruleWithoutCallee(NODE_FIXTURE, "run"));
    File eventsFile = File.createTempFile("mallory-getter", ".jsonl");
    Probe.install("getter", eventsFile, new FaultPlan());
    Class<?> fixture = transformed(config, NODE_FIXTURE);
    assertEquals(3, fixture.getMethod("run", int.class).invoke(
        fixture.getConstructor(long.class).newInstance(17L), 3));
    JsonObject region = firstType(readEvents(eventsFile), "REGION_ENTER");
    assertNotNull(region);
    assertEquals("zk17", region.get("node").getAsString());
    assertEquals(0, region.get("epoch").getAsInt());
    assertFalse(hasType(readEvents(eventsFile), "NODE_IDENTITY_GAP"));
  }

  @Test public void propagatesExplicitTaskHandoffAcrossPooledThread() throws Exception {
    AgentConfig config = new AgentConfig();
    config.includes.add(ASYNC_FIXTURE.replace('.', '/'));
    AgentConfig.SiteRule rule = new AgentConfig.SiteRule();
    rule.clazz = ASYNC_FIXTURE;
    rule.method = "run";
    rule.callee = "java.util.concurrent.ExecutorService#submit(Ljava/util/concurrent/Callable;)Ljava/util/concurrent/Future;";
    config.async.add(rule);
    config.regions.add(ruleWithoutCallee(ASYNC_FIXTURE, "run"));
    File eventsFile = File.createTempFile("mallory-async", ".jsonl");
    Probe.install("async", eventsFile, new FaultPlan());
    Class<?> fixture = transformed(config, ASYNC_FIXTURE);
    try (Probe.NodeScope ignored = Probe.withNode("zk7", 2)) {
      assertEquals(42, fixture.getMethod("run").invoke(fixture.newInstance()));
    }
    List<JsonObject> events = readEvents(eventsFile);
    JsonObject submitted = firstType(events, "TASK_SUBMIT");
    JsonObject claimed = firstType(events, "TASK_CLAIM");
    assertNotNull(submitted);
    assertNotNull(claimed);
    assertEquals(submitted.get("correlation"), claimed.get("correlation"));
    assertEquals("zk7", claimed.get("node").getAsString());
    assertEquals(2, claimed.get("epoch").getAsInt());
    assertNotEquals(submitted.get("thread"), claimed.get("thread"));
  }

  @Test public void parsesDocumentedClassKeyInSiteFile() throws Exception {
    Path directory = Files.createTempDirectory("mallory-config");
    Path sites = directory.resolve("sites.json");
    Path properties = directory.resolve("agent.properties");
    Files.write(sites, ("{\"targets\":[{\"class\":\"" + NODE_FIXTURE
        + "\",\"method\":\"run\"}],\"nodeBindings\":[{\"class\":\""
        + NODE_FIXTURE + "\",\"method\":\"run\",\"getter\":\"getServerId\",\"prefix\":\"zk\"}],"
        + "\"doors\":[{\"class\":\"" + FIXTURE + "\",\"method\":\"run\","
        + "\"exception_class\":\"java.net.SocketTimeoutException\"}]}"
        ).getBytes(StandardCharsets.UTF_8));
    Files.write(properties, ("events=" + directory.resolve("events.jsonl") + "\nsite.file="
        + sites + "\n").getBytes(StandardCharsets.UTF_8));
    AgentConfig config = AgentConfig.load(properties.toString());
    assertEquals(NODE_FIXTURE.replace('.', '/'), config.targets.get(0).className());
    assertTrue(config.nodeBindings.get(0).matches(NODE_FIXTURE.replace('.', '/'), "run", "(I)I"));
    assertEquals("getServerId", config.nodeBindings.get(0).getter);
    assertEquals("java.net.SocketTimeoutException", config.doors.get(0).exceptionClass);
    assertTrue(config.includes(NODE_FIXTURE.replace('.', '/')));
    assertFalse(config.includes(NODE_FIXTURE.replace('.', '/') + "Config"));
  }

  @Test public void emitsExplicitMarkerBeforeBoundedTraceStops() throws Exception {
    File eventsFile = File.createTempFile("mallory-limit", ".jsonl");
    Probe.install("limited", eventsFile, new FaultPlan());
    Probe.configureLimits(2, 1024 * 1024);
    Probe.receive("rpc", "a", "request", "a");
    Probe.receive("rpc", "b", "request", "b");
    Probe.receive("rpc", "c", "request", "c");
    Probe.receive("rpc", "d", "request", "d");
    List<JsonObject> events = readEvents(eventsFile);
    assertEquals(3, events.size());
    assertEquals("TRACE_TRUNCATED", events.get(2).get("type").getAsString());
    assertEquals("max_events", events.get(2).get("reason").getAsString());
  }

  private static AgentConfig.SiteRule ruleWithoutCallee(String clazz, String method) {
    AgentConfig.SiteRule rule = new AgentConfig.SiteRule();
    rule.clazz = clazz;
    rule.method = method;
    return rule;
  }

  private static AgentConfig config() {
    AgentConfig config = new AgentConfig();
    config.includes.add(FIXTURE.replace('.', '/'));
    config.autoIoDoors = true;
    AgentConfig.SiteRule rule = new AgentConfig.SiteRule();
    rule.clazz = FIXTURE;
    rule.method = "run";
    config.targets.add(rule);
    config.regions.add(rule);
    return config;
  }

  private static Class<?> transformed(AgentConfig config) throws Exception {
    return transformed(config, FIXTURE);
  }

  private static Class<?> transformed(AgentConfig config, final String className) throws Exception {
    final MalloryTransformer transformer = new MalloryTransformer(config);
    ClassLoader loader = new ClassLoader(MalloryTransformerTest.class.getClassLoader()) {
      @Override protected Class<?> loadClass(String name, boolean resolve) throws ClassNotFoundException {
        if (!name.equals(className) && !name.startsWith(className + "$"))
          return super.loadClass(name, resolve);
        synchronized (getClassLoadingLock(name)) {
          Class<?> loaded = findLoadedClass(name);
          if (loaded == null) {
            byte[] bytes;
            try { bytes = readResource(name.replace('.', '/') + ".class"); }
            catch (Exception failure) { throw new ClassNotFoundException(name, failure); }
            byte[] changed = transformer.transform(this, name.replace('.', '/'), null, null, bytes);
            if (name.equals(className)) assertNotNull("transformer should change the fixture", changed);
            byte[] actual = changed == null ? bytes : changed;
            loaded = defineClass(name, actual, 0, actual.length);
          }
          if (resolve) resolveClass(loaded);
          return loaded;
        }
      }
    };
    return loader.loadClass(className);
  }

  private static byte[] readResource(String name) throws Exception {
    InputStream stream = MalloryTransformerTest.class.getClassLoader().getResourceAsStream(name);
    assertNotNull(stream);
    try {
      ByteArrayOutputStream bytes = new ByteArrayOutputStream();
      byte[] chunk = new byte[4096];
      int count;
      while ((count = stream.read(chunk)) >= 0) bytes.write(chunk, 0, count);
      return bytes.toByteArray();
    } finally { stream.close(); }
  }

  private static String sha256(byte[] bytes) throws Exception {
    byte[] digest = MessageDigest.getInstance("SHA-256").digest(bytes);
    StringBuilder hex = new StringBuilder();
    for (byte value : digest) hex.append(String.format("%02x", value & 255));
    return hex.toString();
  }

  private static List<JsonObject> readEvents(File path) throws Exception {
    Probe.flushCoverage();
    List<JsonObject> events = new ArrayList<JsonObject>();
    for (String line : Files.readAllLines(path.toPath(), StandardCharsets.UTF_8))
      events.add(new JsonParser().parse(line).getAsJsonObject());
    return events;
  }

  private static boolean hasType(List<JsonObject> events, String type) {
    return firstType(events, type) != null;
  }

  private static JsonObject firstType(List<JsonObject> events, String type) {
    for (JsonObject event : events)
      if (type.equals(event.get("type").getAsString())) return event;
    return null;
  }

  private static JsonObject lastRuntimeEvent(List<JsonObject> events) {
    for (int i = events.size() - 1; i >= 0; i--)
      if (!"COVERAGE_SUMMARY".equals(events.get(i).get("type").getAsString())
          && !"COVERAGE_DEF".equals(events.get(i).get("type").getAsString()))
        return events.get(i);
    return null;
  }

  private static List<String> coverageIds(List<JsonObject> events, JsonObject summary) {
    Map<Integer, String> definitions = new HashMap<Integer, String>();
    for (JsonObject event : events) {
      if (!"COVERAGE_DEF".equals(event.get("type").getAsString())) continue;
      definitions.put(event.get("coverage_ref").getAsInt(), event.get("coverage_id").getAsString());
    }
    List<String> ids = new ArrayList<String>();
    for (com.google.gson.JsonElement ref : summary.getAsJsonArray("coverage_refs"))
      ids.add(definitions.get(ref.getAsInt()));
    java.util.Collections.sort(ids);
    return ids;
  }
}
