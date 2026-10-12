package org.apache.solr.handler.component;

import java.util.concurrent.Callable;

public final class ShardRequestor implements Callable<ShardResponse> {
  private final Params params = new Params();

  public static final class Params {
    public String get(String key) { return "action".equals(key) ? "UNLOAD" : null; }
  }

  @Override public ShardResponse call() {
    new HttpShardHandler(null).request("http://node1", new org.apache.solr.client.solrj.SolrRequest());
    return new ShardResponse();
  }
}
