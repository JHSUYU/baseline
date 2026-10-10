package edu.uva.liftlab.mallory.solr;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.junit.Test;

public class SolrHooksTest {
  public static final class Request {
    String token;
    public void header(String name, String value) {
      if (SolrHooks.HEADER.equals(name)) token = value;
    }
    public String getHeader(String name) {
      return SolrHooks.HEADER.equals(name) ? token : null;
    }
  }

  public static final class CoreContainer {
    private final Controller controller;
    public CoreContainer() { this(new Controller()); }
    CoreContainer(Controller controller) { this.controller = controller; }
    public Controller getZkController() { return controller; }
    public Path getSolrHome() { return Paths.get("/tmp/mallory-cluster/node1"); }
  }

  public static final class Controller {
    private final Reader reader;
    Controller() { this(new Reader()); }
    Controller(Reader reader) { this.reader = reader; }
    public String getNodeName() { return "solr-node"; }
    public CoreContainer getCoreContainer() { return new CoreContainer(this); }
    public Reader getZkStateReader() { return reader; }
  }

  public static final class ShardContainer {
    private final Controller controller;
    ShardContainer(Controller controller) { this.controller = controller; }
    public Controller getZkController() { return controller; }
    public Path getSolrHome() {
      return Paths.get("/tmp/mallory-trial/shard-2-001");
    }
  }

  public static final class ShardController {
    private final Controller controller = new Controller();
    public String getNodeName() { return "127.0.0.1:43001_"; }
    public ShardContainer getCoreContainer() { return new ShardContainer(controller); }
  }

  public static final class Reader {
    public final AliasesManager aliasesManager = new AliasesManager();
    public final class AliasesManager { }
    public final class StateWatcher {
      private final String coll;
      StateWatcher(String coll) { this.coll = coll; }
    }
    private final Object zkClient;
    Reader() { this(new Object()); }
    Reader(Object zkClient) { this.zkClient = zkClient; }
    public Object getZkClient() { return zkClient; }
  }

  public static final class Filter {
    private final CoreContainer cores;
    Filter(CoreContainer cores) { this.cores = cores; }
  }

  public static final class WatchDispatchWrapper {
    private final Object watcher;
    private final Object this$0;
    WatchDispatchWrapper(Object watcher, Object client) {
      this.watcher = watcher;
      this.this$0 = client;
    }
  }

  @Test public void requestHeaderAndLogicalNodeArePaired() {
    Controller controller = new Controller();
    SolrHooks.registerController(controller);
    Request request = new Request();
    SolrHooks.outbound(new Object(), request);
    assertNotNull(request.token);
    SolrHooks.beginHttp(new Filter(new CoreContainer(controller)), request, false);
    assertEquals("node1", Probe.currentNode());
    assertEquals(request.token, Probe.captureContext());
    SolrHooks.endHttp();
    assertEquals("unknown", Probe.currentNode());
  }

  @Test public void shardDirectoryBecomesStableRoleAcrossEphemeralPorts() {
    ShardController controller = new ShardController();
    SolrHooks.registerController(controller);
    SolrHooks.beginController(controller);
    assertEquals("shard-2", Probe.currentNode());
    SolrHooks.endController();
    assertEquals("unknown", Probe.currentNode());
  }

  @Test public void executorTaskCarriesNodeAndRestoresWorker() {
    try (Probe.NodeScope ignored = Probe.withNode("solr-node", 2)) {
      Runnable task = SolrHooks.wrapTask(new Runnable() {
        @Override public void run() {
          assertEquals("solr-node", Probe.currentNode());
          assertEquals(2, Probe.currentEpoch());
          assertTrue(Probe.captureContext().contains(":task:"));
        }
      });
      Probe.setNode("other-node", 0);
      task.run();
      assertEquals("other-node", Probe.currentNode());
    }
  }

