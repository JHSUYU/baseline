package edu.uva.liftlab.mallory.hbase31;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import org.junit.Test;

public class DispatchBindingHooksTest {
  private static final class Dispatcher {
    private final Object master;
    Dispatcher(Object master) { this.master = master; }
    final class RemoteCall { }
  }

  @Test public void exactMasterFollowsWorkerThreadAndScopeRestores() throws Exception {
    Object master0 = new Object();
    Object master1 = new Object();
    Probe.registerNode(master0, "master0", 2);
    Probe.registerNode(master1, "master1", 3);
    Dispatcher.RemoteCall first = new Dispatcher(master0).new RemoteCall();
    Dispatcher.RemoteCall second = new Dispatcher(master1).new RemoteCall();
    ExecutorService worker = Executors.newSingleThreadExecutor();
    try {
      Future<String[]> a = worker.submit(() -> observed(first));
      Future<String[]> b = worker.submit(() -> observed(second));
      String[] left = a.get();
      String[] right = b.get();
      assertEquals("master0", left[0]);
      assertEquals("2", left[1]);
      assertEquals("master1", right[0]);
      assertEquals("3", right[1]);
      assertNotEquals(left[2], right[2]);
      assertFalse(left[2].equals("root"));
      assertEquals("unknown", left[3]);
      assertEquals("unknown", right[3]);
    } finally {
      worker.shutdownNow();
    }
  }

  private static String[] observed(Object call) {
    String before = Probe.currentNode();
    String[] result = new String[4];
    try (Probe.NodeScope ignored = DispatchBindingHooks.enterSendRequest(call)) {
      result[0] = Probe.currentNode();
      result[1] = Integer.toString(Probe.currentEpoch());
      result[2] = Probe.newTaskToken();
    }
    result[3] = Probe.currentNode();
    assertEquals(before, result[3]);
    return result;
  }

  @Test public void nullOrWrongRegisteredOwnerStaysUnknown() {
    Object wrong = new Object();
    Probe.registerNode(wrong, "rs0", 0);
    for (Object candidate : new Object[] { null, wrong, new Object() }) {
      Dispatcher.RemoteCall call = new Dispatcher(candidate).new RemoteCall();
      try (Probe.NodeScope outer = Probe.withNode("client", 4)) {
        try (Probe.NodeScope ignored = DispatchBindingHooks.enterSendRequest(call)) {
          assertEquals("unknown", Probe.currentNode());
        }
        assertEquals("client", Probe.currentNode());
        assertEquals(4, Probe.currentEpoch());
      }
    }
  }
}
