package org.apache.solr.cloud;

import edu.uva.liftlab.mallory.instrumentation.Probe;

/** Minimal fixture for the overseer queue thread's node binding. */
public final class OverseerTaskProcessor implements Runnable {
  private final Object zkStateReader;
  private final boolean fail;
  public String observedNode;
  public int observedEpoch;

  public OverseerTaskProcessor(Object zkStateReader, boolean fail) {
    this.zkStateReader = zkStateReader;
    this.fail = fail;
  }

  @Override public void run() {
    observedNode = Probe.currentNode();
    observedEpoch = Probe.currentEpoch();
    if (fail) throw new IllegalStateException("fixture failure");
  }
}