  @Test public void aliasesWatcherCarriesItsOwningServerOnUnrelatedThread() {
    Controller controller = new Controller();
    SolrHooks.registerController(controller);
    assertEquals("unknown", Probe.currentNode());
    SolrHooks.beginAliasesManager(controller.getZkStateReader().aliasesManager);
    assertEquals("node1", Probe.currentNode());
    SolrHooks.endAliasesManager();
    assertEquals("unknown", Probe.currentNode());
    try (Probe.NodeScope client = Probe.withNode("client", 0)) {
      SolrHooks.beginAliasesManager(controller.getZkStateReader().aliasesManager);
      assertEquals("node1", Probe.currentNode());
      SolrHooks.endAliasesManager();
      assertEquals("client", Probe.currentNode());
    }
  }

  @Test public void collectionStateWatcherCarriesRegisteredReaderAndRestoresScope() {
    Controller controller = new Controller();
    SolrHooks.registerController(controller);
    Reader.StateWatcher watcher = controller.getZkStateReader().new StateWatcher("collection1");
    assertEquals("unknown", Probe.currentNode());
    SolrHooks.beginStateWatcher(watcher);
    assertEquals("node1", Probe.currentNode());
    assertTrue(Probe.captureContext().contains("StateWatcher.refreshAndWatch"));
    SolrHooks.endStateWatcher();
    assertEquals("unknown", Probe.currentNode());
  }

  @Test public void zkCallbackSubmitCarriesOnlyTheRegisteredClientOwner() {
    Reader reader = new Reader();
    SolrHooks.registerClientReader(reader);
    SolrHooks.beginZkWatchDispatch(new WatchDispatchWrapper(new Object(), reader.getZkClient()));
    assertEquals("client", Probe.currentNode());
    Runnable callback = SolrHooks.wrapTask(new Runnable() {
      @Override public void run() {
        assertEquals("client", Probe.currentNode());
        assertEquals(0, Probe.currentEpoch());
      }
    });
    SolrHooks.endZkWatchDispatch();
    assertEquals("unknown", Probe.currentNode());
    callback.run();
    assertEquals("unknown", Probe.currentNode());
    SolrHooks.beginZkWatchDispatch(new WatchDispatchWrapper(new Object(), new Object()));
    assertEquals("unknown", Probe.currentNode());
    SolrHooks.endZkWatchDispatch();
  }

  @Test public void sharedZkClientConflictingOwnersStayUnknown() {
    Object shared = new Object();
    Reader clientReader = new Reader(shared);
    SolrHooks.registerClientReader(clientReader);
    Reader serverReader = new Reader(shared);
    Controller server = new Controller(serverReader);
    SolrHooks.registerController(server);
    SolrHooks.beginZkWatchDispatch(new WatchDispatchWrapper(new Object(), shared));
    assertEquals("unknown", Probe.currentNode());
    SolrHooks.endZkWatchDispatch();
    SolrHooks.beginAliasesManager(serverReader.aliasesManager);
    assertEquals("unknown", Probe.currentNode());
    SolrHooks.endAliasesManager();
  }

  @Test public void aliasesManagerUsesItsRegisteredReaderEvenForNewInstance() {
    Reader reader = new Reader();
    SolrHooks.registerClientReader(reader);
    SolrHooks.beginAliasesManager(reader.new AliasesManager());
    assertEquals("client", Probe.currentNode());
    SolrHooks.endAliasesManager();
    assertEquals("unknown", Probe.currentNode());
    SolrHooks.beginAliasesManager(new Reader().new AliasesManager());
    assertEquals("unknown", Probe.currentNode());
    SolrHooks.endAliasesManager();
  }

  @Test public void aliasesManagerDerivesNewReaderOnlyFromUniqueClientOwner() {
    Object sharedClient = new Object();
    Reader registered = new Reader(sharedClient);
    SolrHooks.registerClientReader(registered);
    Reader derived = new Reader(sharedClient);
    SolrHooks.beginAliasesManager(derived.aliasesManager);
    assertEquals("client", Probe.currentNode());
    SolrHooks.endAliasesManager();
    try (Probe.NodeScope scope = Probe.withRegisteredNode(derived)) {
      assertEquals("client", Probe.currentNode());
    }
    assertEquals("unknown", Probe.currentNode());
  }

