package edu.uva.liftlab.mallory.hbase.ctoractor;

import edu.uva.liftlab.mallory.instrumentation.Probe;

/** The JVMClusterUtil factory's explicit MiniCluster index owns the constructor. */
public final class CtorActorHooks {
  private CtorActorHooks() { }

  public static Probe.NodeScope enterRegionServer(int index) {
    return Probe.withNode("rs" + index, 0);
  }

  public static Probe.NodeScope enterMaster(int index) {
    return Probe.withNode("master" + index, 0);
  }
}
