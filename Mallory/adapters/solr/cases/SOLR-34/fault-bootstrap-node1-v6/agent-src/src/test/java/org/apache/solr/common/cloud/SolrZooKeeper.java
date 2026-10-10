package org.apache.solr.common.cloud;

import org.apache.zookeeper.Watcher;
import org.apache.zookeeper.data.Stat;
import java.nio.charset.StandardCharsets;

public final class SolrZooKeeper {
  public Stat exists(String path, Watcher watcher) { return new Stat(path); }
  public byte[] getData(String path, Watcher watcher, Stat stat) {
    return path.getBytes(StandardCharsets.UTF_8);
  }
}
