package org.apache.solr.cloud.api.collections;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import edu.uva.liftlab.mallory.solr.SolrHooksTest.CoreContainer;

/** Deliberately named like Solr's collection command dispatcher. */
public final class OverseerCollectionMessageHandler {
  public final Overseer overseer = new Overseer();

  public String processMessage(Object message, String operation) {
    if (message == null) throw new IllegalStateException("test failure");
    return Probe.currentNode();
  }

  public static final class Overseer {
    public CoreContainer getCoreContainer() { return new CoreContainer(); }
  }
}