  @Test public void clientProviderDoesNotRebindServerOwnedReader() {
    Reader serverReader = new Reader();
    Probe.registerNode(serverReader, "node1", 0);
    Probe.registerNode(serverReader.aliasesManager, "node1", 0);
    SolrHooks.registerClientReader(serverReader);
    try (Probe.NodeScope scope = Probe.withRegisteredNode(serverReader)) {
      assertEquals("node1", Probe.currentNode());
    }
    try (Probe.NodeScope scope = Probe.withRegisteredNode(serverReader.aliasesManager)) {
      assertEquals("node1", Probe.currentNode());
    }
  }

  @Test public void transformedControllerSetsNodeBeforeTargetMethod() throws Exception {
    String name = "org/apache/solr/cloud/ZkController";
    InputStream input = getClass().getClassLoader().getResourceAsStream(name + ".class");
    assertNotNull(input);
    ByteArrayOutputStream output = new ByteArrayOutputStream();
    byte[] chunk = new byte[4096];
    for (int read; (read = input.read(chunk)) != -1;) output.write(chunk, 0, read);
    byte[] woven = new SolrTransformer().transform(getClass().getClassLoader(), name, null,
        null, output.toByteArray());
    assertNotNull(woven);
    ChildLoader loader = new ChildLoader(getClass().getClassLoader());
    Class<?> controllerClass = loader.define(woven);
    Object controller = controllerClass.newInstance();
    Object observed = controllerClass.getMethod("register", String.class, Object.class,
        boolean.class, boolean.class, boolean.class)
        .invoke(controller, "core", null, false, false, false);
    assertEquals("node-a", observed);
    assertEquals("unknown", Probe.currentNode());
    try {
      controllerClass.getMethod("register", String.class, Object.class,
          boolean.class, boolean.class, boolean.class)
          .invoke(controller, "core", null, true, false, false);
      fail("expected the fixture's indirect exception");
    } catch (java.lang.reflect.InvocationTargetException expected) {
      assertTrue(expected.getCause() instanceof IllegalStateException);
    }
    assertEquals("unknown", Probe.currentNode());
  }

  @Test public void transformedSolrJClientRestoresActorAfterReturnAndThrow() throws Exception {
    String name = "org/apache/solr/client/solrj/impl/BaseHttpClusterStateProvider";
    InputStream input = getClass().getClassLoader().getResourceAsStream(name + ".class");
    assertNotNull(input);
    ByteArrayOutputStream output = new ByteArrayOutputStream();
    byte[] chunk = new byte[4096];
    for (int read; (read = input.read(chunk)) != -1;) output.write(chunk, 0, read);
    byte[] woven = new SolrTransformer().transform(getClass().getClassLoader(), name, null,
        null, output.toByteArray());
    assertNotNull(woven);
    Class<?> clientClass = new ChildLoader(getClass().getClassLoader()).define(woven);
    Object client = clientClass.newInstance();
    assertNotNull(clientClass.getMethod("getAliases", boolean.class).invoke(client, false));
    assertEquals("unknown", Probe.currentNode());
    try {
      clientClass.getMethod("getAliases", boolean.class).invoke(client, true);
      fail("expected the fixture's exception");
    } catch (java.lang.reflect.InvocationTargetException expected) {
      assertTrue(expected.getCause() instanceof IllegalStateException);
    }
    assertEquals("unknown", Probe.currentNode());
  }

  @Test public void transformedHttp2ClientAddsRequestHeader() throws Exception {
    String name = "org/apache/solr/client/solrj/impl/Http2SolrClient";
    InputStream input = getClass().getClassLoader().getResourceAsStream(name + ".class");
    assertNotNull(input);
    ByteArrayOutputStream output = new ByteArrayOutputStream();
    byte[] chunk = new byte[4096];
    for (int read; (read = input.read(chunk)) != -1;) output.write(chunk, 0, read);
    byte[] woven = new SolrTransformer().transform(getClass().getClassLoader(), name, null,
        null, output.toByteArray());
    assertNotNull(woven);
    Class<?> clientClass = new ChildLoader(getClass().getClassLoader()).define(woven);
    Request request = (Request) clientClass.getMethod("createRequest").invoke(clientClass.newInstance());
    assertNotNull(request.token);
  }

