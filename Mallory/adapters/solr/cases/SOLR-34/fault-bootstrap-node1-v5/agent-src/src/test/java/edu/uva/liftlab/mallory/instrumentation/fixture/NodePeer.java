package edu.uva.liftlab.mallory.instrumentation.fixture;

public final class NodePeer {
  private final long myid;
  public NodePeer(long myid) { this.myid = myid; }
  public long getServerId() { return myid; }
  public int run(int input) { return input > 0 ? input : -input; }
}
