package org.apache.solr.client.solrj.impl;

import edu.uva.liftlab.mallory.instrumentation.Probe;
import java.util.Collections;
import java.util.Map;

/** Small class-file fixture for the SolrJ client actor scope. */
public class BaseHttpClusterStateProvider {
  public Map<String, String> getAliases(boolean fail) {
    if (!"client".equals(Probe.currentNode()))
      throw new AssertionError("missing client identity");
    if (fail) throw new IllegalStateException("fixture failure");
    return Collections.singletonMap("alias", "collection");
  }
}
