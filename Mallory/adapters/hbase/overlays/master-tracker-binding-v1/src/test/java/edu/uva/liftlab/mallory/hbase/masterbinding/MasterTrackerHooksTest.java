package edu.uva.liftlab.mallory.hbase.masterbinding;

import static org.junit.Assert.assertEquals;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import org.junit.Test;

public class MasterTrackerHooksTest {
  private static class Listener {
    @SuppressWarnings("unused") private final Object watcher;
    Listener(Object watcher) { this.watcher = watcher; }
  }

  private static final class Manager extends Listener {
    @SuppressWarnings("unused") private final Object master;
    Manager(Object master, Object watcher) {
      super(watcher);
      this.master = master;
    }
  }

  @Test public void bindsInheritedWatcherFromRegisteredMasterIdentity() {
    Object master = new Object();
    Object watcher = new Object();
    Probe.registerNode(master, "master0", 0);
    MasterTrackerHooks.bindWatcherFromManager(new Manager(master, watcher));
    try (Probe.NodeScope ignored = Probe.withRegisteredNode(watcher)) {
      assertEquals("master0", Probe.currentNode());
    }
  }

  @Test public void unregisteredMasterDoesNotInventWatcherIdentity() {
    Object watcher = new Object();
    MasterTrackerHooks.bindWatcherFromManager(new Manager(new Object(), watcher));
    try (Probe.NodeScope ignored = Probe.withRegisteredNode(watcher)) {
      assertEquals("unknown", Probe.currentNode());
    }
  }

  @Test public void nullWatcherDoesNotChangeCallerIdentity() {
    Object master = new Object();
    Probe.registerNode(master, "master1", 0);
    try (Probe.NodeScope ignored = Probe.withNode("client", 0)) {
      MasterTrackerHooks.bindWatcherFromManager(new Manager(master, null));
      assertEquals("client", Probe.currentNode());
    }
  }
}