  @Test public void transformedHttpClientAttributesRequestBeforeOutboundSend() throws Exception {
    String name = "org/apache/solr/client/solrj/impl/HttpSolrClient";
    InputStream input = getClass().getClassLoader().getResourceAsStream(name + ".class");
    assertNotNull(input);
    ByteArrayOutputStream output = new ByteArrayOutputStream();
    byte[] chunk = new byte[4096];
    for (int read; (read = input.read(chunk)) != -1;) output.write(chunk, 0, read);
    byte[] woven = new SolrTransformer().transform(getClass().getClassLoader(), name, null,
        null, output.toByteArray());
    assertNotNull(woven);
    Class<?> clientClass = new ChildLoader(getClass().getClassLoader()).define(woven);
    Object client = clientClass.newInstance();
    assertEquals("client", clientClass.getMethod("request", boolean.class).invoke(client, false));
    assertEquals("client", clientClass.getMethod("executeMethod").invoke(client));
    assertNotNull(((Request) clientClass.getMethod("createMethod").invoke(client)).token);
    assertEquals("unknown", Probe.currentNode());
    try {
      clientClass.getMethod("request", boolean.class).invoke(client, true);
      fail("expected the fixture's exception");
    } catch (java.lang.reflect.InvocationTargetException expected) {
      assertTrue(expected.getCause() instanceof IllegalStateException);
    }
    assertEquals("unknown", Probe.currentNode());
  }

  @Test public void transformedOverseerScopesCollectionCommandToServer() throws Exception {
    String name = "org/apache/solr/cloud/api/collections/OverseerCollectionMessageHandler";
    InputStream input = getClass().getClassLoader().getResourceAsStream(name + ".class");
    assertNotNull(input);
    ByteArrayOutputStream output = new ByteArrayOutputStream();
    byte[] chunk = new byte[4096];
    for (int read; (read = input.read(chunk)) != -1;) output.write(chunk, 0, read);
    byte[] woven = new SolrTransformer().transform(getClass().getClassLoader(), name, null,
        null, output.toByteArray());
    assertNotNull(woven);
    Class<?> handler = new ChildLoader(getClass().getClassLoader()).define(woven);
    Object instance = handler.newInstance();
    assertEquals("node1", handler.getMethod("processMessage", Object.class, String.class)
        .invoke(instance, new Object(), "delete"));
    assertEquals("unknown", Probe.currentNode());
    try {
      handler.getMethod("processMessage", Object.class, String.class)
          .invoke(instance, null, "delete");
      fail("expected the fixture's exception");
    } catch (java.lang.reflect.InvocationTargetException expected) {
      assertTrue(expected.getCause() instanceof IllegalStateException);
    }
    assertEquals("unknown", Probe.currentNode());
  }

  @Test public void overseerQueueThreadUsesRegisteredReaderAndRestoresScope() throws Exception {
    String name = "org/apache/solr/cloud/OverseerTaskProcessor";
    InputStream input = getClass().getClassLoader().getResourceAsStream(name + ".class");
    assertNotNull(input);
    ByteArrayOutputStream output = new ByteArrayOutputStream();
    byte[] chunk = new byte[4096];
    for (int read; (read = input.read(chunk)) != -1;) output.write(chunk, 0, read);
    byte[] woven = new SolrTransformer().transform(getClass().getClassLoader(), name, null,
        null, output.toByteArray());
    assertNotNull(woven);
    Class<?> processor = new ChildLoader(getClass().getClassLoader()).define(woven);
    Object reader = new Object();
    Probe.registerNode(reader, "node2", 3);
    Object instance = processor.getConstructor(Object.class, boolean.class)
        .newInstance(reader, false);
    processor.getMethod("run").invoke(instance);
    assertEquals("node2", processor.getField("observedNode").get(instance));
    assertEquals(3, processor.getField("observedEpoch").get(instance));
    assertEquals("unknown", Probe.currentNode());
    Object failing = processor.getConstructor(Object.class, boolean.class)
        .newInstance(reader, true);
    try {
      processor.getMethod("run").invoke(failing);
      fail("expected the fixture's exception");
    } catch (java.lang.reflect.InvocationTargetException expected) {
      assertTrue(expected.getCause() instanceof IllegalStateException);
    }
    assertEquals("node2", processor.getField("observedNode").get(failing));
    assertEquals("unknown", Probe.currentNode());
  }

