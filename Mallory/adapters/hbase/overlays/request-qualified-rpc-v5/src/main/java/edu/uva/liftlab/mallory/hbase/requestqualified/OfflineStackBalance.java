package edu.uva.liftlab.mallory.hbase.requestqualified;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.io.IOException;
import java.lang.reflect.Field;
import java.util.Deque;

/** No cluster or agent: verify both base close paths leave no Probe region. */
public final class OfflineStackBalance {
  private static final String PORT = "hbase.pb.MasterService.UnassignRegion";
  private OfflineStackBalance() { }

  public static void main(String[] args) throws Exception {
    if (!"HBASE-10".equals(System.getProperty("mallory.hbase.rpc.door.case")))
      throw new IllegalStateException("Run with HBASE-10 selected");
    Probe.setNode("master0", 0);
    try (Probe.ContextScope context = Probe.withCausalContext("offline:task:234")) {
      run(false);
      run(true);
      // An inner unselected RpcServer.call must not pop the selected outer region.
      RequestQualifiedRpcHooks.enterMethod();
      RequestQualifiedRpcHooks.beforeDispatch(new OfflinePreflight.FakeCall(
          PORT));
      RequestQualifiedRpcHooks.enterMethod();
      RequestQualifiedRpcHooks.beforeDispatch(new OfflinePreflight.FakeCall(
          "hbase.pb.MasterService.AssignRegion"));
      RequestQualifiedRpcHooks.closeServerScope(new Response(false));
      if (regions() != 1) throw new IllegalStateException("Nested close popped outer region");
      RequestQualifiedRpcHooks.closeServerScope(new Response(false));
      if (regions() != 0) throw new IllegalStateException("Nested region leaked");
    }
    System.out.println("OFFLINE_STACK_BALANCE_OK normal=1 exceptional=1 nested=1");
  }

  private static void run(boolean throwsOnClose) throws Exception {
    RequestQualifiedRpcHooks.enterMethod();
    RequestQualifiedRpcHooks.beforeDispatch(new OfflinePreflight.FakeCall(
        PORT));
    if (regions() != 1) throw new IllegalStateException("Selected region did not enter");
    Probe.regionEnter("offline:preTransitCheck");
    if (regions() != 2) throw new IllegalStateException("Target region was not nested");
    Probe.regionExit("offline:preTransitCheck");
    boolean threw = false;
    try {
      RequestQualifiedRpcHooks.closeServerScope(new Response(throwsOnClose));
    } catch (Exception expected) {
      if (!(expected instanceof IOException)) throw expected;
      threw = true;
    }
    if (threw != throwsOnClose || regions() != 0)
      throw new IllegalStateException("Region leaked or exception path changed");
  }

  private static int regions() throws Exception {
    Field contextField = Probe.class.getDeclaredField("CONTEXT");
    contextField.setAccessible(true);
    Object context = ((ThreadLocal<?>) contextField.get(null)).get();
    Field framesField = context.getClass().getDeclaredField("frames");
    framesField.setAccessible(true);
    return ((Deque<?>) framesField.get(context)).size();
  }

  private static final class Response implements AutoCloseable {
    private final boolean fail;
    Response(boolean fail) { this.fail = fail; }
    @Override public void close() throws IOException {
      Probe.send("hbase-rpc-response", "offline:task:234",
          PORT, "hbase:RpcServer.call:completion");
      if (fail) throw new IOException("offline close failure");
    }
  }
}
