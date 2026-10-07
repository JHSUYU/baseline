package baseline.solr103940;

import org.apache.zookeeper.KeeperException;

/** No ZooKeeper or embedded cluster: rejects wrong receiver despite identical API call. */
public final class SmokeProbe {
  public static void main(String[] args) throws Exception {
    Object right = new Object();
    Object wrong = new Object();
    Object rightManager = new Object();
    Object wrongManager = new Object();
    FeedbackProbe.registerNode(right, rightManager, "127.0.0.1:12345_solr");
    FeedbackProbe.registerNode(wrong, wrongManager, "127.0.0.1:23456_solr");
    FeedbackProbe.registerJettyRole("node1", "127.0.0.1:12345_solr");
    FeedbackProbe.registerJettyRole("node2", "127.0.0.1:23456_solr");
    for (int round = 0; round < 2; round++) {
      FeedbackProbe.io("GET_DATA", "/aliases.json", wrong);
      try {
        FeedbackProbe.io("GET_DATA", "/aliases.json", right);
        throw new AssertionError("Selected actor was not injected in round " + round);
      } catch (KeeperException.ConnectionLossException expected) {
        // The target client is the only receiver allowed to consume either ordinal.
      }
    }
    for (String site : new String[] {"SOLR-10", "SOLR-39", "SOLR-40"})
      FeedbackProbe.targetCheck(false, site, "myalias", "smoke", right,
          rightManager, "127.0.0.1:12345_solr");
    try {
      FeedbackProbe.targetCheck(false, "SOLR-40", "myalias", "wrong manager",
          right, wrongManager, "127.0.0.1:12345_solr");
      throw new AssertionError("Wrong AliasesManager was accepted");
    } catch (IllegalStateException expected) {
      // Reference equality is required; equal-looking runtime labels are insufficient.
    }
    System.out.println("SOLR103940_V2_SMOKE_PASS");
  }
}