  @Test public void transformedAliasesWatcherRestoresScopeAfterReturnAndThrow() throws Exception {
    String name = "org/apache/solr/common/cloud/ZkStateReader$AliasesManager";
    InputStream input = getClass().getClassLoader().getResourceAsStream(name + ".class");
    assertNotNull(input);
    ByteArrayOutputStream output = new ByteArrayOutputStream();
    byte[] chunk = new byte[4096];
    for (int read; (read = input.read(chunk)) != -1;) output.write(chunk, 0, read);
    byte[] woven = new SolrTransformer().transform(getClass().getClassLoader(), name, null,
        null, output.toByteArray());
    assertNotNull(woven);
    Class<?> watcherClass = new ChildLoader(getClass().getClassLoader()).define(woven);
    org.apache.solr.common.cloud.ZkStateReader reader =
        new org.apache.solr.common.cloud.ZkStateReader();
    Object watcher = watcherClass.getConstructor(org.apache.solr.common.cloud.ZkStateReader.class)
        .newInstance(reader);
    Probe.registerNode(reader, "node1", 0);
    Probe.registerNode(reader.getZkClient(), "node1", 0);
    assertEquals("node1", watcherClass.getMethod("setIfNewer", Object.class)
        .invoke(watcher, "new"));
    assertEquals("node1", watcherClass.getMethod("update").invoke(watcher));
    assertEquals("node1", watcherClass.getMethod("applyModificationAndExportToZk")
        .invoke(watcher));
    assertEquals("node1", watcherClass.getMethod("process", Object.class)
        .invoke(watcher, "watch"));
    assertEquals("unknown", Probe.currentNode());
    try {
      watcherClass.getMethod("setIfNewer", Object.class).invoke(watcher, new Object[] {null});
      fail("expected the fixture's indirect exception");
    } catch (java.lang.reflect.InvocationTargetException expected) {
      assertTrue(expected.getCause() instanceof IllegalStateException);
    }
    assertEquals("unknown", Probe.currentNode());
  }

  @Test public void clientReaderIsRegisteredBeforeWatchersStart() throws Exception {
    String name = "org/apache/solr/client/solrj/impl/ZkClientClusterStateProvider";
    InputStream input = getClass().getClassLoader().getResourceAsStream(name + ".class");
    assertNotNull(input);
    ByteArrayOutputStream output = new ByteArrayOutputStream();
    byte[] chunk = new byte[4096];
    for (int read; (read = input.read(chunk)) != -1;) output.write(chunk, 0, read);
    byte[] woven = new SolrTransformer().transform(getClass().getClassLoader(), name, null,
        null, output.toByteArray());
    assertNotNull(woven);
    Class<?> provider = new ChildLoader(getClass().getClassLoader()).define(woven);
    Object instance = provider.newInstance();
    org.apache.solr.common.cloud.ZkStateReader reader =
        (org.apache.solr.common.cloud.ZkStateReader) provider.getMethod("getZkStateReader")
            .invoke(instance);
    assertEquals("client", reader.watcherNode);
    SolrHooks.beginAliasesManager(reader.aliasesManager);
    assertEquals("client", Probe.currentNode());
    SolrHooks.endAliasesManager();
    assertEquals("unknown", Probe.currentNode());
  }

  private static final class ChildLoader extends ClassLoader {
    ChildLoader(ClassLoader parent) { super(parent); }
    Class<?> define(byte[] code) { return defineClass(null, code, 0, code.length); }
  }
}
