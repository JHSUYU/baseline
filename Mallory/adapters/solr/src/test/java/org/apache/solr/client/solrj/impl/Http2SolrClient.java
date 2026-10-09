package org.apache.solr.client.solrj.impl;

import edu.uva.liftlab.mallory.solr.SolrHooksTest.Request;

/** Deliberately named like SolrJ's HTTP/2 client for transformer verification. */
public final class Http2SolrClient {
  public Request createRequest() { return new Request(); }
}
