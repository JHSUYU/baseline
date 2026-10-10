package org.apache.hadoop.hbase.zookeeper;

/** Tiny bytecode fixture with the same monitor call shapes as HBase 2.6.6. */
public class ZKNodeTracker extends ZKListener {
  private byte[] data;

  public synchronized void start() { }

  public synchronized byte[] blockUntilAvailable(long timeout, boolean refresh)
      throws InterruptedException {
    if (data == null) wait(timeout);
    return data;
  }

  public synchronized void nodeCreated(String path) {
    data = new byte[] {1};
    notifyAll();
  }

  public synchronized void nodeDeleted(String path) { data = null; }

  public synchronized void stop() { notifyAll(); }
}
