package edu.uva.liftlab.mallory.hbase.hbase28;

import edu.uva.liftlab.mallory.instrumentation.Probe;

/** The MiniCluster passes an explicit index before it invokes the server constructor. */
public final class ConstructorActorHooks {
  private ConstructorActorHooks() { }

  public static Probe.NodeScope enterRegionServer(int index) {
    return Probe.withNode("rs" + index, 0);
  }

  public static Probe.NodeScope enterMaster(int index) {
    return Probe.withNode("master" + index, 0);
  }
}
