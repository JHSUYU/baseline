package org.apache.solr.common.cloud;

import org.apache.zookeeper.Watcher;
import org.apache.zookeeper.data.Stat;

/** Test-only fixture with the pinned Solr 8.11.4 lambda descriptor. */
public final class SolrZkClient {
  private final SolrZooKeeper keeper = new SolrZooKeeper();

  private Stat lambda$exists$2(String path, Watcher watcher) {
    return keeper.exists(path, watcher);
  }

  private byte[] lambda$getData$6(String path, Watcher watcher, Stat stat) {
    return keeper.getData(path, watcher, stat);
  }

  public Stat lookup(String path) { return lambda$exists$2(path, null); }
  public byte[] readData(String path) { return lambda$getData$6(path, null, null); }
}
