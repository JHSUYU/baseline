package org.apache.solr.client.solrj.impl;

import java.io.IOException;

/** Test-only signature fixture for Solr's HTTP/2 request boundary. */
public class Http2SolrClient {
    public String request(String operation) throws IOException {
        return operation;
    }
}
