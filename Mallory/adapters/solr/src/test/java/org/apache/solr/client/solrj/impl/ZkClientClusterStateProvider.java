package org.apache.solr.client.solrj.impl;

import org.apache.solr.common.cloud.ZkStateReader;

/** Shape of the standalone SolrJ reader initialization boundary. */
public final class ZkClientClusterStateProvider {
  private ZkStateReader zkStateReader;

  public ZkClientClusterStateProvider() { }

  public ZkStateReader getZkStateReader() {
    if (zkStateReader == null) {
      ZkStateReader zk = new ZkStateReader();
      zk.createClusterStateWatchersAndUpdate();
      zkStateReader = zk;
    }
    return zkStateReader;
  }
}
