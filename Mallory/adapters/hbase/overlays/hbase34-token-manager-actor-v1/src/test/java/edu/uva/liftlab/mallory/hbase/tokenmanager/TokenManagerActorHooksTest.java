package edu.uva.liftlab.mallory.hbase.tokenmanager;

import static org.junit.Assert.assertEquals;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import org.junit.Test;

public class TokenManagerActorHooksTest {
  private static class Listener { final Object watcher; Listener(Object watcher) { this.watcher = watcher; } }
  private static final class SecretListener extends Listener { SecretListener(Object w) { super(w); } }
  private static final class Manager { final Object zkWatcher; Manager(Object w) { zkWatcher = new SecretListener(w); } }

  @Test public void exactRegisteredWatcherBindsOwnerAndRestoresPriorScope() {
    Object regionServerWatcher = new Object();
    Object masterWatcher = new Object();
    Probe.registerNode(regionServerWatcher, "rs0", 0);
    Probe.registerNode(masterWatcher, "master0", 0);
    Probe.setNode("client", 0);
    try (Probe.NodeScope ignored = TokenManagerActorHooks.enter(new Manager(regionServerWatcher))) {
      assertEquals("rs0", Probe.currentNode());
    }
    assertEquals("client", Probe.currentNode());
    try (Probe.NodeScope ignored = TokenManagerActorHooks.enter(new Manager(masterWatcher))) {
      assertEquals("master0", Probe.currentNode());
    }
    assertEquals("client", Probe.currentNode());
  }

  @Test public void missingOrUnregisteredWatcherDoesNotGuessActor() {
    Probe.setNode("client", 0);
    try (Probe.NodeScope ignored = TokenManagerActorHooks.enter(new Manager(new Object()))) {
      assertEquals("unknown", Probe.currentNode());
    }
    assertEquals("client", Probe.currentNode());
    try (Probe.NodeScope ignored = TokenManagerActorHooks.enter(new Object())) {
      assertEquals("unknown", Probe.currentNode());
    }
    assertEquals("client", Probe.currentNode());
  }
}
