package org.apache.solr.cloud;

import edu.uva.liftlab.mallory.instrumentation.Probe;

/** Deliberately named like Solr's controller for transformer verification. */
public final class ZkController {
  public String getNodeName() { return "node-a"; }
  public Object getCoreContainer() { return null; }
  public String register(String core, Object descriptor, boolean a, boolean b, boolean c) {
    if (a) failIndirectly();
    return Probe.currentNode();
  }
  private void failIndirectly() { throw new IllegalStateException("implicit"); }
}
