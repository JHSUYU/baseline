package org.apache.solr.client.solrj.impl;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import edu.uva.liftlab.mallory.solr.SolrHooksTest.Request;

/** Minimal SolrJ-shaped fixture for request actor and outbound header hooks. */
public final class HttpSolrClient {
  public Request createMethod() { return new Request(); }
  public String request(boolean fail) {
    if (fail) throw new IllegalStateException("fixture");
    return Probe.currentNode();
  }
  public String executeMethod() { return Probe.currentNode(); }
}
