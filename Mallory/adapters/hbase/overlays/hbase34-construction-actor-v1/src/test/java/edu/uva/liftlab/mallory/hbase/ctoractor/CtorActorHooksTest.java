package edu.uva.liftlab.mallory.hbase.ctoractor;

import static org.junit.Assert.assertEquals;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import org.junit.Test;

public class CtorActorHooksTest {
  @Test public void exactFactoryIndexScopesAndRestoresNode() {
    Probe.setNode("client", 0);
    try (Probe.NodeScope ignored = CtorActorHooks.enterRegionServer(0)) {
      assertEquals("rs0", Probe.currentNode());
    }
    assertEquals("client", Probe.currentNode());
    try (Probe.NodeScope ignored = CtorActorHooks.enterMaster(1)) {
      assertEquals("master1", Probe.currentNode());
    }
    assertEquals("client", Probe.currentNode());
  }
}
