package org.apache.solr.handler.component;

import java.util.concurrent.Future;

public final class HttpShardHandler {
  private final Future<ShardResponse> future;

  public HttpShardHandler(Future<ShardResponse> future) { this.future = future; }

  protected org.apache.solr.common.util.NamedList request(String url,
      org.apache.solr.client.solrj.SolrRequest request) {
    return new org.apache.solr.common.util.NamedList();
  }

  private ShardResponse take(boolean bailOnError) throws Exception {
    return future.get();
  }

  public ShardResponse waitForResult() throws Exception { return take(false); }
}
