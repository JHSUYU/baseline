package baseline.solr05;
public final class ProbePhaseSmoke {
  public static void main(String[] args) throws Exception {
    FeedbackProbe.io("B", "/y");
    FeedbackProbe.io("A", "/x");
    try { FeedbackProbe.io("A", "/x"); } catch (org.apache.zookeeper.KeeperException.ConnectionLossException expected) {}
    try { FeedbackProbe.io("B", "/y"); } catch (org.apache.zookeeper.KeeperException.ConnectionLossException expected) {}
  }
}
